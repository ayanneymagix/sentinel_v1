from datetime import date, datetime
from typing import Any, List, Optional
from pydantic import BaseModel, Field, field_validator


class UserRole:
    SUPER_ADMIN = "SUPER_ADMIN"
    DEPARTMENT_ADMIN = "DEPARTMENT_ADMIN"
    OPERATOR = "OPERATOR"
    VIEWER = "VIEWER"
    AUDITOR = "AUDITOR"

    ALL = [SUPER_ADMIN, DEPARTMENT_ADMIN, OPERATOR, VIEWER, AUDITOR]


class UserContext(BaseModel):
    user_id: str = "USR_SYSTEM"
    username: str = "operator"
    role: str = UserRole.OPERATOR
    department_id: Optional[int] = None
    email: Optional[str] = None


# ------------------------------------------------------------------------------
# Departments
# ------------------------------------------------------------------------------

class DepartmentBase(BaseModel):
    department_id: str = Field(..., min_length=2, max_length=50)
    code: str = Field(..., min_length=2, max_length=30)
    name: str = Field(..., min_length=2, max_length=200)
    department_type: str = Field(..., description="STATE, ZONE, RANGE, DISTRICT, POLICE_STATION, OPERATIONAL_UNIT")
    parent_id: Optional[int] = None
    district: Optional[str] = None
    state: str = "Gujarat"
    is_active: bool = True


class DepartmentCreate(DepartmentBase):
    pass


class DepartmentUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    department_type: Optional[str] = None
    parent_id: Optional[int] = None
    district: Optional[str] = None
    is_active: Optional[bool] = None


class DepartmentResponse(DepartmentBase):
    id: int
    created_at: datetime
    updated_at: datetime
    camera_count: Optional[int] = 0

    model_config = {"from_attributes": True}


# ------------------------------------------------------------------------------
# CCTV Asset Registry
# ------------------------------------------------------------------------------

class CCTVAssetBase(BaseModel):
    camera_id: str = Field(..., min_length=2, max_length=100)
    source_camera_id: Optional[str] = None
    name: str = Field(..., min_length=2, max_length=250)
    display_name: Optional[str] = None
    description: Optional[str] = None

    # Ownership
    department_id: Optional[int] = None
    owning_department: Optional[str] = None
    operating_department: Optional[str] = None
    ownership_type: Optional[str] = "GOVERNMENT"

    # Classification
    camera_type: Optional[str] = "FIXED_BULLET"
    camera_category: Optional[str] = "TRAFFIC"
    form_factor: Optional[str] = "FIXED"
    environment: Optional[str] = "OUTDOOR"
    purpose: Optional[str] = "JUNCTION_MONITORING"

    # Location & GIS
    address: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    state: Optional[str] = "Gujarat"
    pincode: Optional[str] = None
    latitude: Optional[float] = Field(default=None, ge=-90.0, le=90.0)
    longitude: Optional[float] = Field(default=None, ge=-180.0, le=180.0)
    location_source: Optional[str] = "CATALOGUE"
    gis_verification_status: Optional[str] = "UNVERIFIED"

    # Infrastructure
    mounting_type: Optional[str] = "POLE"
    site_id: Optional[str] = None
    pole_id: Optional[str] = None
    power_source: Optional[str] = "GRID"
    network_provider: Optional[str] = None
    connectivity_type: Optional[str] = "OPTICAL_FIBER"
    bandwidth_mbps: Optional[float] = None

    # Technical
    manufacturer: Optional[str] = None
    model_number: Optional[str] = None
    serial_number: Optional[str] = None
    firmware_version: Optional[str] = None
    ip_address: Optional[str] = None
    mac_address: Optional[str] = None
    rtsp_port: Optional[int] = 8554
    codec: Optional[str] = "h264"
    resolution: Optional[str] = None
    fps: Optional[float] = None
    bitrate_kbps: Optional[int] = None
    stream_protocol: Optional[str] = "HLS"
    rtsp_available: bool = True
    hls_available: bool = True
    webrtc_available: bool = True

    # Lifecycle & Dates
    installation_date: Optional[date] = None
    commissioning_date: Optional[date] = None
    warranty_expiry_date: Optional[date] = None

    # Storage
    storage_type: Optional[str] = "CENTRAL_SAN"
    storage_location: Optional[str] = None
    retention_days: Optional[int] = 30
    storage_capacity_gb: Optional[float] = None
    recording_enabled: bool = True

    # Operational & Health
    operational_status: str = "ACTIVE"
    health_status: str = "UNKNOWN"
    last_seen: Optional[datetime] = None
    last_health_check: Optional[datetime] = None
    maintenance_status: str = "OPERATIONAL"

    # Administrative
    is_active: bool = True

    @field_validator("camera_id")
    def validate_camera_id(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("camera_id cannot be blank")
        return v

    @field_validator("latitude")
    def validate_latitude(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and (v < -90.0 or v > 90.0):
            raise ValueError("Latitude must be between -90 and +90 degrees")
        return v

    @field_validator("longitude")
    def validate_longitude(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and (v < -180.0 or v > 180.0):
            raise ValueError("Longitude must be between -180 and +180 degrees")
        return v


class CCTVAssetCreate(CCTVAssetBase):
    pass


class CCTVAssetUpdate(BaseModel):
    name: Optional[str] = None
    display_name: Optional[str] = None
    description: Optional[str] = None
    department_id: Optional[int] = None
    owning_department: Optional[str] = None
    operating_department: Optional[str] = None
    ownership_type: Optional[str] = None
    camera_type: Optional[str] = None
    camera_category: Optional[str] = None
    form_factor: Optional[str] = None
    environment: Optional[str] = None
    purpose: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None
    latitude: Optional[float] = Field(default=None, ge=-90.0, le=90.0)
    longitude: Optional[float] = Field(default=None, ge=-180.0, le=180.0)
    location_source: Optional[str] = None
    gis_verification_status: Optional[str] = None
    mounting_type: Optional[str] = None
    site_id: Optional[str] = None
    pole_id: Optional[str] = None
    power_source: Optional[str] = None
    network_provider: Optional[str] = None
    connectivity_type: Optional[str] = None
    bandwidth_mbps: Optional[float] = None
    manufacturer: Optional[str] = None
    model_number: Optional[str] = None
    serial_number: Optional[str] = None
    firmware_version: Optional[str] = None
    ip_address: Optional[str] = None
    mac_address: Optional[str] = None
    rtsp_port: Optional[int] = None
    codec: Optional[str] = None
    resolution: Optional[str] = None
    fps: Optional[float] = None
    bitrate_kbps: Optional[int] = None
    stream_protocol: Optional[str] = None
    rtsp_available: Optional[bool] = None
    hls_available: Optional[bool] = None
    webrtc_available: Optional[bool] = None
    installation_date: Optional[date] = None
    commissioning_date: Optional[date] = None
    warranty_expiry_date: Optional[date] = None
    storage_type: Optional[str] = None
    storage_location: Optional[str] = None
    retention_days: Optional[int] = None
    storage_capacity_gb: Optional[float] = None
    recording_enabled: Optional[bool] = None
    operational_status: Optional[str] = None
    health_status: Optional[str] = None
    maintenance_status: Optional[str] = None
    is_active: Optional[bool] = None


class CCTVAssetResponse(CCTVAssetBase):
    id: int
    geom: Optional[str] = None
    created_at: datetime
    created_by: Optional[str] = "SYSTEM"
    updated_at: datetime
    updated_by: Optional[str] = "SYSTEM"

    # Dynamic stream links populated from live catalogue
    live_stream_url: Optional[str] = None
    hls_stream_url: Optional[str] = None
    webrtc_stream_url: Optional[str] = None
    rtsp_stream_url: Optional[str] = None

    model_config = {"from_attributes": True}


class PaginatedCCTVAssetsResponse(BaseModel):
    items: List[CCTVAssetResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


# ------------------------------------------------------------------------------
# Maintenance Tickets
# ------------------------------------------------------------------------------

class MaintenanceTicketBase(BaseModel):
    camera_id: str
    issue_description: str = Field(..., min_length=5)
    maintenance_type: str = "CORRECTIVE" # PREVENTIVE, CORRECTIVE, ROUTINE_INSPECTION, HARDWARE_REPLACEMENT, FIRMWARE_UPGRADE, OPTICAL_CLEANING, CALIBRATION
    priority: str = "MEDIUM" # LOW, MEDIUM, HIGH, CRITICAL
    status: str = "OPEN" # OPEN, SCHEDULED, IN_PROGRESS, COMPLETED, CANCELLED
    scheduled_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    assigned_to: Optional[str] = None
    reported_by: Optional[str] = "OPERATOR"
    resolution: Optional[str] = None
    notes: Optional[str] = None
    cost_inr: Optional[float] = None


class MaintenanceTicketCreate(MaintenanceTicketBase):
    pass


class MaintenanceTicketUpdate(BaseModel):
    issue_description: Optional[str] = None
    maintenance_type: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    assigned_to: Optional[str] = None
    resolution: Optional[str] = None
    notes: Optional[str] = None
    cost_inr: Optional[float] = None


class MaintenanceTicketResponse(MaintenanceTicketBase):
    id: int
    ticket_number: str
    reported_at: datetime
    created_by: Optional[str] = "SYSTEM"
    updated_by: Optional[str] = "SYSTEM"
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ------------------------------------------------------------------------------
# Audit Log
# ------------------------------------------------------------------------------

class AuditLogResponse(BaseModel):
    id: int
    timestamp: datetime
    user_id: Optional[str] = None
    username: str
    role: str
    action: str
    entity_type: str
    entity_id: str
    camera_id: Optional[str] = None
    old_value: Optional[Any] = None
    new_value: Optional[Any] = None
    reason: Optional[str] = None
    ip_address: Optional[str] = None

    model_config = {"from_attributes": True}


# ------------------------------------------------------------------------------
# Bulk Import / Export & Validation
# ------------------------------------------------------------------------------

class RowValidationError(BaseModel):
    row_number: int
    camera_id: Optional[str] = None
    field: str
    error_message: str


class ImportPreviewResponse(BaseModel):
    total_rows: int
    valid_rows: int
    invalid_rows: int
    preview_items: List[dict[str, Any]]
    errors: List[RowValidationError]


class ImportSummaryResponse(BaseModel):
    total_rows: int
    valid_rows: int
    invalid_rows: int
    inserted: int
    updated: int
    skipped: int
    errors: List[RowValidationError]


# ------------------------------------------------------------------------------
# Analytics, KPIs, Coverage & Ageing
# ------------------------------------------------------------------------------

class RegistryKPIs(BaseModel):
    total_cameras: int
    online_count: int
    offline_count: int
    degraded_count: int
    maintenance_count: int
    unknown_count: int
    gis_mapped_count: int
    gis_unmapped_count: int
    missing_install_date_count: int
    ageing_count: int
    by_department: dict[str, int]
    by_district: dict[str, int]
    by_type: dict[str, int]
    by_ownership: dict[str, int]


class AgeingCameraItem(BaseModel):
    camera_id: str
    name: str
    district: Optional[str]
    installation_date: Optional[str]
    age_years: Optional[float]
    bracket: str # "0-3_YEARS", "3-5_YEARS", "5+_YEARS", "UNKNOWN"


class AgeingReportResponse(BaseModel):
    threshold_years_young: float = 3.0
    threshold_years_old: float = 5.0
    total_analyzed: int
    known_install_dates: int
    missing_install_dates: int
    count_young: int
    count_medium: int
    count_old: int
    count_unknown: int
    cameras: List[AgeingCameraItem]


class CoverageAnalysisResponse(BaseModel):
    total_cameras: int
    mapped_cameras_count: int
    unmapped_cameras_count: int
    coverage_model: str # "CONICAL_RADIUS_ESTIMATE"
    default_radius_meters: float
    coverage_analysis_available: bool
    reference_data_status: str # "AUTHORITATIVE_GIS_LAYERS_PENDING" or "ACTIVE"
    note: str
    active_cameras_with_coordinates: List[dict[str, Any]]


class GapAnalysisResponse(BaseModel):
    gap_analysis_available: bool
    reason: str
    reference_layers_required: List[str]
    reference_layers_configured: List[str]
    uncovered_priority_zones: List[dict[str, Any]]
    message: str
