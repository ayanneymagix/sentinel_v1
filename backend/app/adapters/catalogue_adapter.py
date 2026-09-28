"""
Sentinel Phase 2 — Model 2: Catalogue Source Adapter
Connects to the Real Gujarat Police Dynamic Camera Catalogue & Gateway.
"""

import time
import logging
from typing import Any, Dict, List, Optional
from app.adapters.base import (
    CameraSourceAdapter,
    NormalizedSourceCamera,
    SourceHealthResult,
    SourceProbeResult,
    StreamEndpoint
)
from app.services.catalogue_service import CameraCatalogueService

logger = logging.getLogger("sentinel.adapter.catalogue")


class CatalogueSourceAdapter(CameraSourceAdapter):
    """
    Adapter consuming cameras from the dynamic Gujarat Camera Gateway (/api/ingest).
    This is the primary authoritative Phase 0 & Phase 1 live feed source.
    """

    def __init__(self, source_id: str = "SRC_GUJ_GATEWAY", source_name: str = "Gujarat Police Dynamic Camera Gateway", endpoint_url: str = "http://cctv.corp8.cloud/api/ingest", config: Optional[Dict[str, Any]] = None):
        super().__init__(source_id, source_name, "GATEWAY_CATALOGUE", endpoint_url, config)
        self._catalogue_service = CameraCatalogueService.get_instance()

    async def probe(self) -> SourceProbeResult:
        start_t = time.perf_counter()
        try:
            cameras = await self._catalogue_service.fetch_catalogue()
            elapsed_ms = (time.perf_counter() - start_t) * 1000.0
            is_ok = len(cameras) > 0
            return SourceProbeResult(
                source_id=self.source_id,
                is_reachable=is_ok,
                status="ACTIVE" if is_ok else "OFFLINE",
                health_status="HEALTHY" if is_ok else "OFFLINE",
                latency_ms=round(elapsed_ms, 2),
                discovered_camera_count=len(cameras),
                capabilities={
                    "hls": True,
                    "webrtc": True,
                    "rtsp": True,
                    "ptz": False,
                    "discovery": True,
                    "analytics_ingestion": True
                },
                error_message=None if is_ok else "Gateway returned 0 cameras or rate limit reached"
            )
        except Exception as e:
            elapsed_ms = (time.perf_counter() - start_t) * 1000.0
            logger.warning("Catalogue probe failed: %s", e)
            return SourceProbeResult(
                source_id=self.source_id,
                is_reachable=False,
                status="OFFLINE",
                health_status="OFFLINE",
                latency_ms=round(elapsed_ms, 2),
                discovered_camera_count=0,
                error_message=str(e),
                capabilities={"hls": True, "webrtc": True, "rtsp": True}
            )

    async def discover_cameras(self) -> List[NormalizedSourceCamera]:
        raw_cams = await self._catalogue_service.get_cameras()
        normalized = []
        for c in raw_cams:
            cid = c.get("camera_id") or c.get("id")
            if not cid:
                continue

            endpoints_dict = c.get("endpoints") or {}
            hls_ep = endpoints_dict.get("hls") or c.get("hls_url") or f"/api/cameras/{cid}/hls/index.m3u8"
            webrtc_ep = endpoints_dict.get("whep") or c.get("whep_url") or f"/stream/{cid}/whep"
            rtsp_ep = endpoints_dict.get("rtsp") or c.get("rtsp_url")

            stream_eps = [
                StreamEndpoint(protocol="HLS", url=hls_ep, is_available=True, latency_profile="BUFFERED")
            ]
            if webrtc_ep:
                stream_eps.append(StreamEndpoint(protocol="WEBRTC", url=webrtc_ep, is_available=True, latency_profile="LOW_LATENCY"))
            if rtsp_ep:
                stream_eps.append(StreamEndpoint(protocol="RTSP", url=rtsp_ep, is_available=True, latency_profile="STREAMING"))

            cam = NormalizedSourceCamera(
                camera_id=cid,
                source_id=self.source_id,
                source_name=self.source_name,
                name=c.get("name") or f"Camera {cid}",
                city=c.get("city") or "Gujarat",
                district=c.get("district") or c.get("city"),
                latitude=c.get("latitude"),
                longitude=c.get("longitude"),
                codec=c.get("codec") or "h264",
                resolution=c.get("resolution") or "1920x1080",
                fps=c.get("fps") or 25.0,
                status=c.get("status") or "online",
                health="ONLINE" if (c.get("status") == "online" or c.get("live_status") == "LIVE") else "OFFLINE",
                endpoints=endpoints_dict,
                stream_endpoints=stream_eps,
                capabilities={"hls": True, "webrtc": bool(webrtc_ep), "rtsp": bool(rtsp_ep), "ptz": False},
                metadata={
                    "source_type": self.source_type,
                    "live_status": c.get("live_status", "LIVE"),
                    "calibrated": c.get("calibrated", False)
                }
            )
            normalized.append(cam)
        return normalized

    async def get_camera(self, camera_id: str) -> Optional[NormalizedSourceCamera]:
        cams = await self.discover_cameras()
        return next((c for c in cams if c.camera_id.lower() == camera_id.lower()), None)

    async def get_stream(self, camera_id: str, protocol: str) -> Optional[StreamEndpoint]:
        cam = await self.get_camera(camera_id)
        if not cam:
            return None
        proto_upper = protocol.upper()
        return next((ep for ep in cam.stream_endpoints if ep.protocol == proto_upper), None)

    async def get_health(self) -> SourceHealthResult:
        try:
            cams = await self._catalogue_service.get_cameras()
            active_count = sum(1 for c in cams if c.get("status") == "online" or c.get("live_status") == "LIVE")
            total_count = len(cams)
            is_healthy = total_count > 0

            return SourceHealthResult(
                source_id=self.source_id,
                status="ACTIVE" if is_healthy else "DEGRADED",
                health_status="HEALTHY" if active_count > 0 else "OFFLINE",
                gateway_reachable=is_healthy,
                auth_valid=True,
                camera_discovery_working=total_count > 0,
                stream_availability="AVAILABLE" if active_count > 0 else "UNAVAILABLE",
                active_camera_count=active_count,
                total_camera_count=total_count,
                diagnostic_message=f"Gujarat Police Gateway responding with {total_count} cameras ({active_count} active streams)."
            )
        except Exception as e:
            return SourceHealthResult(
                source_id=self.source_id,
                status="ERROR",
                health_status="OFFLINE",
                gateway_reachable=False,
                auth_valid=False,
                camera_discovery_working=False,
                stream_availability="UNAVAILABLE",
                active_camera_count=0,
                total_camera_count=0,
                diagnostic_message=f"Gateway health probe error: {e}"
            )
