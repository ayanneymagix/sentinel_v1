"""
Sentinel Phase 2 — Model 2: Source Adapter Manager
Orchestrates multi-source CCTV/VMS adapters and unified stream routing.
"""

import logging
from typing import Any, Dict, List, Optional
from app.adapters.base import (
    CameraSourceAdapter,
    NormalizedSourceCamera,
    SourceHealthResult,
    SourceProbeResult,
    StreamEndpoint
)
from app.adapters.catalogue_adapter import CatalogueSourceAdapter
from app.adapters.onvif_adapter import ONVIFSourceAdapter
from app.adapters.rtsp_adapter import RTSPSourceAdapter
from app.adapters.vendor_sdk_adapter import VendorSDKAdapter
from app.adapters.vms_api_adapter import VMSAPIAdapter
from app.database.postgres import postgres

logger = logging.getLogger("sentinel.adapter.manager")


class SourceAdapterManager:
    _instance: Optional["SourceAdapterManager"] = None

    def __init__(self):
        self._adapters: Dict[str, CameraSourceAdapter] = {}
        # Pre-seed default Gujarat Gateway
        self.register_adapter(CatalogueSourceAdapter())

    @classmethod
    def get_instance(cls) -> "SourceAdapterManager":
        if cls._instance is None:
            cls._instance = SourceAdapterManager()
        return cls._instance

    def register_adapter(self, adapter: CameraSourceAdapter):
        self._adapters[adapter.source_id] = adapter
        logger.info("Registered VMS adapter: [%s] %s (%s)", adapter.source_id, adapter.source_name, adapter.source_type)

    def get_adapter(self, source_id: str) -> Optional[CameraSourceAdapter]:
        return self._adapters.get(source_id)

    def list_adapters(self) -> List[CameraSourceAdapter]:
        return list(self._adapters.values())

    async def reload_from_db(self):
        """
        Loads all configured sources from PostgreSQL and initializes corresponding adapters.
        """
        if not postgres.pool:
            return

        try:
            async with postgres.pool.acquire() as conn:
                rows = await conn.fetch("SELECT * FROM public.vms_sources WHERE is_active = true;")
                for r in rows:
                    sid = r["source_id"]
                    stype = r["source_type"]
                    sname = r["source_name"]
                    endpoint = r["endpoint_url"]
                    config = r["config"] or {}

                    if sid in self._adapters:
                        continue

                    adapter = self._create_adapter(sid, sname, stype, endpoint, config)
                    if adapter:
                        self.register_adapter(adapter)
        except Exception as e:
            logger.warning("Error reloading VMS adapters from database: %s", e)

    def _create_adapter(self, source_id: str, source_name: str, source_type: str, endpoint: str, config: Dict[str, Any]) -> Optional[CameraSourceAdapter]:
        stype = source_type.upper()
        if stype == "GATEWAY_CATALOGUE":
            return CatalogueSourceAdapter(source_id, source_name, endpoint, config)
        elif stype == "RTSP":
            return RTSPSourceAdapter(source_id, source_name, endpoint, config)
        elif stype == "ONVIF":
            return ONVIFSourceAdapter(source_id, source_name, endpoint, config)
        elif stype == "VMS_API":
            return VMSAPIAdapter(source_id, source_name, endpoint, config)
        elif stype == "VENDOR_SDK":
            return VendorSDKAdapter(source_id, source_name, endpoint, config)
        else:
            return RTSPSourceAdapter(source_id, source_name, endpoint, config)

    async def discover_all_cameras(self) -> List[NormalizedSourceCamera]:
        """
        Polls all active adapters and unifies cameras under canonical identities.
        """
        all_cams: List[NormalizedSourceCamera] = []
        seen_ids = set()

        for adapter in self._adapters.values():
            try:
                cams = await adapter.discover_cameras()
                for c in cams:
                    cid_lower = c.camera_id.lower()
                    if cid_lower not in seen_ids:
                        all_cams.append(c)
                        seen_ids.add(cid_lower)
            except Exception as e:
                logger.warning("Failed discovering cameras from adapter %s: %s", adapter.source_id, e)

        return all_cams

    async def get_camera(self, camera_id: str) -> Optional[NormalizedSourceCamera]:
        cid_lower = camera_id.lower()
        for adapter in self._adapters.values():
            try:
                cam = await adapter.get_camera(cid_lower)
                if cam:
                    return cam
            except Exception:
                continue
        return None

    async def resolve_stream(self, camera_id: str, protocol: str) -> Optional[StreamEndpoint]:
        cid_lower = camera_id.lower()
        for adapter in self._adapters.values():
            try:
                stream = await adapter.get_stream(cid_lower, protocol)
                if stream:
                    return stream
            except Exception:
                continue
        return None

    async def probe_source(self, source_id: str) -> Optional[SourceProbeResult]:
        adapter = self.get_adapter(source_id)
        if not adapter:
            return None
        return await adapter.probe()

    async def get_source_health(self, source_id: str) -> Optional[SourceHealthResult]:
        adapter = self.get_adapter(source_id)
        if not adapter:
            return None
        return await adapter.get_health()
