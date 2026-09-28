"""
Sentinel Phase 2 — Model 2: Source System Abstraction & Adapters
Base Adapter Interface and Normalized Data Models
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class StreamEndpoint(BaseModel):
    protocol: str = Field(..., description="HLS, WEBRTC, or RTSP")
    url: str = Field(..., description="Direct or proxied stream URL")
    is_available: bool = Field(True, description="Whether endpoint is active")
    latency_profile: str = Field("STANDARD", description="LOW_LATENCY (WebRTC), BUFFERED (HLS), STREAMING (RTSP)")


class NormalizedSourceCamera(BaseModel):
    camera_id: str
    source_id: str
    source_name: str
    name: str
    city: Optional[str] = "Gujarat"
    district: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    codec: Optional[str] = "h264"
    resolution: Optional[str] = "1920x1080"
    fps: Optional[float] = 25.0
    status: str = "online" # online, offline, degraded, unknown
    health: str = "ONLINE" # ONLINE, OFFLINE, DEGRADED, UNKNOWN
    endpoints: Dict[str, str] = Field(default_factory=dict)
    stream_endpoints: List[StreamEndpoint] = Field(default_factory=list)
    capabilities: Dict[str, bool] = Field(default_factory=lambda: {"hls": True, "webrtc": True, "rtsp": True, "ptz": False})
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SourceProbeResult(BaseModel):
    source_id: str
    is_reachable: bool
    status: str # ACTIVE, NOT_CONFIGURED, OFFLINE, ERROR
    health_status: str # HEALTHY, DEGRADED, OFFLINE, UNKNOWN
    latency_ms: Optional[float] = None
    discovered_camera_count: int = 0
    error_message: Optional[str] = None
    capabilities: Dict[str, Any] = Field(default_factory=dict)
    checked_at: datetime = Field(default_factory=datetime.utcnow)


class SourceHealthResult(BaseModel):
    source_id: str
    status: str # ACTIVE, NOT_CONFIGURED, OFFLINE, ERROR
    health_status: str # HEALTHY, DEGRADED, OFFLINE, UNKNOWN
    gateway_reachable: bool = False
    auth_valid: bool = False
    camera_discovery_working: bool = False
    stream_availability: str = "UNKNOWN" # AVAILABLE, DEGRADED, UNAVAILABLE, UNKNOWN
    active_camera_count: int = 0
    total_camera_count: int = 0
    diagnostic_message: Optional[str] = None
    checked_at: datetime = Field(default_factory=datetime.utcnow)


class CameraSourceAdapter(ABC):
    """
    Abstract Base Class for all Sentinel Model 2 Source Adapters.
    Encapsulates interaction with independent external CCTV/VMS systems.
    """

    def __init__(self, source_id: str, source_name: str, source_type: str, endpoint_url: str, config: Optional[Dict[str, Any]] = None):
        self.source_id = source_id
        self.source_name = source_name
        self.source_type = source_type
        self.endpoint_url = endpoint_url
        self.config = config or {}

    @abstractmethod
    async def probe(self) -> SourceProbeResult:
        """
        Tests reachability, credentials, and handshake without altering source system.
        """
        pass

    @abstractmethod
    async def discover_cameras(self) -> List[NormalizedSourceCamera]:
        """
        Discovers all available camera channels from the source system.
        """
        pass

    @abstractmethod
    async def get_camera(self, camera_id: str) -> Optional[NormalizedSourceCamera]:
        """
        Retrieves normalized metadata for a specific camera channel.
        """
        pass

    @abstractmethod
    async def get_stream(self, camera_id: str, protocol: str) -> Optional[StreamEndpoint]:
        """
        Resolves stream endpoint (HLS, WebRTC, RTSP) for a specific camera.
        """
        pass

    @abstractmethod
    async def get_health(self) -> SourceHealthResult:
        """
        Evaluates source-level health independently of individual camera streams.
        """
        pass

    def get_metadata(self) -> Dict[str, Any]:
        """
        Returns adapter metadata and capabilities.
        """
        return {
            "source_id": self.source_id,
            "source_name": self.source_name,
            "source_type": self.source_type,
            "endpoint_url": self.endpoint_url,
            "config": self.config
        }
