from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class Detection(BaseModel):
    model_config = {"extra": "allow"}

    object_type: str
    class_name: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    bbox: list[float] | None = None
    norm_bbox: list[float] | None = None
    track_id: int | None = None
    plate: str | None = None
    alpr_details: dict[str, Any] | None = None
    risk_level: str | None = "LOW"
    risk_priority: str | None = "LOW"
    risk_color: str | None = "#10b981"
    risk_reason: str | None = None
    video_time_seconds: float | None = None
    velocity_px_s: float | None = None
    speed_kmh: float | None = None
    speed_status: str | None = None
    speed_display_reason: str | None = None
    calibration_id: str | None = None
    vx_px_s: float | None = None
    vy_px_s: float | None = None
    accel_px_s2: float | None = None
    vx: float | None = None
    vy: float | None = None
    speed: float | None = None
    heading_deg: float | None = None
    direction: str | None = None
    acceleration: float | None = None
    collision_detected: bool | None = False
    collision_partner_id: int | None = None
    collision_evidence: dict[str, Any] | None = None
    # Fine-grained Vehicle Attributes & Classification
    make: str | None = None
    model_subtype: str | None = None
    color: str | None = None
    full_name: str | None = None
    color_rgb: list[int] | None = None
    appearance_embedding: list[float] | None = None
    trajectory: list[list[float]] | None = None
    # Cross-Camera Multi-Target Multi-Camera Re-ID
    global_id: str | None = None
    journey_length: int | None = None
    is_reid_match: bool | None = None


class EventCreate(BaseModel):
    model_config = {"extra": "allow"}

    event_id: UUID

    node_id: str
    camera_id: str
    event_type: str

    timestamp: datetime

    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0
    )

    latitude: float | None = None
    longitude: float | None = None

    frame_number: int | None = None
    video_time_seconds: float | None = None
    risk_level: str | None = None
    risk_reason: str | None = None

    inference_latency_ms: float | None = None

    detections: list[Detection] = Field(
        default_factory=list
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict
    )


class EventResponse(BaseModel):
    status: str
    event_id: UUID
    message: str


class CameraCalibrationCreate(BaseModel):
    ground_plane_points: list[list[float]] = Field(..., description="4 image pixel points [[u, v], ...]")
    reference_distances: list[list[float]] | None = Field(default=None, description="4 real-world ground points in meters [[X, Y], ...]")
    real_width_meters: float | None = Field(default=None, description="Road segment width in meters")
    real_length_meters: float | None = Field(default=None, description="Road segment length in meters")
    calibrated_by: str = "OPERATOR"


class CameraCalibrationResponse(BaseModel):
    calibration_id: str
    camera_id: str
    ground_plane_points: list[list[float]]
    reference_distances: list[list[float]]
    real_width_meters: float | None = None
    real_length_meters: float | None = None
    homography_matrix: list[list[float]]
    calibrated_by: str
    calibrated_at: str | datetime
    is_active: bool
    status: str
    accuracy_validation_status: str = "PENDING_REFERENCE_GROUND_TRUTH"


class CalibrationValidationResult(BaseModel):
    valid: bool
    message: str
    homography_matrix: list[list[float]] | None = None
    min_span_meters: float | None = None
    max_span_meters: float | None = None
    polygon_area_px: float | None = None