"""
Sentinel Phase 2 — Model 2: Vendor SDK Adapter Stub
Provides extensible abstraction for proprietary vendor binary SDKs
(Hikvision NetSDK, Dahua NetSDK, Axis VAPIX, Bosch VIP).
Adheres strictly to the Zero-Fabricated-Data rule: returns NOT_CONFIGURED
when vendor native binary drivers are not mounted.
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

logger = logging.getLogger("sentinel.adapter.vendor_sdk")


class VendorSDKAdapter(CameraSourceAdapter):
    """
    Extensible adapter hook for vendor-specific native SDKs.
    """

    def __init__(self, source_id: str, source_name: str, endpoint_url: str, config: Optional[Dict[str, Any]] = None):
        super().__init__(source_id, source_name, "VENDOR_SDK", endpoint_url, config)
        self.sdk_name = self.config.get("sdk_name", "GENERIC_SDK")

    async def probe(self) -> SourceProbeResult:
        return SourceProbeResult(
            source_id=self.source_id,
            is_reachable=False,
            status="NOT_CONFIGURED",
            health_status="UNKNOWN",
            error_message=f"Vendor SDK '{self.sdk_name}' driver not mounted. Read-only consumption interface ready.",
            capabilities={"vendor_sdk": self.sdk_name, "native_bindings": False}
        )

    async def discover_cameras(self) -> List[NormalizedSourceCamera]:
        return []

    async def get_camera(self, camera_id: str) -> Optional[NormalizedSourceCamera]:
        return None

    async def get_stream(self, camera_id: str, protocol: str) -> Optional[StreamEndpoint]:
        return None

    async def get_health(self) -> SourceHealthResult:
        return SourceHealthResult(
            source_id=self.source_id,
            status="NOT_CONFIGURED",
            health_status="UNKNOWN",
            gateway_reachable=False,
            auth_valid=False,
            camera_discovery_working=False,
            stream_availability="UNAVAILABLE",
            active_camera_count=0,
            total_camera_count=0,
            diagnostic_message=f"Vendor SDK {self.sdk_name} driver unmounted."
        )
