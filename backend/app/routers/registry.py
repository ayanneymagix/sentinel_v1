import io
import json
import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional
import asyncpg
from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status
)
from fastapi.responses import StreamingResponse

from app.database.postgres import postgres
from app.models.registry_schemas import (
    AgeingCameraItem,
    AgeingReportResponse,
    AuditLogResponse,
    CCTVAssetCreate,
    CCTVAssetResponse,
    CCTVAssetUpdate,
    CoverageAnalysisResponse,
    DepartmentCreate,
    DepartmentResponse,
    DepartmentUpdate,
    GapAnalysisResponse,
    ImportPreviewResponse,
    ImportSummaryResponse,
    MaintenanceTicketCreate,
    MaintenanceTicketResponse,
    MaintenanceTicketUpdate,
    PaginatedCCTVAssetsResponse,
    RegistryKPIs,
    UserContext,
    UserRole
)
from app.services.audit_service import AuditService
from app.services.catalogue_service import CameraCatalogueService
from app.services.import_export_service import ImportExportService
from app.services.rbac import (
    check_department_permission,
    get_current_user,
    require_roles
)

logger = logging.getLogger("sentinel.registry.api")

router = APIRouter(
    prefix="/api/registry",
    tags=["CCTV Asset Registry & GIS Management"]
)


def _row_to_asset_response(row: asyncpg.Record, stream_info: Optional[Dict[str, Any]] = None) -> CCTVAssetResponse:
    d = dict(row)
    cam_id = d["camera_id"]
    
    # Merge live stream information if available from live catalogue
    hls_url = None
    webrtc_url = None
    rtsp_url = None
    live_stream_url = None

    if stream_info:
        hls_url = stream_info.get("hls_url") or stream_info.get("stream_url")
        webrtc_url = stream_info.get("whep_url") or stream_info.get("webrtc_url")
        rtsp_url = stream_info.get("rtsp_url")
        live_stream_url = hls_url or webrtc_url
    else:
        # Default proxy endpoint if camera is known to support HLS
        hls_url = f"/api/cameras/{cam_id}/hls/index.m3u8"
        live_stream_url = hls_url

    d["hls_stream_url"] = hls_url
    d["webrtc_stream_url"] = webrtc_url
    d["rtsp_stream_url"] = rtsp_url
    d["live_stream_url"] = live_stream_url

    return CCTVAssetResponse(**d)


# ==============================================================================
# 1. CCTV ASSET CRUD & SEARCH / FILTERING
# ==============================================================================

@router.get(
    "/cameras",
    response_model=PaginatedCCTVAssetsResponse,
    summary="Search & Filter CCTV Assets",
    description="Returns paginated list of registered CCTV camera assets with real stream endpoints and metadata."
)
async def list_cameras(
    search: Optional[str] = Query(None, description="Search by camera ID, name, district, city"),
    department_id: Optional[int] = Query(None, description="Filter by department ID"),
    district: Optional[str] = Query(None, description="Filter by district"),
    city: Optional[str] = Query(None, description="Filter by city"),
    camera_type: Optional[str] = Query(None, description="Filter by camera type (e.g. FIXED_BULLET, PTZ, ANPR)"),
    camera_category: Optional[str] = Query(None, description="Filter by category (e.g. TRAFFIC, PUBLIC_SAFETY)"),
    ownership_type: Optional[str] = Query(None, description="Filter by ownership"),
    operational_status: Optional[str] = Query(None, description="Filter by operational status (ACTIVE, INACTIVE, etc.)"),
    health_status: Optional[str] = Query(None, description="Filter by health status (ONLINE, OFFLINE, DEGRADED, UNKNOWN)"),
    maintenance_status: Optional[str] = Query(None, description="Filter by maintenance status"),
    has_gis: Optional[bool] = Query(None, description="Filter by GIS coordinates availability (true=mapped, false=unmapped)"),
    is_active: Optional[bool] = Query(None, description="Filter by active state"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    sort_by: str = Query("camera_id", description="Sort field: camera_id, name, created_at, installation_date"),
    sort_order: str = Query("asc", regex="^(asc|desc)$", description="Sort order: asc or desc"),
    user: UserContext = Depends(get_current_user)
):
    if not postgres.pool:
        raise HTTPException(status_code=503, detail="PostgreSQL database offline")

    # Fetch live streams from catalogue service for real-time link enrichment
    catalogue_streams = {}
    try:
        cat_cams = await CameraCatalogueService.get_instance().get_cameras()
        for c in cat_cams:
            cid = c.get("camera_id") or c.get("id")
            if cid:
                catalogue_streams[cid] = c
    except Exception as e:
        logger.debug(f"Catalogue stream fetch non-critical warning: {e}")

    # Build dynamic SQL query
    conditions = ["1=1"]
    params = []
    p_idx = 1

    # Department RBAC filter: DEPARTMENT_ADMIN can only see assets belonging to their department
    if user.role == UserRole.DEPARTMENT_ADMIN and user.department_id is not None:
        conditions.append(f"department_id = ${p_idx}")
        params.append(user.department_id)
        p_idx += 1
    elif department_id is not None:
        conditions.append(f"department_id = ${p_idx}")
        params.append(department_id)
        p_idx += 1

    if search:
        s_term = f"%{search.strip()}%"
        conditions.append(f"(camera_id ILIKE ${p_idx} OR name ILIKE ${p_idx} OR display_name ILIKE ${p_idx} OR district ILIKE ${p_idx} OR city ILIKE ${p_idx})")
        params.append(s_term)
        p_idx += 1

    if district:
        conditions.append(f"district ILIKE ${p_idx}")
        params.append(district.strip())
        p_idx += 1

    if city:
        conditions.append(f"city ILIKE ${p_idx}")
        params.append(city.strip())
        p_idx += 1

    if camera_type:
        conditions.append(f"camera_type = ${p_idx}")
        params.append(camera_type.strip().upper())
        p_idx += 1

    if camera_category:
        conditions.append(f"camera_category = ${p_idx}")
        params.append(camera_category.strip().upper())
        p_idx += 1

    if ownership_type:
        conditions.append(f"ownership_type = ${p_idx}")
        params.append(ownership_type.strip().upper())
        p_idx += 1

    if operational_status:
        conditions.append(f"operational_status = ${p_idx}")
        params.append(operational_status.strip().upper())
        p_idx += 1

    if health_status:
        conditions.append(f"health_status = ${p_idx}")
        params.append(health_status.strip().upper())
        p_idx += 1

    if maintenance_status:
        conditions.append(f"maintenance_status = ${p_idx}")
        params.append(maintenance_status.strip().upper())
        p_idx += 1

    if has_gis is not None:
        if has_gis:
            conditions.append("latitude IS NOT NULL AND longitude IS NOT NULL")
        else:
            conditions.append("(latitude IS NULL OR longitude IS NULL)")

    if is_active is not None:
        conditions.append(f"is_active = ${p_idx}")
        params.append(is_active)
        p_idx += 1

    where_clause = " AND ".join(conditions)

    # Valid sorting columns
    allowed_sort_cols = {
        "camera_id": "camera_id",
        "name": "name",
        "created_at": "created_at",
        "installation_date": "installation_date",
        "district": "district",
        "operational_status": "operational_status",
        "health_status": "health_status"
    }
    sort_col = allowed_sort_cols.get(sort_by, "camera_id")
    order_direction = "DESC" if sort_order.lower() == "desc" else "ASC"

    count_sql = f"SELECT COUNT(*) FROM public.cctv_assets WHERE {where_clause};"
    offset = (page - 1) * page_size
    query_sql = f"""
        SELECT * FROM public.cctv_assets 
        WHERE {where_clause} 
        ORDER BY {sort_col} {order_direction}
        LIMIT ${p_idx} OFFSET ${p_idx + 1};
    """
    params.extend([page_size, offset])

    async with postgres.pool.acquire() as conn:
        total = await conn.fetchval(count_sql, *params[:-2])
        rows = await conn.fetch(query_sql, *params)

    items = [_row_to_asset_response(r, catalogue_streams.get(r["camera_id"])) for r in rows]
    total_pages = (total + page_size - 1) // page_size if total > 0 else 1

    return PaginatedCCTVAssetsResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


@router.post(
    "/cameras",
    response_model=CCTVAssetResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Manual Camera Onboarding",
    description="Onboards a single camera asset with validation, departmental checks, and audit logging."
)
async def create_camera(
    payload: CCTVAssetCreate,
    user: UserContext = Depends(require_roles([UserRole.SUPER_ADMIN, UserRole.DEPARTMENT_ADMIN]))
):
    if not postgres.pool:
        raise HTTPException(status_code=503, detail="PostgreSQL database offline")

    # Enforce department access for department admins
    check_department_permission(user, payload.department_id)

    # Validation: Coordinates range
    if payload.latitude is not None:
        if payload.latitude < -90.0 or payload.latitude > 90.0:
            raise HTTPException(status_code=400, detail="Latitude must be between -90 and +90 degrees.")
    if payload.longitude is not None:
        if payload.longitude < -180.0 or payload.longitude > 180.0:
            raise HTTPException(status_code=400, detail="Longitude must be between -180 and +180 degrees.")

    # Validation: Commissioning vs Installation date
    if payload.installation_date and payload.commissioning_date:
        if payload.commissioning_date < payload.installation_date:
            raise HTTPException(
                status_code=400,
                detail=f"Commissioning date ({payload.commissioning_date}) cannot be earlier than installation date ({payload.installation_date})."
            )

    async with postgres.pool.acquire() as conn:
        # Check duplicate camera_id
        existing = await conn.fetchval(
            "SELECT camera_id FROM public.cctv_assets WHERE camera_id = $1;", payload.camera_id
        )
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Camera with ID '{payload.camera_id}' already exists in registry."
            )

        # Validate department if provided
        if payload.department_id:
            dept_exists = await conn.fetchval("SELECT id FROM public.departments WHERE id = $1;", payload.department_id)
            if not dept_exists:
                raise HTTPException(status_code=400, detail=f"Department ID {payload.department_id} does not exist.")

        gis_status = "VERIFIED" if (payload.latitude is not None and payload.longitude is not None) else "COORDINATES_UNAVAILABLE"
        geom_val = (
            json.dumps({"type": "Point", "coordinates": [payload.longitude, payload.latitude]})
            if (payload.latitude is not None and payload.longitude is not None)
            else None
        )

        async with conn.transaction():
            insert_sql = """
                INSERT INTO public.cctv_assets (
                    camera_id, source_camera_id, name, display_name, description,
                    department_id, owning_department, operating_department, ownership_type,
                    camera_type, camera_category, form_factor, environment, purpose,
                    address, city, district, state, pincode,
                    latitude, longitude, geom, location_source, gis_verification_status,
                    mounting_type, site_id, pole_id, power_source, network_provider,
                    connectivity_type, bandwidth_mbps, manufacturer, model_number,
                    serial_number, firmware_version, ip_address, mac_address, rtsp_port,
                    codec, resolution, fps, bitrate_kbps, stream_protocol,
                    rtsp_available, hls_available, webrtc_available,
                    installation_date, commissioning_date, warranty_expiry_date,
                    storage_type, storage_location, retention_days, storage_capacity_gb,
                    recording_enabled, operational_status, health_status,
                    maintenance_status, is_active, created_by, updated_by
                ) VALUES (
                    $1, $2, $3, $4, $5,
                    $6, $7, $8, $9,
                    $10, $11, $12, $13, $14,
                    $15, $16, $17, $18, $19,
                    $20, $21, $22, 'MANUAL_ONBOARDING', $23,
                    $24, $25, $26, $27, $28,
                    $29, $30, $31, $32,
                    $33, $34, $35, $36, $37,
                    $38, $39, $40, $41, $42,
                    $43, $44, $45,
                    $46, $47, $48,
                    $49, $50, $51, $52,
                    $53, $54, $55,
                    $56, $57, $58, $58
                ) RETURNING *;
            """
            row = await conn.fetchrow(
                insert_sql,
                payload.camera_id, payload.source_camera_id or payload.camera_id, payload.name,
                payload.display_name or payload.name, payload.description,
                payload.department_id, payload.owning_department, payload.operating_department, payload.ownership_type,
                payload.camera_type, payload.camera_category, payload.form_factor, payload.environment, payload.purpose,
                payload.address, payload.city, payload.district or payload.city, payload.state, payload.pincode,
                payload.latitude, payload.longitude, geom_val, gis_status,
                payload.mounting_type, payload.site_id, payload.pole_id, payload.power_source, payload.network_provider,
                payload.connectivity_type, payload.bandwidth_mbps, payload.manufacturer, payload.model_number,
                payload.serial_number, payload.firmware_version, payload.ip_address, payload.mac_address, payload.rtsp_port,
                payload.codec, payload.resolution, payload.fps, payload.bitrate_kbps, payload.stream_protocol,
                payload.rtsp_available, payload.hls_available, payload.webrtc_available,
                payload.installation_date, payload.commissioning_date, payload.warranty_expiry_date,
                payload.storage_type, payload.storage_location, payload.retention_days, payload.storage_capacity_gb,
                payload.recording_enabled, payload.operational_status, payload.health_status,
                payload.maintenance_status, payload.is_active, user.username
            )

            # Keep public.cameras in sync so live grid and GIS map reflect the asset
            await conn.execute("""
                INSERT INTO public.cameras (
                    camera_id, node_id, name, city, source, latitude, longitude, geom, enabled, status
                ) VALUES ($1, 'NODE_GUJ_01', $2, $3, 'MANUAL_ONBOARDING', $4, $5, $6, $7, $8)
                ON CONFLICT (camera_id) DO UPDATE
                SET name = EXCLUDED.name,
                    city = COALESCE(EXCLUDED.city, public.cameras.city),
                    latitude = COALESCE(EXCLUDED.latitude, public.cameras.latitude),
                    longitude = COALESCE(EXCLUDED.longitude, public.cameras.longitude),
                    geom = COALESCE(EXCLUDED.geom, public.cameras.geom),
                    updated_at = NOW();
            """, payload.camera_id, payload.name, payload.city or payload.district,
                 payload.latitude, payload.longitude, geom_val, payload.is_active,
                 payload.health_status.lower() if payload.health_status else 'unknown')

        # Audit log creation
        await AuditService.log_event(
            pool=postgres.pool,
            action="CREATE",
            entity_type="CAMERA_ASSET",
            entity_id=payload.camera_id,
            camera_id=payload.camera_id,
            user=user,
            new_value=payload.model_dump(mode="json"),
            reason=f"Manual camera asset onboarding by {user.username} ({user.role})"
        )

        return _row_to_asset_response(row)


@router.get(
    "/cameras/{camera_id}",
    response_model=CCTVAssetResponse,
    summary="Get CCTV Camera Asset Details",
    description="Retrieves comprehensive details for a specific camera asset."
)
async def get_camera_detail(
    camera_id: str,
    user: UserContext = Depends(get_current_user)
):
    if not postgres.pool:
        raise HTTPException(status_code=503, detail="PostgreSQL database offline")

    async with postgres.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM public.cctv_assets WHERE camera_id = $1;", camera_id
        )

    if not row:
        raise HTTPException(status_code=404, detail=f"Camera asset '{camera_id}' not found in registry.")

    # Department RBAC check
    if user.role == UserRole.DEPARTMENT_ADMIN and user.department_id is not None:
        if row["department_id"] != user.department_id:
            raise HTTPException(status_code=403, detail="Access denied to this departmental camera asset.")

    # Live stream lookup
    stream_info = None
    try:
        cat_cams = await CameraCatalogueService.get_instance().get_cameras()
        stream_info = next((c for c in cat_cams if (c.get("camera_id") or c.get("id")) == camera_id), None)
    except Exception:
        pass

    return _row_to_asset_response(row, stream_info)


@router.patch(
    "/cameras/{camera_id}",
    response_model=CCTVAssetResponse,
    summary="Update CCTV Camera Asset",
    description="Updates metadata for a camera asset with validation and immutable audit trail."
)
async def update_camera(
    camera_id: str,
    payload: CCTVAssetUpdate,
    user: UserContext = Depends(require_roles([UserRole.SUPER_ADMIN, UserRole.DEPARTMENT_ADMIN]))
):
    if not postgres.pool:
        raise HTTPException(status_code=503, detail="PostgreSQL database offline")

    async with postgres.pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT * FROM public.cctv_assets WHERE camera_id = $1;", camera_id
        )
        if not existing:
            raise HTTPException(status_code=404, detail=f"Camera asset '{camera_id}' not found.")

        # RBAC departmental permission check
        check_department_permission(user, existing["department_id"])
        if payload.department_id is not None:
            check_department_permission(user, payload.department_id)

        update_dict = payload.model_dump(exclude_unset=True)
        if not update_dict:
            return _row_to_asset_response(existing)

        # Coordinate check
        new_lat = update_dict.get("latitude", existing["latitude"])
        new_lng = update_dict.get("longitude", existing["longitude"])

        if new_lat is not None and (new_lat < -90.0 or new_lat > 90.0):
            raise HTTPException(status_code=400, detail="Latitude must be between -90 and +90 degrees.")
        if new_lng is not None and (new_lng < -180.0 or new_lng > 180.0):
            raise HTTPException(status_code=400, detail="Longitude must be between -180 and +180 degrees.")

        # Date order check
        new_install = update_dict.get("installation_date", existing["installation_date"])
        new_comm = update_dict.get("commissioning_date", existing["commissioning_date"])
        if new_install and new_comm and new_comm < new_install:
            raise HTTPException(
                status_code=400,
                detail=f"Commissioning date ({new_comm}) cannot precede installation date ({new_install})."
            )

        if "latitude" in update_dict or "longitude" in update_dict:
            if new_lat is not None and new_lng is not None:
                update_dict["geom"] = json.dumps({"type": "Point", "coordinates": [new_lng, new_lat]})
                update_dict["gis_verification_status"] = "VERIFIED"
            else:
                update_dict["geom"] = None
                update_dict["gis_verification_status"] = "COORDINATES_UNAVAILABLE"

        update_dict["updated_by"] = user.username
        update_dict["updated_at"] = datetime.now()

        set_clauses = []
        values = []
        for idx, (col, val) in enumerate(update_dict.items(), start=1):
            set_clauses.append(f"{col} = ${idx}")
            values.append(val)
        values.append(camera_id)

        update_sql = f"""
            UPDATE public.cctv_assets 
            SET {', '.join(set_clauses)}
            WHERE camera_id = ${len(values)}
            RETURNING *;
        """

        async with conn.transaction():
            updated_row = await conn.fetchrow(update_sql, *values)

            # Sync name, city, and coordinates to public.cameras
            if any(k in update_dict for k in ("name", "city", "district", "latitude", "longitude", "is_active", "operational_status")):
                sync_name = update_dict.get("name", existing["name"])
                sync_city = update_dict.get("city", existing["city"]) or update_dict.get("district", existing["district"])
                sync_en = update_dict.get("is_active", existing["is_active"])
                await conn.execute("""
                    UPDATE public.cameras 
                    SET name = $1, city = $2, latitude = $3, longitude = $4, geom = $5, enabled = $6, updated_at = NOW()
                    WHERE camera_id = $7;
                """, sync_name, sync_city, new_lat, new_lng, update_dict.get("geom", existing["geom"]), sync_en, camera_id)

        # Audit log change
        old_val_serializable = {k: v for k, v in dict(existing).items() if k in update_dict}
        await AuditService.log_event(
            pool=postgres.pool,
            action="UPDATE",
            entity_type="CAMERA_ASSET",
            entity_id=camera_id,
            camera_id=camera_id,
            user=user,
            old_value=old_val_serializable,
            new_value=update_dict,
            reason=f"Camera asset {camera_id} updated by {user.username} ({user.role})"
        )

        return _row_to_asset_response(updated_row)


@router.put(
    "/cameras/{camera_id}",
    response_model=CCTVAssetResponse,
    summary="Replace CCTV Camera Asset",
    description="Full update of CCTV camera asset metadata."
)
async def replace_camera(
    camera_id: str,
    payload: CCTVAssetCreate,
    user: UserContext = Depends(require_roles([UserRole.SUPER_ADMIN, UserRole.DEPARTMENT_ADMIN]))
):
    # Pass through to patch logic with full payload
    update_data = CCTVAssetUpdate(**payload.model_dump())
    return await update_camera(camera_id, update_data, user)


@router.post(
    "/cameras/{camera_id}/activate",
    response_model=CCTVAssetResponse,
    summary="Activate Camera Asset",
    description="Sets camera operational status to ACTIVE and enables stream playback."
)
async def activate_camera(
    camera_id: str,
    user: UserContext = Depends(require_roles([UserRole.SUPER_ADMIN, UserRole.DEPARTMENT_ADMIN, UserRole.OPERATOR]))
):
    if not postgres.pool:
        raise HTTPException(status_code=503, detail="PostgreSQL database offline")

    async with postgres.pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT * FROM public.cctv_assets WHERE camera_id = $1;", camera_id)
        if not existing:
            raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found.")

        check_department_permission(user, existing["department_id"])

        async with conn.transaction():
            row = await conn.fetchrow("""
                UPDATE public.cctv_assets 
                SET operational_status = 'ACTIVE', is_active = true, updated_by = $1, updated_at = NOW()
                WHERE camera_id = $2
                RETURNING *;
            """, user.username, camera_id)

            await conn.execute("UPDATE public.cameras SET enabled = true, updated_at = NOW() WHERE camera_id = $1;", camera_id)

        await AuditService.log_event(
            pool=postgres.pool,
            action="STATUS_CHANGE",
            entity_type="CAMERA_ASSET",
            entity_id=camera_id,
            camera_id=camera_id,
            user=user,
            old_value={"operational_status": existing["operational_status"], "is_active": existing["is_active"]},
            new_value={"operational_status": "ACTIVE", "is_active": True},
            reason=f"Camera {camera_id} activated by {user.username} ({user.role})"
        )

        return _row_to_asset_response(row)


@router.post(
    "/cameras/{camera_id}/deactivate",
    response_model=CCTVAssetResponse,
    summary="Deactivate Camera Asset",
    description="Sets camera operational status to INACTIVE and disables live processing."
)
async def deactivate_camera(
    camera_id: str,
    user: UserContext = Depends(require_roles([UserRole.SUPER_ADMIN, UserRole.DEPARTMENT_ADMIN, UserRole.OPERATOR]))
):
    if not postgres.pool:
        raise HTTPException(status_code=503, detail="PostgreSQL database offline")

    async with postgres.pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT * FROM public.cctv_assets WHERE camera_id = $1;", camera_id)
        if not existing:
            raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found.")

        check_department_permission(user, existing["department_id"])

        async with conn.transaction():
            row = await conn.fetchrow("""
                UPDATE public.cctv_assets 
                SET operational_status = 'INACTIVE', is_active = false, updated_by = $1, updated_at = NOW()
                WHERE camera_id = $2
                RETURNING *;
            """, user.username, camera_id)

            await conn.execute("UPDATE public.cameras SET enabled = false, updated_at = NOW() WHERE camera_id = $1;", camera_id)

        await AuditService.log_event(
            pool=postgres.pool,
            action="STATUS_CHANGE",
            entity_type="CAMERA_ASSET",
            entity_id=camera_id,
            camera_id=camera_id,
            user=user,
            old_value={"operational_status": existing["operational_status"], "is_active": existing["is_active"]},
            new_value={"operational_status": "INACTIVE", "is_active": False},
            reason=f"Camera {camera_id} deactivated by {user.username} ({user.role})"
        )

        return _row_to_asset_response(row)


# ==============================================================================
# 2. BULK IMPORT & VALIDATION ENGINE
# ==============================================================================

@router.post(
    "/import/csv",
    summary="Bulk Import CCTV Assets from CSV",
    description="Validates and imports camera assets from CSV. Set commit=false to preview with row-level validation errors, commit=true to insert valid rows."
)
async def import_csv(
    file: UploadFile = File(...),
    commit: bool = Query(False, description="Preview (false) or Execute Import (true)"),
    user: UserContext = Depends(require_roles([UserRole.SUPER_ADMIN, UserRole.DEPARTMENT_ADMIN]))
):
    if not postgres.pool:
        raise HTTPException(status_code=503, detail="PostgreSQL database offline")

    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Invalid file format. Please upload a .csv file.")

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large. Maximum CSV size is 10MB.")

    result = await ImportExportService.process_import(
        file_bytes=content,
        filename=file.filename,
        commit=commit,
        pool=postgres.pool,
        user=user
    )
    return result


@router.post(
    "/import/excel",
    summary="Bulk Import CCTV Assets from Excel (.xlsx)",
    description="Validates and imports camera assets from Excel. Set commit=false to preview with row-level validation errors, commit=true to insert valid rows."
)
async def import_excel(
    file: UploadFile = File(...),
    commit: bool = Query(False, description="Preview (false) or Execute Import (true)"),
    user: UserContext = Depends(require_roles([UserRole.SUPER_ADMIN, UserRole.DEPARTMENT_ADMIN]))
):
    if not postgres.pool:
        raise HTTPException(status_code=503, detail="PostgreSQL database offline")

    if not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Invalid file format. Please upload an Excel (.xlsx) file.")

    content = await file.read()
    if len(content) > 15 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large. Maximum Excel size is 15MB.")

    result = await ImportExportService.process_import(
        file_bytes=content,
        filename=file.filename,
        commit=commit,
        pool=postgres.pool,
        user=user
    )
    return result


# ==============================================================================
# 3. REGISTRY EXPORT (CSV, Excel, GeoJSON)
# ==============================================================================

@router.get(
    "/export",
    summary="Export CCTV Asset Registry",
    description="Exports database records in CSV, Excel (.xlsx), or GeoJSON format, respecting filters and RBAC."
)
async def export_registry(
    format: str = Query("csv", regex="^(csv|excel|geojson)$", description="Export format: csv, excel, geojson"),
    district: Optional[str] = Query(None),
    department_id: Optional[int] = Query(None),
    camera_type: Optional[str] = Query(None),
    operational_status: Optional[str] = Query(None),
    health_status: Optional[str] = Query(None),
    user: UserContext = Depends(require_roles([UserRole.SUPER_ADMIN, UserRole.DEPARTMENT_ADMIN, UserRole.AUDITOR, UserRole.OPERATOR]))
):
    if not postgres.pool:
        raise HTTPException(status_code=503, detail="PostgreSQL database offline")

    conditions = ["1=1"]
    params = []
    p_idx = 1

    if user.role == UserRole.DEPARTMENT_ADMIN and user.department_id is not None:
        conditions.append(f"c.department_id = ${p_idx}")
        params.append(user.department_id)
        p_idx += 1
    elif department_id is not None:
        conditions.append(f"c.department_id = ${p_idx}")
        params.append(department_id)
        p_idx += 1

    if district:
        conditions.append(f"c.district ILIKE ${p_idx}")
        params.append(district.strip())
        p_idx += 1

    if camera_type:
        conditions.append(f"c.camera_type = ${p_idx}")
        params.append(camera_type.strip().upper())
        p_idx += 1

    if operational_status:
        conditions.append(f"c.operational_status = ${p_idx}")
        params.append(operational_status.strip().upper())
        p_idx += 1

    if health_status:
        conditions.append(f"c.health_status = ${p_idx}")
        params.append(health_status.strip().upper())
        p_idx += 1

    sql = f"""
        SELECT c.*, d.name AS department_name
        FROM public.cctv_assets c
        LEFT JOIN public.departments d ON c.department_id = d.id
        WHERE {' AND '.join(conditions)}
        ORDER BY c.camera_id ASC;
    """

    async with postgres.pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)

    records = [dict(r) for r in rows]

    file_bytes, media_type, filename = await ImportExportService.export_registry(
        format_type=format,
        records=records,
        user=user,
        pool=postgres.pool
    )

    return StreamingResponse(
        io.BytesIO(file_bytes),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


# ==============================================================================
# 4. DEPARTMENT HIERARCHY
# ==============================================================================

@router.get(
    "/departments",
    response_model=List[DepartmentResponse],
    summary="Get Department Hierarchy",
    description="Returns the database-backed department hierarchy with camera counts."
)
async def list_departments(user: UserContext = Depends(get_current_user)):
    if not postgres.pool:
        raise HTTPException(status_code=503, detail="PostgreSQL database offline")

    sql = """
        SELECT d.*, COUNT(c.id) AS camera_count
        FROM public.departments d
        LEFT JOIN public.cctv_assets c ON d.id = c.department_id
        GROUP BY d.id
        ORDER BY d.id ASC;
    """

    async with postgres.pool.acquire() as conn:
        rows = await conn.fetch(sql)

    return [DepartmentResponse(**dict(r)) for r in rows]


@router.post(
    "/departments",
    response_model=DepartmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Department",
    description="Adds an administrative police department to the hierarchy."
)
async def create_department(
    payload: DepartmentCreate,
    user: UserContext = Depends(require_roles([UserRole.SUPER_ADMIN]))
):
    if not postgres.pool:
        raise HTTPException(status_code=503, detail="PostgreSQL database offline")

    async with postgres.pool.acquire() as conn:
        existing = await conn.fetchval(
            "SELECT id FROM public.departments WHERE department_id = $1 OR code = $2;",
            payload.department_id, payload.code
        )
        if existing:
            raise HTTPException(status_code=409, detail=f"Department ID '{payload.department_id}' or Code '{payload.code}' already exists.")

        insert_sql = """
            INSERT INTO public.departments (
                department_id, code, name, department_type, parent_id, district, state, is_active
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING *, 0 AS camera_count;
        """
        row = await conn.fetchrow(
            insert_sql,
            payload.department_id, payload.code, payload.name, payload.department_type,
            payload.parent_id, payload.district, payload.state, payload.is_active
        )

        await AuditService.log_event(
            pool=postgres.pool,
            action="CREATE",
            entity_type="DEPARTMENT",
            entity_id=payload.department_id,
            user=user,
            new_value=payload.model_dump(mode="json"),
            reason=f"Department {payload.name} created by {user.username} ({user.role})"
        )

        return DepartmentResponse(**dict(row))


# ==============================================================================
# 5. MAINTENANCE TICKETS
# ==============================================================================

@router.get(
    "/maintenance",
    response_model=List[MaintenanceTicketResponse],
    summary="List Maintenance Tickets",
    description="Returns camera maintenance records with status and history."
)
async def list_maintenance_tickets(
    camera_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    maintenance_type: Optional[str] = Query(None),
    user: UserContext = Depends(get_current_user)
):
    if not postgres.pool:
        raise HTTPException(status_code=503, detail="PostgreSQL database offline")

    conditions = ["1=1"]
    params = []
    p_idx = 1

    if camera_id:
        conditions.append(f"camera_id = ${p_idx}")
        params.append(camera_id.strip())
        p_idx += 1

    if status:
        conditions.append(f"status = ${p_idx}")
        params.append(status.strip().upper())
        p_idx += 1

    if priority:
        conditions.append(f"priority = ${p_idx}")
        params.append(priority.strip().upper())
        p_idx += 1

    if maintenance_type:
        conditions.append(f"maintenance_type = ${p_idx}")
        params.append(maintenance_type.strip().upper())
        p_idx += 1

    sql = f"""
        SELECT * FROM public.cctv_maintenance
        WHERE {' AND '.join(conditions)}
        ORDER BY reported_at DESC
        LIMIT 200;
    """

    async with postgres.pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)

    return [MaintenanceTicketResponse(**dict(r)) for r in rows]


@router.post(
    "/maintenance",
    response_model=MaintenanceTicketResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Maintenance Ticket",
    description="Reports an issue or schedules maintenance for a camera."
)
async def create_maintenance_ticket(
    payload: MaintenanceTicketCreate,
    user: UserContext = Depends(require_roles([UserRole.SUPER_ADMIN, UserRole.DEPARTMENT_ADMIN, UserRole.OPERATOR]))
):
    if not postgres.pool:
        raise HTTPException(status_code=503, detail="PostgreSQL database offline")

    async with postgres.pool.acquire() as conn:
        # Check camera existence
        cam_exists = await conn.fetchrow(
            "SELECT camera_id, department_id, maintenance_status FROM public.cctv_assets WHERE camera_id = $1;",
            payload.camera_id
        )
        if not cam_exists:
            raise HTTPException(status_code=404, detail=f"Camera '{payload.camera_id}' not found.")

        check_department_permission(user, cam_exists["department_id"])

        # Generate ticket number MNT-YYYYMMDD-XXXX
        today_prefix = datetime.now().strftime("MNT-%Y%m%d-")
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM public.cctv_maintenance WHERE ticket_number LIKE $1;",
            f"{today_prefix}%"
        )
        ticket_number = f"{today_prefix}{count + 1:04d}"

        insert_sql = """
            INSERT INTO public.cctv_maintenance (
                ticket_number, camera_id, issue_description, maintenance_type,
                priority, status, scheduled_at, assigned_to, reported_by,
                resolution, notes, cost_inr, created_by, updated_by
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $13)
            RETURNING *;
        """

        async with conn.transaction():
            row = await conn.fetchrow(
                insert_sql,
                ticket_number, payload.camera_id, payload.issue_description, payload.maintenance_type,
                payload.priority, payload.status, payload.scheduled_at, payload.assigned_to,
                user.username, payload.resolution, payload.notes, payload.cost_inr, user.username
            )

            # Update camera maintenance status
            new_cam_status = "UNDER_MAINTENANCE" if payload.status in ("SCHEDULED", "IN_PROGRESS") else "MAINTENANCE_REQUIRED"
            await conn.execute(
                "UPDATE public.cctv_assets SET maintenance_status = $1, updated_at = NOW() WHERE camera_id = $2;",
                new_cam_status, payload.camera_id
            )

        await AuditService.log_event(
            pool=postgres.pool,
            action="MAINTENANCE_CHANGE",
            entity_type="MAINTENANCE_TICKET",
            entity_id=ticket_number,
            camera_id=payload.camera_id,
            user=user,
            new_value=payload.model_dump(mode="json"),
            reason=f"Maintenance ticket {ticket_number} created for camera {payload.camera_id} by {user.username}"
        )

        return MaintenanceTicketResponse(**dict(row))


@router.patch(
    "/maintenance/{ticket_number}",
    response_model=MaintenanceTicketResponse,
    summary="Update Maintenance Ticket",
    description="Updates ticket status, resolution, and completion details."
)
async def update_maintenance_ticket(
    ticket_number: str,
    payload: MaintenanceTicketUpdate,
    user: UserContext = Depends(require_roles([UserRole.SUPER_ADMIN, UserRole.DEPARTMENT_ADMIN, UserRole.OPERATOR]))
):
    if not postgres.pool:
        raise HTTPException(status_code=503, detail="PostgreSQL database offline")

    async with postgres.pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT * FROM public.cctv_maintenance WHERE ticket_number = $1;", ticket_number
        )
        if not existing:
            raise HTTPException(status_code=404, detail=f"Ticket '{ticket_number}' not found.")

        update_dict = payload.model_dump(exclude_unset=True)
        if not update_dict:
            return MaintenanceTicketResponse(**dict(existing))

        # Auto set completed_at if status becomes COMPLETED
        if update_dict.get("status") == "COMPLETED" and not update_dict.get("completed_at"):
            update_dict["completed_at"] = datetime.now()

        update_dict["updated_by"] = user.username
        update_dict["updated_at"] = datetime.now()

        set_clauses = []
        values = []
        for idx, (col, val) in enumerate(update_dict.items(), start=1):
            set_clauses.append(f"{col} = ${idx}")
            values.append(val)
        values.append(ticket_number)

        async with conn.transaction():
            updated_row = await conn.fetchrow(f"""
                UPDATE public.cctv_maintenance 
                SET {', '.join(set_clauses)}
                WHERE ticket_number = ${len(values)}
                RETURNING *;
            """, *values)

            # If ticket completed or cancelled, check if any open tickets remain for this camera
            if update_dict.get("status") in ("COMPLETED", "CANCELLED"):
                open_count = await conn.fetchval("""
                    SELECT COUNT(*) FROM public.cctv_maintenance 
                    WHERE camera_id = $1 AND status IN ('OPEN', 'SCHEDULED', 'IN_PROGRESS');
                """, existing["camera_id"])
                if open_count == 0:
                    await conn.execute("""
                        UPDATE public.cctv_assets 
                        SET maintenance_status = 'OPERATIONAL', updated_at = NOW() 
                        WHERE camera_id = $1;
                    """, existing["camera_id"])

        await AuditService.log_event(
            pool=postgres.pool,
            action="MAINTENANCE_CHANGE",
            entity_type="MAINTENANCE_TICKET",
            entity_id=ticket_number,
            camera_id=existing["camera_id"],
            user=user,
            old_value=dict(existing),
            new_value=update_dict,
            reason=f"Ticket {ticket_number} updated: status -> {update_dict.get('status')}"
        )

        return MaintenanceTicketResponse(**dict(updated_row))


# ==============================================================================
# 6. IMMUTABLE AUDIT LOG
# ==============================================================================

@router.get(
    "/audit-log",
    response_model=List[AuditLogResponse],
    summary="Query Immutable Audit Trail",
    description="Returns auditable log records for security, compliance, and governance."
)
async def get_audit_log(
    camera_id: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    user: UserContext = Depends(require_roles([UserRole.SUPER_ADMIN, UserRole.AUDITOR]))
):
    if not postgres.pool:
        raise HTTPException(status_code=503, detail="PostgreSQL database offline")

    conditions = ["1=1"]
    params = []
    p_idx = 1

    if camera_id:
        conditions.append(f"camera_id = ${p_idx}")
        params.append(camera_id.strip())
        p_idx += 1

    if action:
        conditions.append(f"action = ${p_idx}")
        params.append(action.strip().upper())
        p_idx += 1

    if user_id:
        conditions.append(f"user_id = ${p_idx}")
        params.append(user_id.strip())
        p_idx += 1

    sql = f"""
        SELECT * FROM public.cctv_audit_log
        WHERE {' AND '.join(conditions)}
        ORDER BY timestamp DESC
        LIMIT ${p_idx};
    """
    params.append(limit)

    async with postgres.pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)

    return [AuditLogResponse(**dict(r)) for r in rows]


# ==============================================================================
# 7. ANALYTICS, KPIS, AGEING & COVERAGE (100% Database-Derived)
# ==============================================================================

@router.get(
    "/analytics/kpis",
    response_model=RegistryKPIs,
    summary="Database-Derived Registry KPIs",
    description="Calculates live KPI metrics exclusively from real database records with zero hardcoded or fake numbers."
)
async def get_registry_kpis(user: UserContext = Depends(get_current_user)):
    if not postgres.pool:
        raise HTTPException(status_code=503, detail="PostgreSQL database offline")

    dept_filter = ""
    dept_params = []
    if user.role == UserRole.DEPARTMENT_ADMIN and user.department_id is not None:
        dept_filter = "WHERE department_id = $1"
        dept_params = [user.department_id]

    async with postgres.pool.acquire() as conn:
        total = await conn.fetchval(f"SELECT COUNT(*) FROM public.cctv_assets {dept_filter};", *dept_params) or 0
        
        # Operational / Health counts
        health_rows = await conn.fetch(f"""
            SELECT UPPER(health_status) as h, COUNT(*) as cnt 
            FROM public.cctv_assets {dept_filter} 
            GROUP BY UPPER(health_status);
        """, *dept_params)
        health_map = {r["h"]: r["cnt"] for r in health_rows}

        maint_cnt = await conn.fetchval(f"""
            SELECT COUNT(*) FROM public.cctv_assets 
            {dept_filter} {'AND' if dept_filter else 'WHERE'} maintenance_status != 'OPERATIONAL';
        """, *dept_params) or 0

        # GIS Mapped vs Unmapped
        mapped_cnt = await conn.fetchval(f"""
            SELECT COUNT(*) FROM public.cctv_assets 
            {dept_filter} {'AND' if dept_filter else 'WHERE'} latitude IS NOT NULL AND longitude IS NOT NULL;
        """, *dept_params) or 0

        unmapped_cnt = total - mapped_cnt

        # Installation date coverage
        missing_install_cnt = await conn.fetchval(f"""
            SELECT COUNT(*) FROM public.cctv_assets 
            {dept_filter} {'AND' if dept_filter else 'WHERE'} installation_date IS NULL;
        """, *dept_params) or 0

        ageing_cnt = await conn.fetchval(f"""
            SELECT COUNT(*) FROM public.cctv_assets 
            {dept_filter} {'AND' if dept_filter else 'WHERE'} installation_date IS NOT NULL 
            AND (CURRENT_DATE - installation_date) > (5 * 365.25);
        """, *dept_params) or 0

        # Group by department
        dept_rows = await conn.fetch(f"""
            SELECT COALESCE(d.name, 'Unassigned / Discovered') as dname, COUNT(c.id) as cnt
            FROM public.cctv_assets c
            LEFT JOIN public.departments d ON c.department_id = d.id
            {dept_filter.replace('department_id', 'c.department_id')}
            GROUP BY d.name
            ORDER BY cnt DESC;
        """, *dept_params)
        by_dept = {r["dname"]: r["cnt"] for r in dept_rows}

        # Group by district
        dist_rows = await conn.fetch(f"""
            SELECT COALESCE(district, 'Unknown District') as dname, COUNT(*) as cnt
            FROM public.cctv_assets {dept_filter}
            GROUP BY district
            ORDER BY cnt DESC;
        """, *dept_params)
        by_dist = {r["dname"]: r["cnt"] for r in dist_rows}

        # Group by camera type
        type_rows = await conn.fetch(f"""
            SELECT COALESCE(camera_type, 'UNKNOWN') as tname, COUNT(*) as cnt
            FROM public.cctv_assets {dept_filter}
            GROUP BY camera_type
            ORDER BY cnt DESC;
        """, *dept_params)
        by_type = {r["tname"]: r["cnt"] for r in type_rows}

        # Group by ownership
        own_rows = await conn.fetch(f"""
            SELECT COALESCE(ownership_type, 'UNKNOWN') as oname, COUNT(*) as cnt
            FROM public.cctv_assets {dept_filter}
            GROUP BY ownership_type
            ORDER BY cnt DESC;
        """, *dept_params)
        by_own = {r["oname"]: r["cnt"] for r in own_rows}

    return RegistryKPIs(
        total_cameras=total,
        online_count=health_map.get("ONLINE", 0),
        offline_count=health_map.get("OFFLINE", 0),
        degraded_count=health_map.get("DEGRADED", 0),
        maintenance_count=maint_cnt,
        unknown_count=health_map.get("UNKNOWN", 0),
        gis_mapped_count=mapped_cnt,
        gis_unmapped_count=unmapped_cnt,
        missing_install_date_count=missing_install_cnt,
        ageing_count=ageing_cnt,
        by_department=by_dept,
        by_district=by_dist,
        by_type=by_type,
        by_ownership=by_own
    )


@router.get(
    "/analytics/ageing",
    response_model=AgeingReportResponse,
    summary="Ageing Infrastructure Report",
    description="Calculates asset ageing exclusively based on real recorded installation dates with configurable thresholds."
)
async def get_ageing_report(
    young_years: float = Query(3.0, ge=0.5, description="Upper threshold for Young assets"),
    old_years: float = Query(5.0, ge=1.0, description="Lower threshold for Old/Ageing assets"),
    user: UserContext = Depends(get_current_user)
):
    if not postgres.pool:
        raise HTTPException(status_code=503, detail="PostgreSQL database offline")

    if young_years >= old_years:
        raise HTTPException(status_code=400, detail="young_years threshold must be strictly less than old_years threshold.")

    async with postgres.pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT camera_id, name, district, installation_date
            FROM public.cctv_assets
            ORDER BY installation_date ASC NULLS LAST, camera_id ASC;
        """)

    items: List[AgeingCameraItem] = []
    count_young = 0
    count_medium = 0
    count_old = 0
    count_unknown = 0
    known_dates = 0

    today = date.today()

    for r in rows:
        cid = r["camera_id"]
        cname = r["name"]
        dist = r["district"]
        inst_date = r["installation_date"]

        if inst_date:
            known_dates += 1
            age = (today - inst_date).days / 365.25
            if age < young_years:
                bracket = f"0-{int(young_years)}_YEARS"
                count_young += 1
            elif age < old_years:
                bracket = f"{int(young_years)}-{int(old_years)}_YEARS"
                count_medium += 1
            else:
                bracket = f"{int(old_years)}+_YEARS"
                count_old += 1

            items.append(AgeingCameraItem(
                camera_id=cid,
                name=cname,
                district=dist,
                installation_date=str(inst_date),
                age_years=round(age, 2),
                bracket=bracket
            ))
        else:
            count_unknown += 1
            items.append(AgeingCameraItem(
                camera_id=cid,
                name=cname,
                district=dist,
                installation_date=None,
                age_years=None,
                bracket="UNKNOWN"
            ))

    return AgeingReportResponse(
        threshold_years_young=young_years,
        threshold_years_old=old_years,
        total_analyzed=len(rows),
        known_install_dates=known_dates,
        missing_install_dates=count_unknown,
        count_young=count_young,
        count_medium=count_medium,
        count_old=count_old,
        count_unknown=count_unknown,
        cameras=items
    )


@router.get(
    "/analytics/coverage",
    response_model=CoverageAnalysisResponse,
    summary="GIS Camera Coverage Analysis",
    description="Calculates coverage radius and visibility estimates for registered cameras with verified coordinates."
)
async def get_coverage_analysis(
    radius_meters: float = Query(300.0, ge=50.0, le=5000.0, description="Estimated camera visibility radius in meters"),
    user: UserContext = Depends(get_current_user)
):
    if not postgres.pool:
        raise HTTPException(status_code=503, detail="PostgreSQL database offline")

    async with postgres.pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM public.cctv_assets;") or 0
        rows = await conn.fetch("""
            SELECT camera_id, name, district, city, latitude, longitude, camera_type, operational_status
            FROM public.cctv_assets
            WHERE latitude IS NOT NULL AND longitude IS NOT NULL;
        """)

    active_items = []
    for r in rows:
        active_items.append({
            "camera_id": r["camera_id"],
            "name": r["name"],
            "district": r["district"],
            "city": r["city"],
            "latitude": r["latitude"],
            "longitude": r["longitude"],
            "camera_type": r["camera_type"],
            "operational_status": r["operational_status"],
            "radius_meters": radius_meters
        })

    return CoverageAnalysisResponse(
        total_cameras=total,
        mapped_cameras_count=len(rows),
        unmapped_cameras_count=total - len(rows),
        coverage_model="CONICAL_RADIUS_ESTIMATE",
        default_radius_meters=radius_meters,
        coverage_analysis_available=len(rows) > 0,
        reference_data_status="ACTIVE" if len(rows) > 0 else "COORDINATES_PENDING",
        note="Coverage represents physical camera optical estimate based on verified GPS points. Official police beat coverage boundaries require jurisdictional polygon layers to be uploaded.",
        active_cameras_with_coordinates=active_items
    )


@router.get(
    "/analytics/gap-analysis",
    response_model=GapAnalysisResponse,
    summary="GIS Coverage Gap Analysis",
    description="Gap analysis framework. Strictly identifies missing reference layers without inventing synthetic high-risk areas."
)
async def get_gap_analysis(user: UserContext = Depends(get_current_user)):
    # Sentinel Gap Analysis Rule: Never fabricate high risk areas or claim coverage gaps without actual reference layers
    return GapAnalysisResponse(
        gap_analysis_available=False,
        reason="Coverage gap analysis requires authoritative reference polygon layers (police jurisdiction boundaries, road network shapefiles, or designated critical infrastructure zones) to be uploaded into Sentinel.",
        reference_layers_required=[
            "POLICE_STATION_JURISDICTION_POLYGONS",
            "GUJARAT_STATE_HIGHWAY_ROAD_NETWORK",
            "CRITICAL_INFRASTRUCTURE_POINTS_OF_INTEREST"
        ],
        reference_layers_configured=[],
        uncovered_priority_zones=[],
        message="No synthetic coverage gaps were generated. Please upload authoritative GIS reference shapefiles or GeoJSON datasets through Sentinel GIS Administration to enable gap computation."
    )


# ==============================================================================
# 8. DYNAMIC CATALOGUE SYNCHRONIZATION
# ==============================================================================

@router.post(
    "/sync-catalogue",
    summary="Synchronize with Live Gujarat Camera Catalogue",
    description="Discovers live cameras from the Phase 0 Gujarat catalogue, updating real coordinates and statuses while preserving administrative registry metadata."
)
async def sync_catalogue_cameras(
    user: UserContext = Depends(require_roles([UserRole.SUPER_ADMIN, UserRole.OPERATOR]))
):
    if not postgres.pool:
        raise HTTPException(status_code=503, detail="PostgreSQL database offline")

    cat_service = CameraCatalogueService.get_instance()
    catalogue_cameras = await cat_service.get_cameras()

    if not catalogue_cameras:
        return {"status": "warning", "message": "Catalogue returned 0 cameras or is offline", "synced": 0}

    discovered = 0
    updated = 0

    sync_sql = """
        INSERT INTO public.cctv_assets (
            camera_id, source_camera_id, name, display_name,
            district, city, latitude, longitude, geom,
            location_source, gis_verification_status,
            operational_status, health_status, codec, is_active,
            created_by, updated_by
        ) VALUES (
            $1, $1, $2, $2,
            $3, $3, $4, $5,
            CASE WHEN $4 IS NOT NULL AND $5 IS NOT NULL 
                 THEN json_build_object('type', 'Point', 'coordinates', json_build_array($5, $4))::text 
                 ELSE NULL END,
            'CATALOGUE',
            CASE WHEN $4 IS NOT NULL AND $5 IS NOT NULL THEN 'VERIFIED' ELSE 'COORDINATES_UNAVAILABLE' END,
            'ACTIVE', $6, $7, true,
            $8, $8
        )
        ON CONFLICT (camera_id) DO UPDATE
        SET latitude = COALESCE(EXCLUDED.latitude, public.cctv_assets.latitude),
            longitude = COALESCE(EXCLUDED.longitude, public.cctv_assets.longitude),
            geom = COALESCE(EXCLUDED.geom, public.cctv_assets.geom),
            gis_verification_status = CASE 
                WHEN COALESCE(EXCLUDED.latitude, public.cctv_assets.latitude) IS NOT NULL THEN 'VERIFIED'
                ELSE 'COORDINATES_UNAVAILABLE'
            END,
            health_status = EXCLUDED.health_status,
            codec = COALESCE(EXCLUDED.codec, public.cctv_assets.codec),
            updated_at = NOW(),
            updated_by = EXCLUDED.updated_by;
    """

    async with postgres.pool.acquire() as conn:
        existing_ids = set(await conn.fetch("SELECT camera_id FROM public.cctv_assets;"))
        existing_set = {r["camera_id"] for r in existing_ids}

        async with conn.transaction():
            for cam in catalogue_cameras:
                cid = cam.get("camera_id") or cam.get("id")
                if not cid:
                    continue
                cname = cam.get("name") or cid
                city = cam.get("city")
                lat = cam.get("latitude")
                lon = cam.get("longitude")
                h_status = "ONLINE" if cam.get("status") == "online" else "UNKNOWN"
                codec = cam.get("codec") or "h264"

                await conn.execute(
                    sync_sql,
                    cid, cname, city, lat, lon, h_status, codec, user.username
                )

                if cid in existing_set:
                    updated += 1
                else:
                    discovered += 1

    await AuditService.log_event(
        pool=postgres.pool,
        action="UPDATE",
        entity_type="CATALOGUE_SYNC",
        entity_id="PHASE0_CATALOGUE",
        user=user,
        new_value={"catalogue_count": len(catalogue_cameras), "discovered": discovered, "updated": updated},
        reason=f"Catalogue synchronized by {user.username}: {discovered} discovered, {updated} updated."
    )

    return {
        "status": "success",
        "total_catalogue_cameras": len(catalogue_cameras),
        "discovered_new": discovered,
        "updated_existing": updated,
        "timestamp": datetime.now().isoformat()
    }
