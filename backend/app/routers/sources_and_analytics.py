"""
Sentinel Phase 2 — Model 2: Unified Viewing + Selective Analytics Router
Endpoints for VMS Sources, Unified Stream Gateway, Selective Analytics & Vehicle Search.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from app.adapters.adapter_manager import SourceAdapterManager
from app.database.postgres import postgres
from app.models.model2_schemas import (
    CameraAnalyticsConfigResponse,
    CameraAnalyticsConfigUpdate,
    Model2KPIResponse,
    VehicleMovementSighting,
    VehicleSearchResponse,
    VMSSourceCreate,
    VMSSourceResponse,
    VMSSourceUpdate
)
from app.models.registry_schemas import UserContext, UserRole
from app.services.audit_service import AuditService
from app.services.rbac import check_department_permission, get_current_user, require_roles

logger = logging.getLogger("sentinel.v2.sources_analytics")

router = APIRouter(prefix="/api/v2", tags=["Model 2: Unified Viewing & Selective Analytics"])


# ==============================================================================
# 1. VMS SOURCE MANAGEMENT
# ==============================================================================

@router.get(
    "/sources",
    response_model=List[VMSSourceResponse],
    summary="List Independent VMS Sources",
    description="Retrieves all registered external CCTV/VMS source systems and their health."
)
async def list_sources(
    source_type: Optional[str] = Query(None, description="Filter by source type"),
    status: Optional[str] = Query(None, description="Filter by status (ACTIVE, NOT_CONFIGURED, etc.)"),
    user: UserContext = Depends(get_current_user)
):
    if not postgres.pool:
        raise HTTPException(status_code=503, detail="PostgreSQL database offline")

    conditions = []
    params = []

    if source_type:
        params.append(source_type.upper())
        conditions.append(f"s.source_type = ${len(params)}")

    if status:
        params.append(status.upper())
        conditions.append(f"s.status = ${len(params)}")

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

    sql = f"""
        SELECT 
            s.*,
            d.name AS owner_department_name,
            (SELECT COUNT(*) FROM public.cctv_assets a WHERE a.source_id = s.source_id) AS camera_count
        FROM public.vms_sources s
        LEFT JOIN public.departments d ON s.owner_department_id = d.id
        {where_clause}
        ORDER BY s.id ASC;
    """

    async with postgres.pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)

    return [VMSSourceResponse(**dict(r)) for r in rows]


@router.post(
    "/sources",
    response_model=VMSSourceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register Independent VMS Source",
    description="Onboards a new independent VMS or camera gateway system (SUPER_ADMIN only)."
)
async def create_source(
    payload: VMSSourceCreate,
    user: UserContext = Depends(require_roles([UserRole.SUPER_ADMIN]))
):
    if not postgres.pool:
        raise HTTPException(status_code=503, detail="PostgreSQL database offline")

    async with postgres.pool.acquire() as conn:
        existing = await conn.fetchval(
            "SELECT id FROM public.vms_sources WHERE source_id = $1;", payload.source_id
        )
        if existing:
            raise HTTPException(status_code=409, detail=f"Source ID '{payload.source_id}' already registered.")

        # Determine initial status: if mock/demo or unreachable, mark NOT_CONFIGURED
        is_demo_or_internal = any(k in payload.endpoint_url.lower() for k in ["internal", "example", "demo", "placeholder"])
        initial_status = "NOT_CONFIGURED" if is_demo_or_internal else "ACTIVE"
        initial_health = "UNKNOWN" if is_demo_or_internal else "HEALTHY"

        insert_sql = """
            INSERT INTO public.vms_sources (
                source_id, source_name, source_type, owner_department_id,
                connection_type, endpoint_url, credentials_ref, status,
                health_status, capabilities, config, created_by
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            RETURNING *, 0 AS camera_count;
        """
        row = await conn.fetchrow(
            insert_sql,
            payload.source_id, payload.source_name, payload.source_type.upper(),
            payload.owner_department_id, payload.connection_type.upper(),
            payload.endpoint_url, payload.credentials_ref,
            initial_status, initial_health,
            payload.capabilities, payload.config,
            user.username
        )

    # Reload adapters in manager
    await SourceAdapterManager.get_instance().reload_from_db()

    await AuditService.log_event(
        pool=postgres.pool,
        action="CREATE",
        entity_type="VMS_SOURCE",
        entity_id=payload.source_id,
        user=user,
        new_value=payload.model_dump(mode="json"),
        reason=f"Independent VMS source '{payload.source_name}' registered by {user.username}"
    )

    return VMSSourceResponse(**dict(row))


@router.get(
    "/sources/{source_id}",
    response_model=VMSSourceResponse,
    summary="Get VMS Source Details",
    description="Retrieves operational and configuration details for a source system."
)
async def get_source(source_id: str, user: UserContext = Depends(get_current_user)):
    if not postgres.pool:
        raise HTTPException(status_code=503, detail="PostgreSQL database offline")

    async with postgres.pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT 
                s.*,
                d.name AS owner_department_name,
                (SELECT COUNT(*) FROM public.cctv_assets a WHERE a.source_id = s.source_id) AS camera_count
            FROM public.vms_sources s
            LEFT JOIN public.departments d ON s.owner_department_id = d.id
            WHERE s.source_id = $1;
        """, source_id)

    if not row:
        raise HTTPException(status_code=404, detail=f"Source '{source_id}' not found.")

    return VMSSourceResponse(**dict(row))


@router.patch(
    "/sources/{source_id}",
    response_model=VMSSourceResponse,
    summary="Update VMS Source Configuration",
    description="Modifies source metadata or connection configuration without modifying the external VMS."
)
async def update_source(
    source_id: str,
    payload: VMSSourceUpdate,
    user: UserContext = Depends(require_roles([UserRole.SUPER_ADMIN]))
):
    if not postgres.pool:
        raise HTTPException(status_code=503, detail="PostgreSQL database offline")

    async with postgres.pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT * FROM public.vms_sources WHERE source_id = $1;", source_id)
        if not existing:
            raise HTTPException(status_code=404, detail=f"Source '{source_id}' not found.")

        update_dict = payload.model_dump(exclude_unset=True)
        if not update_dict:
            return VMSSourceResponse(**dict(existing), camera_count=0)

        update_dict["updated_at"] = datetime.now(timezone.utc)

        set_clauses = []
        values = []
        for idx, (col, val) in enumerate(update_dict.items(), start=1):
            set_clauses.append(f"{col} = ${idx}")
            values.append(val)
        values.append(source_id)

        updated_row = await conn.fetchrow(f"""
            UPDATE public.vms_sources 
            SET {', '.join(set_clauses)}
            WHERE source_id = ${len(values)}
            RETURNING *, (SELECT COUNT(*) FROM public.cctv_assets a WHERE a.source_id = $1) AS camera_count;
        """, *values)

    await SourceAdapterManager.get_instance().reload_from_db()

    await AuditService.log_event(
        pool=postgres.pool,
        action="UPDATE",
        entity_type="VMS_SOURCE",
        entity_id=source_id,
        user=user,
        old_value={k: existing[k] for k in update_dict.keys() if k in existing},
        new_value=update_dict,
        reason=f"VMS source {source_id} updated by {user.username}"
    )

    return VMSSourceResponse(**dict(updated_row))


@router.post(
    "/sources/{source_id}/probe",
    summary="Probe VMS Source Handshake",
    description="Executes a live probe against the external source adapter to verify connectivity and discovery."
)
async def probe_source(
    source_id: str,
    user: UserContext = Depends(require_roles([UserRole.SUPER_ADMIN, UserRole.DEPARTMENT_ADMIN, UserRole.OPERATOR]))
):
    manager = SourceAdapterManager.get_instance()
    await manager.reload_from_db()
    result = await manager.probe_source(source_id)

    if not result:
        raise HTTPException(status_code=404, detail=f"Adapter for source '{source_id}' not found.")

    # Update source health status in database
    if postgres.pool:
        async with postgres.pool.acquire() as conn:
            await conn.execute("""
                UPDATE public.vms_sources 
                SET status = $1, health_status = $2, last_health_check = NOW(), updated_at = NOW() 
                WHERE source_id = $3;
            """, result.status, result.health_status, source_id)

    return result.model_dump()


# ==============================================================================
# 2. UNIFIED MULTI-SOURCE CAMERA GATEWAY
# ==============================================================================

@router.get(
    "/cameras",
    summary="Multi-Source Unified Camera List",
    description="Retrieves cameras normalized across all connected source systems (Gujarat Gateway, ONVIF, RTSP, VMS)."
)
async def get_multi_source_cameras(
    source_id: Optional[str] = Query(None, description="Filter cameras by source system"),
    department_id: Optional[int] = Query(None, description="Filter by department"),
    status: Optional[str] = Query(None, description="Filter by operational status"),
    health_status: Optional[str] = Query(None, description="Filter by health status"),
    user: UserContext = Depends(get_current_user)
):
    if not postgres.pool:
        raise HTTPException(status_code=503, detail="PostgreSQL database offline")

    conditions = ["a.is_active = true"]
    params = []

    if source_id:
        params.append(source_id)
        conditions.append(f"a.source_id = ${len(params)}")

    if department_id:
        params.append(department_id)
        conditions.append(f"a.department_id = ${len(params)}")

    if status:
        params.append(status.upper())
        conditions.append(f"a.operational_status = ${len(params)}")

    if health_status:
        params.append(health_status.upper())
        conditions.append(f"a.health_status = ${len(params)}")

    where_clause = "WHERE " + " AND ".join(conditions)

    sql = f"""
        SELECT 
            a.camera_id,
            a.name,
            a.display_name,
            a.source_id,
            COALESCE(s.source_name, 'Gujarat Police Dynamic Camera Gateway') AS source_name,
            COALESCE(s.source_type, 'GATEWAY_CATALOGUE') AS source_type,
            a.department_id,
            d.name AS department_name,
            a.district,
            a.city,
            a.latitude,
            a.longitude,
            a.camera_type,
            a.codec,
            a.resolution,
            a.fps,
            a.operational_status,
            a.health_status,
            a.hls_available,
            a.webrtc_available,
            a.rtsp_available,
            c.profile_name AS analytics_profile,
            c.enabled_analytics,
            c.anpr_enabled
        FROM public.cctv_assets a
        LEFT JOIN public.vms_sources s ON a.source_id = s.source_id
        LEFT JOIN public.departments d ON a.department_id = d.id
        LEFT JOIN public.camera_analytics_config c ON a.camera_id = c.camera_id
        {where_clause}
        ORDER BY a.camera_id ASC;
    """

    async with postgres.pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)

    return [dict(r) for r in rows]


@router.get(
    "/cameras/{camera_id}/stream/{protocol}",
    summary="Unified Stream Gateway",
    description="Resolves authorized stream endpoints (HLS, WebRTC, RTSP) across any connected VMS source."
)
async def resolve_camera_stream(
    camera_id: str,
    protocol: str,
    user: UserContext = Depends(get_current_user)
):
    proto = protocol.upper()
    if proto not in ("HLS", "WEBRTC", "RTSP"):
        raise HTTPException(status_code=400, detail="Supported stream protocols: HLS, WEBRTC, RTSP.")

    manager = SourceAdapterManager.get_instance()
    endpoint = await manager.resolve_stream(camera_id, proto)

    if not endpoint:
        # Fallback to database URL lookup if adapter stream wasn't dynamic
        if postgres.pool:
            async with postgres.pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT camera_id, hls_available, webrtc_available, rtsp_available 
                    FROM public.cctv_assets WHERE camera_id = $1;
                """, camera_id)
                if not row:
                    raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found.")

        # Default proxy routes
        if proto == "HLS":
            return {"protocol": "HLS", "url": f"/api/cameras/{camera_id}/hls/index.m3u8", "is_available": True}
        elif proto == "WEBRTC":
            return {"protocol": "WEBRTC", "url": f"/stream/{camera_id}/whep", "is_available": True}
        else:
            return {"protocol": "RTSP", "url": f"rtsp://127.0.0.1:8554/stream/{camera_id}", "is_available": True}

    return endpoint.model_dump()


# ==============================================================================
# 3. SELECTIVE ANALYTICS CONFIGURATION
# ==============================================================================

AVAILABLE_ANALYTICS_CAPABILITIES = [
    {
        "id": "OBJECT_DETECTION",
        "name": "Vehicle & Person Detection",
        "model": "YOLOv8x-COCO",
        "description": "Real-time bounding box detection of cars, trucks, buses, motorcycles, bicycles, and persons."
    },
    {
        "id": "TRACKING",
        "name": "Multi-Object Trajectory Tracking",
        "model": "ByteTrack-Kalman",
        "description": "Associates detections across consecutive frames to maintain persistent track IDs and velocities."
    },
    {
        "id": "ANPR",
        "name": "Automatic Number Plate Recognition",
        "model": "Sentinel-OCR / PaddleOCR",
        "description": "Locates license plates, performs character recognition, and cross-references against eGujCop watchlist."
    },
    {
        "id": "VEHICLE_COUNTING",
        "name": "Traffic Density & Flow Counting",
        "model": "Virtual Tripwire / Line-Crossing",
        "description": "Tallies directional vehicle volume across designated virtual screen coordinates."
    },
    {
        "id": "REID",
        "name": "Cross-Camera Re-Identification",
        "model": "OSNet-IBN",
        "description": "Generates 512-dim visual embeddings to correlate targets across multiple camera feeds."
    }
]


@router.get(
    "/analytics/profiles",
    summary="List Analytics Profiles & Capabilities",
    description="Returns supported selective analytics engines and capability definitions."
)
async def list_analytics_profiles():
    return {
        "capabilities": AVAILABLE_ANALYTICS_CAPABILITIES,
        "predefined_profiles": [
            {
                "name": "STANDARD_SURVEILLANCE",
                "description": "Standard object detection and trajectory tracking at 5 FPS.",
                "enabled_analytics": ["OBJECT_DETECTION", "TRACKING"],
                "sampling_fps": 5.0,
                "confidence_threshold": 0.50
            },
            {
                "name": "HIGH_PRIORITY_ANPR",
                "description": "High-framerate ALPR and vehicle tracking on major junctions (10 FPS).",
                "enabled_analytics": ["OBJECT_DETECTION", "TRACKING", "ANPR"],
                "sampling_fps": 10.0,
                "confidence_threshold": 0.45
            },
            {
                "name": "PTZ_TRACKING",
                "description": "High-frequency tracking optimized for PTZ surveillance cameras.",
                "enabled_analytics": ["OBJECT_DETECTION", "TRACKING"],
                "sampling_fps": 15.0,
                "confidence_threshold": 0.55
            },
            {
                "name": "OFF",
                "description": "Disables video analytics pipeline on this camera to conserve edge GPU capacity.",
                "enabled_analytics": [],
                "sampling_fps": 0.0,
                "confidence_threshold": 0.0
            }
        ]
    }


@router.get(
    "/analytics/config",
    response_model=List[CameraAnalyticsConfigResponse],
    summary="List Selective Analytics Configurations",
    description="Retrieves analytics execution configurations for all cameras."
)
async def list_analytics_configs(
    anpr_only: bool = Query(False, description="Filter cameras with ANPR enabled"),
    user: UserContext = Depends(get_current_user)
):
    if not postgres.pool:
        raise HTTPException(status_code=503, detail="PostgreSQL database offline")

    where = "WHERE c.anpr_enabled = true" if anpr_only else ""

    sql = f"""
        SELECT 
            c.*,
            a.name AS camera_name,
            s.source_name
        FROM public.camera_analytics_config c
        LEFT JOIN public.cctv_assets a ON c.camera_id = a.camera_id
        LEFT JOIN public.vms_sources s ON c.source_id = s.source_id
        {where}
        ORDER BY c.camera_id ASC;
    """

    async with postgres.pool.acquire() as conn:
        rows = await conn.fetch(sql)

    return [CameraAnalyticsConfigResponse(**dict(r)) for r in rows]


@router.get(
    "/analytics/config/{camera_id}",
    response_model=CameraAnalyticsConfigResponse,
    summary="Get Camera Analytics Configuration",
    description="Retrieves selective analytics profile for a specific camera."
)
async def get_camera_analytics_config(
    camera_id: str,
    user: UserContext = Depends(get_current_user)
):
    if not postgres.pool:
        raise HTTPException(status_code=503, detail="PostgreSQL database offline")

    sql = """
        SELECT 
            c.*,
            a.name AS camera_name,
            s.source_name
        FROM public.camera_analytics_config c
        LEFT JOIN public.cctv_assets a ON c.camera_id = a.camera_id
        LEFT JOIN public.vms_sources s ON c.source_id = s.source_id
        WHERE c.camera_id = $1;
    """

    async with postgres.pool.acquire() as conn:
        row = await conn.fetchrow(sql, camera_id)

    if not row:
        raise HTTPException(status_code=404, detail=f"Analytics config for camera '{camera_id}' not found.")

    return CameraAnalyticsConfigResponse(**dict(row))


@router.put(
    "/analytics/config/{camera_id}",
    response_model=CameraAnalyticsConfigResponse,
    summary="Configure Selective Analytics Profile",
    description="Selectively activates or configures AI analytics models for a camera (SUPER_ADMIN, DEPT_ADMIN)."
)
async def update_camera_analytics_config(
    camera_id: str,
    payload: CameraAnalyticsConfigUpdate,
    user: UserContext = Depends(require_roles([UserRole.SUPER_ADMIN, UserRole.DEPARTMENT_ADMIN]))
):
    if not postgres.pool:
        raise HTTPException(status_code=503, detail="PostgreSQL database offline")

    async with postgres.pool.acquire() as conn:
        # Check camera existence
        cam = await conn.fetchrow("SELECT camera_id, department_id, source_id FROM public.cctv_assets WHERE camera_id = $1;", camera_id)
        if not cam:
            raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found in registry.")

        check_department_permission(user, cam["department_id"])

        existing = await conn.fetchrow("SELECT * FROM public.camera_analytics_config WHERE camera_id = $1;", camera_id)

        update_dict = payload.model_dump(exclude_unset=True)
        if not update_dict and existing:
            return CameraAnalyticsConfigResponse(**dict(existing))

        # Auto sync anpr_enabled flag based on enabled_analytics array
        if "enabled_analytics" in update_dict and update_dict["enabled_analytics"] is not None:
            update_dict["anpr_enabled"] = ("ANPR" in update_dict["enabled_analytics"])

        update_dict["updated_at"] = datetime.now(timezone.utc)
        update_dict["updated_by"] = user.username

        if existing:
            set_clauses = []
            values = []
            for idx, (col, val) in enumerate(update_dict.items(), start=1):
                set_clauses.append(f"{col} = ${idx}")
                values.append(val)
            values.append(camera_id)

            sql = f"""
                UPDATE public.camera_analytics_config
                SET {', '.join(set_clauses)}
                WHERE camera_id = ${len(values)}
                RETURNING *;
            """
            updated_row = await conn.fetchrow(sql, *values)
        else:
            # Create new row
            insert_sql = """
                INSERT INTO public.camera_analytics_config (
                    camera_id, source_id, profile_name, enabled_analytics,
                    confidence_threshold, sampling_fps, anpr_enabled,
                    is_active, updated_by
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                RETURNING *;
            """
            updated_row = await conn.fetchrow(
                insert_sql,
                camera_id,
                cam["source_id"] or "SRC_GUJ_GATEWAY",
                update_dict.get("profile_name", "CUSTOM"),
                update_dict.get("enabled_analytics", ["OBJECT_DETECTION", "TRACKING"]),
                update_dict.get("confidence_threshold", 0.50),
                update_dict.get("sampling_fps", 5.0),
                update_dict.get("anpr_enabled", False),
                update_dict.get("is_active", True),
                user.username
            )

    await AuditService.log_event(
        pool=postgres.pool,
        action="UPDATE",
        entity_type="ANALYTICS_CONFIG",
        entity_id=camera_id,
        camera_id=camera_id,
        user=user,
        new_value=update_dict,
        reason=f"Selective analytics configured for {camera_id} by {user.username} (Profile: {update_dict.get('profile_name')})"
    )

    return CameraAnalyticsConfigResponse(**dict(updated_row))


# ==============================================================================
# 4. SEARCHABLE VEHICLE MOVEMENT & REAL EVENT ARCHITECTURE
# ==============================================================================

@router.get(
    "/events/search",
    response_model=VehicleSearchResponse,
    summary="Search Vehicle Movement & Detections",
    description="Queries real historical vehicle detections, license plates, and trajectory tracks from database."
)
async def search_vehicle_movements(
    plate_number: Optional[str] = Query(None, description="Search license plate string (e.g. GJ01...)"),
    camera_id: Optional[str] = Query(None, description="Filter sightings by camera ID"),
    source_id: Optional[str] = Query(None, description="Filter sightings by source system"),
    vehicle_class: Optional[str] = Query(None, description="Filter by class: car, truck, bus, motorcycle"),
    track_id: Optional[int] = Query(None, description="Filter by tracking ID"),
    start_time: Optional[datetime] = Query(None, description="Earliest sighting timestamp"),
    end_time: Optional[datetime] = Query(None, description="Latest sighting timestamp"),
    min_confidence: float = Query(0.30, ge=0.1, le=1.0, description="Minimum detection confidence"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: UserContext = Depends(get_current_user)
):
    if not postgres.pool:
        raise HTTPException(status_code=503, detail="PostgreSQL database offline")

    conditions = ["e.confidence >= $1"]
    params: List[Any] = [min_confidence]

    if camera_id:
        params.append(camera_id.lower())
        conditions.append(f"LOWER(e.camera_id) = ${len(params)}")

    if plate_number:
        clean_plate = plate_number.strip().upper()
        params.append(clean_plate)
        # Search either top-level plate or inside detections array
        conditions.append(f"""(
            UPPER(COALESCE(e.metadata->'alpr'->>'plate', e.metadata->>'license_plate', e.metadata->>'plate')) LIKE '%' || ${len(params)} || '%'
            OR e.metadata->'detections' @> jsonb_build_array(jsonb_build_object('plate', ${len(params)}))
        )""")

    if vehicle_class:
        params.append(vehicle_class.strip().lower())
        conditions.append(f"""(
            LOWER(COALESCE(e.metadata->>'class_name', e.metadata->>'object_type')) = ${len(params)}
            OR e.metadata->'detections' @> jsonb_build_array(jsonb_build_object('class_name', ${len(params)}))
        )""")

    if track_id is not None:
        params.append(track_id)
        conditions.append(f"""(
            (e.metadata->'behavior'->>'track_id')::int = ${len(params)}
            OR e.metadata->'detections' @> jsonb_build_array(jsonb_build_object('track_id', ${len(params)}))
        )""")

    if start_time:
        params.append(start_time)
        conditions.append(f"e.event_timestamp >= ${len(params)}")

    if end_time:
        params.append(end_time)
        conditions.append(f"e.event_timestamp <= ${len(params)}")

    where_clause = "WHERE " + " AND ".join(conditions)

    sql = f"""
        SELECT 
            e.event_id::text,
            e.camera_id,
            COALESCE(a.name, c.name, 'Camera ' || e.camera_id) AS camera_name,
            COALESCE(a.source_id, 'SRC_GUJ_GATEWAY') AS source_id,
            COALESCE(s.source_name, 'Gujarat Police Dynamic Camera Gateway') AS source_name,
            COALESCE(a.city, c.city, 'Gujarat') AS city,
            a.district,
            COALESCE(e.latitude, a.latitude, c.latitude) AS latitude,
            COALESCE(e.longitude, a.longitude, c.longitude) AS longitude,
            e.event_timestamp AS timestamp,
            COALESCE(e.metadata->'alpr'->>'plate', e.metadata->>'license_plate', e.metadata->>'plate') AS plate_number,
            COALESCE(e.metadata->>'class_name', e.metadata->>'object_type', 'vehicle') AS vehicle_class,
            ROUND(e.confidence::numeric, 4)::float AS confidence,
            (COALESCE(e.metadata->'behavior'->>'track_id', e.metadata->>'track_id'))::int AS track_id,
            (e.metadata->'behavior'->>'speed_kmh')::float AS speed_kmh,
            (e.metadata->'behavior'->>'heading_deg')::float AS direction_degrees,
            COALESCE(e.metadata->'behavior'->>'risk_level', 'LOW') AS risk_level
        FROM public.events e
        LEFT JOIN public.cctv_assets a ON e.camera_id = a.camera_id
        LEFT JOIN public.cameras c ON e.camera_id = c.camera_id
        LEFT JOIN public.vms_sources s ON a.source_id = s.source_id
        {where_clause}
        ORDER BY e.event_timestamp DESC
        LIMIT ${len(params) + 1} OFFSET ${len(params) + 2};
    """
    params.extend([limit, offset])

    async with postgres.pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)

        # Count summary
        count_sql = f"""
            SELECT COUNT(*), COUNT(DISTINCT e.camera_id), MIN(e.event_timestamp), MAX(e.event_timestamp)
            FROM public.events e
            {where_clause};
        """
        cnt_row = await conn.fetchrow(count_sql, *params[:-2])

    total_sightings = cnt_row[0] or 0
    unique_cams = cnt_row[1] or 0
    first_seen = cnt_row[2]
    last_seen = cnt_row[3]

    sightings = []
    for r in rows:
        d = dict(r)
        # Parse Indian RTO jurisdiction if plate is found
        p = d.get("plate_number")
        if p and len(p) >= 4:
            d["rto_jurisdiction"] = f"RTO Zone {p[:4]}"
        sightings.append(VehicleMovementSighting(**d))

    return VehicleSearchResponse(
        query={
            "plate_number": plate_number,
            "camera_id": camera_id,
            "source_id": source_id,
            "vehicle_class": vehicle_class,
            "track_id": track_id
        },
        total_sightings=total_sightings,
        unique_cameras_count=unique_cams,
        sightings=sightings,
        first_seen=first_seen,
        last_seen=last_seen
    )


# ==============================================================================
# 5. MODEL 2 COMMAND CENTER KPIS
# ==============================================================================

@router.get(
    "/analytics/kpis",
    response_model=Model2KPIResponse,
    summary="Model 2 Unified Dashboard KPIs",
    description="Returns live database-derived metrics across all connected VMS sources and selective analytics."
)
async def get_model2_kpis(user: UserContext = Depends(get_current_user)):
    if not postgres.pool:
        raise HTTPException(status_code=503, detail="PostgreSQL database offline")

    async with postgres.pool.acquire() as conn:
        # Camera stats (single aggregated pass)
        cam_stats = await conn.fetchrow("""
            SELECT 
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE health_status = 'ONLINE') AS live,
                COUNT(*) FILTER (WHERE health_status = 'OFFLINE') AS offline,
                COUNT(*) FILTER (WHERE health_status = 'DEGRADED') AS degraded
            FROM public.cctv_assets;
        """)
        total_cams = cam_stats["total"] or 0
        live_cams = cam_stats["live"] or 0
        offline_cams = cam_stats["offline"] or 0
        degraded_cams = cam_stats["degraded"] or 0

        # Sources stats
        src_stats = await conn.fetchrow("""
            SELECT 
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE status = 'ACTIVE') AS active
            FROM public.vms_sources;
        """)
        total_sources = src_stats["total"] or 0
        active_sources = src_stats["active"] or 0

        # Analytics stats
        ana_stats = await conn.fetchrow("""
            SELECT 
                COUNT(*) FILTER (WHERE is_active = true) AS active,
                COUNT(*) FILTER (WHERE anpr_enabled = true) AS anpr
            FROM public.camera_analytics_config;
        """)
        active_analytics = ana_stats["active"] or 0
        anpr_cams = ana_stats["anpr"] or 0

        # Events stats
        recent_events = await conn.fetchval("SELECT COUNT(*) FROM public.events;") or 0
        anpr_events = await conn.fetchval("""
            SELECT COUNT(*) FROM public.events 
            WHERE event_type IN ('ANPR', 'ALPR_DETECTED');
        """) or 0

        # Sources breakdown
        s_rows = await conn.fetch("""
            SELECT 
                s.source_id,
                s.source_name,
                s.source_type,
                s.status,
                s.health_status,
                COUNT(a.id) AS camera_count
            FROM public.vms_sources s
            LEFT JOIN public.cctv_assets a ON s.source_id = a.source_id
            GROUP BY s.source_id, s.source_name, s.source_type, s.status, s.health_status
            ORDER BY s.source_id ASC;
        """)

    sources_summary = [dict(r) for r in s_rows]

    return Model2KPIResponse(
        total_cameras=total_cams,
        active_sources=active_sources,
        total_sources=total_sources,
        live_cameras=live_cams,
        offline_cameras=offline_cams,
        degraded_cameras=degraded_cams,
        active_analytics_cameras=active_analytics,
        anpr_enabled_cameras=anpr_cams,
        recent_events_count=recent_events,
        anpr_events_count=anpr_events,
        sources_summary=sources_summary
    )
