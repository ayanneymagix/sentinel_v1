"""
Sentinel Phase 2 — Model 2: RTSP Source Adapter
Consumes standalone IP camera / NVR RTSP stream endpoints using TCP transport.
"""

import socket
import logging
from urllib.parse import urlparse
from typing import Any, Dict, List, Optional
from app.adapters.base import (
    CameraSourceAdapter,
    NormalizedSourceCamera,
    SourceHealthResult,
    SourceProbeResult,
    StreamEndpoint
)

logger = logging.getLogger("sentinel.adapter.rtsp")


class RTSPSourceAdapter(CameraSourceAdapter):
    """
    Adapter for direct RTSP stream feeds (e.g. standalone IP cameras or local NVR channels).
    Enforces TCP transport for AI inference stability.
    """

    def __init__(self, source_id: str, source_name: str, endpoint_url: str, config: Optional[Dict[str, Any]] = None):
        super().__init__(source_id, source_name, "RTSP", endpoint_url, config)
        self.camera_id = self.config.get("camera_id") or source_id.lower()

    async def probe(self) -> SourceProbeResult:
        """
        Probes the RTSP socket port for TCP reachability.
        """
        parsed = urlparse(self.endpoint_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 554

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2.0)
            res = sock.connect_ex((host, port))
            sock.close()
            is_open = (res == 0)

            return SourceProbeResult(
                source_id=self.source_id,
                is_reachable=is_open,
                status="ACTIVE" if is_open else "OFFLINE",
                health_status="HEALTHY" if is_open else "OFFLINE",
                discovered_camera_count=1 if is_open else 0,
                capabilities={"rtsp": True, "hls": False, "webrtc": False, "transport": "TCP"},
                error_message=None if is_open else f"TCP connection to RTSP host {host}:{port} refused (error {res})"
            )
        except Exception as e:
            return SourceProbeResult(
                source_id=self.source_id,
                is_reachable=False,
                status="ERROR",
                health_status="OFFLINE",
                error_message=f"RTSP probe error: {e}"
            )

    async def discover_cameras(self) -> List[NormalizedSourceCamera]:
        probe_res = await self.probe()
        is_live = probe_res.is_reachable
        return [
            NormalizedSourceCamera(
                camera_id=self.camera_id,
                source_id=self.source_id,
                source_name=self.source_name,
                name=self.config.get("name") or f"RTSP Camera ({self.camera_id})",
                city=self.config.get("city") or "Gujarat",
                district=self.config.get("district"),
                latitude=self.config.get("latitude"),
                longitude=self.config.get("longitude"),
                codec=self.config.get("codec") or "h264",
                resolution=self.config.get("resolution") or "1920x1080",
                fps=self.config.get("fps") or 25.0,
                status="online" if is_live else "offline",
                health="ONLINE" if is_live else "OFFLINE",
                endpoints={"rtsp": self.endpoint_url},
                stream_endpoints=[
                    StreamEndpoint(protocol="RTSP", url=self.endpoint_url, is_available=is_live, latency_profile="STREAMING")
                ],
                capabilities={"rtsp": True, "hls": False, "webrtc": False, "ptz": False},
                metadata={"transport": "TCP", "auth_required": bool(self.config.get("auth"))}
            )
        ]

    async def get_camera(self, camera_id: str) -> Optional[NormalizedSourceCamera]:
        cams = await self.discover_cameras()
        return next((c for c in cams if c.camera_id.lower() == camera_id.lower()), None)

    async def get_stream(self, camera_id: str, protocol: str) -> Optional[StreamEndpoint]:
        if protocol.upper() != "RTSP":
            return None
        return StreamEndpoint(protocol="RTSP", url=self.endpoint_url, is_available=True, latency_profile="STREAMING")

    async def get_health(self) -> SourceHealthResult:
        probe_res = await self.probe()
        return SourceHealthResult(
            source_id=self.source_id,
            status=probe_res.status,
            health_status=probe_res.health_status,
            gateway_reachable=probe_res.is_reachable,
            auth_valid=probe_res.is_reachable,
            camera_discovery_working=probe_res.is_reachable,
            stream_availability="AVAILABLE" if probe_res.is_reachable else "UNAVAILABLE",
            active_camera_count=1 if probe_res.is_reachable else 0,
            total_camera_count=1,
            diagnostic_message="RTSP TCP socket operational" if probe_res.is_reachable else probe_res.error_message
        )
