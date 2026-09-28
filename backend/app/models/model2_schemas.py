"""
Sentinel Phase 2 — Model 2: Unified Viewing + Selective Analytics
Pydantic Schemas for VMS Sources, Analytics Configurations & Search
"""

import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class VMSSourceBase(BaseModel):
    source_name: str = Field(..., min_length=2, max_length=255)
    source_type: str = Field(..., description="GATEWAY_CATALOGUE, ONVIF, RTSP, VMS_API, VENDOR_SDK, WEBRTC, HLS")
    owner_department_id: Optional[int] = None
    connection_type: str = Field("HTTP_REST", description="HTTP_REST, RTSP_TCP, ONVIF_SOAP, WEBSOCKET, SDK")
    endpoint_url: str = Field(..., min_length=4)
    credentials_ref: Optional[str] = Field(None, description="Secret reference key (never raw secrets)")
    capabilities: Dict[str, Any] = Field(default_factory=lambda: {"hls": True, "webrtc": True, "rtsp": True, "ptz": False})
    config: Dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True

    @field_validator("capabilities", "config", mode="before")
    @classmethod
    def parse_source_json(cls, v: Any) -> Any:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return {}
        return v or {}


class VMSSourceCreate(VMSSourceBase):
    source_id: str = Field(..., min_length=3, max_length=64, pattern=r"^[A-Z0-9_\-]+$")


class VMSSourceUpdate(BaseModel):
    source_name: Optional[str] = None
    owner_department_id: Optional[int] = None
    connection_type: Optional[str] = None
    endpoint_url: Optional[str] = None
    credentials_ref: Optional[str] = None
    status: Optional[str] = None
    health_status: Optional[str] = None
    capabilities: Optional[Dict[str, Any]] = None
    config: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None

    @field_validator("capabilities", "config", mode="before")
    @classmethod
    def parse_update_json(cls, v: Any) -> Any:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return {}
        return v


class VMSSourceResponse(BaseModel):
    id: int
    source_id: str
    source_name: str
    source_type: str
    owner_department_id: Optional[int] = None
    owner_department_name: Optional[str] = None
    connection_type: str
    endpoint_url: str
    status: str
    health_status: str
    capabilities: Dict[str, Any] = Field(default_factory=dict)
    config: Dict[str, Any] = Field(default_factory=dict)
    camera_count: int = 0
    last_health_check: Optional[datetime] = None
    last_sync: Optional[datetime] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @field_validator("capabilities", "config", mode="before")
    @classmethod
    def parse_resp_json(cls, v: Any) -> Any:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return {}
        return v or {}


class CameraAnalyticsConfigResponse(BaseModel):
    id: int
    camera_id: str
    camera_name: Optional[str] = None
    source_id: Optional[str] = None
    source_name: Optional[str] = None
    profile_name: str
    enabled_analytics: List[str]
    confidence_threshold: float
    sampling_fps: float
    anpr_enabled: bool
    vehicle_counting_enabled: bool
    person_counting_enabled: bool
    behavior_analysis_enabled: bool
    reid_enabled: bool
    schedule: Dict[str, Any] = Field(default_factory=dict)
    is_active: bool
    updated_at: datetime
    updated_by: Optional[str] = None

    @field_validator("schedule", mode="before")
    @classmethod
    def parse_schedule_json(cls, v: Any) -> Any:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return {}
        return v or {}


class CameraAnalyticsConfigUpdate(BaseModel):
    profile_name: Optional[str] = None
    enabled_analytics: Optional[List[str]] = None
    confidence_threshold: Optional[float] = Field(None, ge=0.1, le=1.0)
    sampling_fps: Optional[float] = Field(None, ge=0.5, le=30.0)
    anpr_enabled: Optional[bool] = None
    vehicle_counting_enabled: Optional[bool] = None
    person_counting_enabled: Optional[bool] = None
    behavior_analysis_enabled: Optional[bool] = None
    reid_enabled: Optional[bool] = None
    schedule: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None


class VehicleMovementSighting(BaseModel):
    event_id: str
    camera_id: str
    camera_name: str
    source_id: Optional[str] = None
    source_name: Optional[str] = None
    city: str
    district: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    timestamp: datetime
    plate_number: Optional[str] = None
    vehicle_class: Optional[str] = None
    confidence: float
    track_id: Optional[int] = None
    speed_kmh: Optional[float] = None
    direction_degrees: Optional[float] = None
    risk_level: str = "LOW"
    rto_jurisdiction: Optional[str] = None


class VehicleSearchResponse(BaseModel):
    query: Dict[str, Any]
    total_sightings: int
    unique_cameras_count: int
    sightings: List[VehicleMovementSighting]
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None


class Model2KPIResponse(BaseModel):
    total_cameras: int
    active_sources: int
    total_sources: int
    live_cameras: int
    offline_cameras: int
    degraded_cameras: int
    active_analytics_cameras: int
    anpr_enabled_cameras: int
    recent_events_count: int
    anpr_events_count: int
    sources_summary: List[Dict[str, Any]]
