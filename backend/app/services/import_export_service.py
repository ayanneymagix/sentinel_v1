import io
import csv
import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
import asyncpg
from app.models.registry_schemas import (
    ImportPreviewResponse,
    ImportSummaryResponse,
    RowValidationError,
    UserContext
)
from app.services.audit_service import AuditService

logger = logging.getLogger("sentinel.registry.import_export")

REQUIRED_FIELDS = ["camera_id", "name"]

VALID_CAMERA_TYPES = {
    "FIXED_BULLET", "FIXED_DOME", "PTZ", "ANPR", "PANORAMIC_360", "THERMAL", "SPEED_DOME"
}

VALID_OPERATIONAL_STATUSES = {
    "ACTIVE", "INACTIVE", "DECOMMISSIONED", "DISCOVERED_PENDING_REGISTRATION"
}

class ImportExportService:

    @staticmethod
    def _parse_date(val: Any) -> Optional[date]:
        if not val or str(val).strip() == "" or str(val).strip().upper() in ("NULL", "NONE", "UNKNOWN", "NOT_AVAILABLE"):
            return None
        if isinstance(val, (datetime, date)):
            return val if isinstance(val, date) else val.date()
        s = str(val).strip()
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                continue
        raise ValueError(f"Invalid date format '{s}'. Expected YYYY-MM-DD or DD-MM-YYYY.")

    @classmethod
    def parse_csv(cls, content: bytes) -> List[Dict[str, Any]]:
        text = content.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        rows = []
        for r in reader:
            clean_row = {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in r.items() if k}
            rows.append(clean_row)
        return rows

    @classmethod
    def parse_excel(cls, content: bytes) -> List[Dict[str, Any]]:
        wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
        sheet = wb.active
        headers = []
        rows = []
        for idx, row in enumerate(sheet.iter_rows(values_only=True)):
            if idx == 0:
                headers = [str(cell).strip() if cell is not None else f"col_{cidx}" for cidx, cell in enumerate(row)]
            else:
                if not any(row):
                    continue
                row_dict = {}
                for cidx, cell in enumerate(row):
                    if cidx < len(headers):
                        h = headers[cidx]
                        row_dict[h] = str(cell).strip() if isinstance(cell, str) else cell
                rows.append(row_dict)
        return rows

    @classmethod
    async def validate_rows(
        cls,
        rows: List[Dict[str, Any]],
        conn: asyncpg.Connection
    ) -> Tuple[List[Dict[str, Any]], List[RowValidationError]]:
        valid_items: List[Dict[str, Any]] = []
        errors: List[RowValidationError] = []
        seen_camera_ids_in_batch = set()

        # Query existing camera_ids from database
        existing_db_ids = set()
        db_rows = await conn.fetch("SELECT camera_id FROM public.cctv_assets;")
        for r in db_rows:
            existing_db_ids.add(r["camera_id"].upper())

        # Query valid department codes/IDs
        dept_lookup: Dict[str, int] = {}
        drows = await conn.fetch("SELECT id, code FROM public.departments;")
        for dr in drows:
            dept_lookup[str(dr["id"])] = dr["id"]
            if dr["code"]:
                dept_lookup[dr["code"].upper()] = dr["id"]

        for idx, raw in enumerate(rows, start=1):
            row_errors: List[RowValidationError] = []

            # 1. camera_id check
            cid = str(raw.get("camera_id") or "").strip()
            if not cid:
                row_errors.append(RowValidationError(
                    row_number=idx,
                    camera_id=None,
                    field="camera_id",
                    error_message="camera_id is mandatory and cannot be empty."
                ))
            else:
                cid_upper = cid.upper()
                if cid_upper in seen_camera_ids_in_batch:
                    row_errors.append(RowValidationError(
                        row_number=idx,
                        camera_id=cid,
                        field="camera_id",
                        error_message=f"Duplicate camera_id '{cid}' found within import file."
                    ))
                seen_camera_ids_in_batch.add(cid_upper)

            # 2. name check
            cname = str(raw.get("name") or "").strip()
            if not cname:
                row_errors.append(RowValidationError(
                    row_number=idx,
                    camera_id=cid,
                    field="name",
                    error_message="Camera name is mandatory and cannot be empty."
                ))

            # 3. coordinates check
            lat_val = raw.get("latitude")
            lng_val = raw.get("longitude")
            parsed_lat = None
            parsed_lng = None

            if lat_val is not None and str(lat_val).strip() != "":
                try:
                    parsed_lat = float(lat_val)
                    if parsed_lat < -90.0 or parsed_lat > 90.0:
                        row_errors.append(RowValidationError(
                            row_number=idx,
                            camera_id=cid,
                            field="latitude",
                            error_message=f"Latitude {parsed_lat} out of valid bounds [-90, +90]."
                        ))
                except ValueError:
                    row_errors.append(RowValidationError(
                        row_number=idx,
                        camera_id=cid,
                        field="latitude",
                        error_message=f"Invalid numeric latitude '{lat_val}'."
                    ))

            if lng_val is not None and str(lng_val).strip() != "":
                try:
                    parsed_lng = float(lng_val)
                    if parsed_lng < -180.0 or parsed_lng > 180.0:
                        row_errors.append(RowValidationError(
                            row_number=idx,
                            camera_id=cid,
                            field="longitude",
                            error_message=f"Longitude {parsed_lng} out of valid bounds [-180, +180]."
                        ))
                except ValueError:
                    row_errors.append(RowValidationError(
                        row_number=idx,
                        camera_id=cid,
                        field="longitude",
                        error_message=f"Invalid numeric longitude '{lng_val}'."
                    ))

            # 4. Department validation
            dept_ref = raw.get("department_id") or raw.get("department_code")
            resolved_dept_id = None
            if dept_ref:
                ref_key = str(dept_ref).strip().upper()
                if ref_key in dept_lookup:
                    resolved_dept_id = dept_lookup[ref_key]
                else:
                    row_errors.append(RowValidationError(
                        row_number=idx,
                        camera_id=cid,
                        field="department",
                        error_message=f"Department reference '{dept_ref}' does not exist in authoritative department hierarchy."
                    ))

            # 5. Dates validation
            install_date = None
            comm_date = None
            warr_date = None

            try:
                install_date = cls._parse_date(raw.get("installation_date"))
            except ValueError as e:
                row_errors.append(RowValidationError(
                    row_number=idx, camera_id=cid, field="installation_date", error_message=str(e)
                ))

            try:
                comm_date = cls._parse_date(raw.get("commissioning_date"))
            except ValueError as e:
                row_errors.append(RowValidationError(
                    row_number=idx, camera_id=cid, field="commissioning_date", error_message=str(e)
                ))

            try:
                warr_date = cls._parse_date(raw.get("warranty_expiry_date"))
            except ValueError as e:
                row_errors.append(RowValidationError(
                    row_number=idx, camera_id=cid, field="warranty_expiry_date", error_message=str(e)
                ))

            if install_date and comm_date and comm_date < install_date:
                row_errors.append(RowValidationError(
                    row_number=idx,
                    camera_id=cid,
                    field="commissioning_date",
                    error_message=f"Commissioning date ({comm_date}) cannot be earlier than installation date ({install_date})."
                ))

            # 6. Camera Type validation
            cam_type = (raw.get("camera_type") or "FIXED_BULLET").strip().upper()
            if cam_type not in VALID_CAMERA_TYPES:
                row_errors.append(RowValidationError(
                    row_number=idx,
                    camera_id=cid,
                    field="camera_type",
                    error_message=f"Invalid camera_type '{cam_type}'. Allowed types: {sorted(list(VALID_CAMERA_TYPES))}."
                ))

            # 7. Operational Status
            op_status = (raw.get("operational_status") or "ACTIVE").strip().upper()
            if op_status not in VALID_OPERATIONAL_STATUSES:
                row_errors.append(RowValidationError(
                    row_number=idx,
                    camera_id=cid,
                    field="operational_status",
                    error_message=f"Invalid operational_status '{op_status}'. Allowed: {sorted(list(VALID_OPERATIONAL_STATUSES))}."
                ))

            if row_errors:
                errors.extend(row_errors)
            else:
                item = {
                    "camera_id": cid,
                    "source_camera_id": str(raw.get("source_camera_id") or cid),
                    "name": cname,
                    "display_name": str(raw.get("display_name") or cname),
                    "description": raw.get("description"),
                    "department_id": resolved_dept_id,
                    "district": raw.get("district") or raw.get("city"),
                    "city": raw.get("city"),
                    "state": raw.get("state") or "Gujarat",
                    "pincode": raw.get("pincode"),
                    "latitude": parsed_lat,
                    "longitude": parsed_lng,
                    "camera_type": cam_type,
                    "camera_category": raw.get("camera_category") or "TRAFFIC",
                    "mounting_type": raw.get("mounting_type") or "POLE",
                    "manufacturer": raw.get("manufacturer"),
                    "model_number": raw.get("model_number"),
                    "serial_number": raw.get("serial_number"),
                    "installation_date": install_date,
                    "commissioning_date": comm_date,
                    "warranty_expiry_date": warr_date,
                    "operational_status": op_status,
                    "health_status": (raw.get("health_status") or "UNKNOWN").upper(),
                    "storage_type": raw.get("storage_type") or "CENTRAL_SAN",
                    "is_update": (cid.upper() in existing_db_ids)
                }
                valid_items.append(item)

        return valid_items, errors

    @classmethod
    async def process_import(
        cls,
        file_bytes: bytes,
        filename: str,
        commit: bool,
        pool: asyncpg.Pool,
        user: UserContext
    ) -> ImportSummaryResponse | ImportPreviewResponse:
        is_excel = filename.lower().endswith((".xlsx", ".xls"))
        rows = cls.parse_excel(file_bytes) if is_excel else cls.parse_csv(file_bytes)

        async with pool.acquire() as conn:
            valid_items, errors = await cls.validate_rows(rows, conn)

            if not commit:
                # Preview mode only
                return ImportPreviewResponse(
                    total_rows=len(rows),
                    valid_rows=len(valid_items),
                    invalid_rows=len({e.row_number for e in errors}),
                    preview_items=valid_items[:25], # first 25 preview records
                    errors=errors
                )

            # Commit mode
            inserted = 0
            updated = 0
            skipped = 0

            async with conn.transaction():
                insert_sql = """
                    INSERT INTO public.cctv_assets (
                        camera_id, source_camera_id, name, display_name, description,
                        department_id, district, city, state, pincode,
                        latitude, longitude, geom, camera_type, camera_category,
                        mounting_type, manufacturer, model_number, serial_number,
                        installation_date, commissioning_date, warranty_expiry_date,
                        operational_status, health_status, storage_type,
                        location_source, gis_verification_status, created_by, updated_by
                    ) VALUES (
                        $1, $2, $3, $4, $5,
                        $6, $7, $8, $9, $10,
                        $11, $12, $13,
                        $14, $15, $16, $17, $18, $19,
                        $20, $21, $22, $23, $24, $25,
                        'MANUAL_IMPORT', $26,
                        $27, $27
                    )
                    ON CONFLICT (camera_id) DO UPDATE
                    SET name = EXCLUDED.name,
                        display_name = EXCLUDED.display_name,
                        district = COALESCE(EXCLUDED.district, public.cctv_assets.district),
                        city = COALESCE(EXCLUDED.city, public.cctv_assets.city),
                        latitude = COALESCE(EXCLUDED.latitude, public.cctv_assets.latitude),
                        longitude = COALESCE(EXCLUDED.longitude, public.cctv_assets.longitude),
                        geom = COALESCE(EXCLUDED.geom, public.cctv_assets.geom),
                        gis_verification_status = COALESCE(EXCLUDED.gis_verification_status, public.cctv_assets.gis_verification_status),
                        camera_type = COALESCE(EXCLUDED.camera_type, public.cctv_assets.camera_type),
                        manufacturer = COALESCE(EXCLUDED.manufacturer, public.cctv_assets.manufacturer),
                        model_number = COALESCE(EXCLUDED.model_number, public.cctv_assets.model_number),
                        serial_number = COALESCE(EXCLUDED.serial_number, public.cctv_assets.serial_number),
                        installation_date = COALESCE(EXCLUDED.installation_date, public.cctv_assets.installation_date),
                        commissioning_date = COALESCE(EXCLUDED.commissioning_date, public.cctv_assets.commissioning_date),
                        operational_status = EXCLUDED.operational_status,
                        updated_by = EXCLUDED.updated_by,
                        updated_at = NOW();
                """

                # Sync to public.cameras so live grid / GIS map displays newly imported cameras
                sync_cam_sql = """
                    INSERT INTO public.cameras (
                        camera_id, node_id, name, city, source, latitude, longitude, geom, enabled, status
                    ) VALUES (
                        $1, 'NODE_GUJ_01', $2, $3, 'MANUAL_IMPORT', $4, $5, $6, true, 'online'
                    )
                    ON CONFLICT (camera_id) DO UPDATE
                    SET name = EXCLUDED.name,
                        city = COALESCE(EXCLUDED.city, public.cameras.city),
                        latitude = COALESCE(EXCLUDED.latitude, public.cameras.latitude),
                        longitude = COALESCE(EXCLUDED.longitude, public.cameras.longitude),
                        geom = COALESCE(EXCLUDED.geom, public.cameras.geom),
                        updated_at = NOW();
                """

                import json
                for item in valid_items:
                    lat = item.get("latitude")
                    lng = item.get("longitude")
                    if lat is not None and lng is not None:
                        geom_val = json.dumps({"type": "Point", "coordinates": [float(lng), float(lat)]})
                        gis_status = "VERIFIED"
                    else:
                        geom_val = None
                        gis_status = "COORDINATES_UNAVAILABLE"

                    await conn.execute(
                        insert_sql,
                        item["camera_id"], item["source_camera_id"], item["name"],
                        item["display_name"], item["description"], item["department_id"],
                        item["district"], item["city"], item["state"], item["pincode"],
                        float(lat) if lat is not None else None,
                        float(lng) if lng is not None else None,
                        geom_val,
                        item["camera_type"], item["camera_category"], item["mounting_type"],
                        item["manufacturer"], item["model_number"], item["serial_number"],
                        item["installation_date"], item["commissioning_date"], item["warranty_expiry_date"],
                        item["operational_status"], item["health_status"], item["storage_type"],
                        gis_status, user.username
                    )

                    await conn.execute(
                        sync_cam_sql,
                        item["camera_id"], item["name"], item["city"] or item["district"],
                        float(lat) if lat is not None else None,
                        float(lng) if lng is not None else None,
                        geom_val
                    )

                    if item["is_update"]:
                        updated += 1
                    else:
                        inserted += 1

            # Append audit log
            await AuditService.log_event(
                pool=pool,
                action="IMPORT",
                entity_type="CCTV_ASSET_REGISTRY",
                entity_id=filename,
                user=user,
                new_value={
                    "total_rows": len(rows),
                    "inserted": inserted,
                    "updated": updated,
                    "invalid_rows": len({e.row_number for e in errors}),
                    "filename": filename
                },
                reason=f"Bulk import from {filename} completed: {inserted} inserted, {updated} updated."
            )

            return ImportSummaryResponse(
                total_rows=len(rows),
                valid_rows=len(valid_items),
                invalid_rows=len({e.row_number for e in errors}),
                inserted=inserted,
                updated=updated,
                skipped=len({e.row_number for e in errors}),
                errors=errors
            )

    @classmethod
    async def export_registry(
        cls,
        format_type: str,
        records: List[Dict[str, Any]],
        user: UserContext,
        pool: asyncpg.Pool
    ) -> Tuple[bytes, str, str]:
        """
        Exports actual CCTV asset database records in CSV, Excel or GeoJSON.
        Returns: (file_bytes, media_type, filename)
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Record export in audit trail
        await AuditService.log_event(
            pool=pool,
            action="EXPORT",
            entity_type="CCTV_ASSET_REGISTRY",
            entity_id=f"EXPORT_{format_type.upper()}",
            user=user,
            new_value={"format": format_type, "record_count": len(records)},
            reason=f"User {user.username} ({user.role}) exported {len(records)} camera records in {format_type.upper()} format."
        )

        fieldnames = [
            "camera_id", "name", "display_name", "department_name", "district", "city",
            "state", "latitude", "longitude", "gis_verification_status", "camera_type",
            "camera_category", "mounting_type", "manufacturer", "model_number",
            "serial_number", "installation_date", "commissioning_date", "warranty_expiry_date",
            "operational_status", "health_status", "maintenance_status", "storage_type",
            "retention_days", "created_at"
        ]

        if format_type.lower() == "geojson":
            import json
            features = []
            for r in records:
                lat = r.get("latitude")
                lng = r.get("longitude")
                geom = None
                if lat is not None and lng is not None:
                    geom = {"type": "Point", "coordinates": [lng, lat]}
                props = {k: v for k, v in r.items() if k not in ("latitude", "longitude", "geom")}
                features.append({
                    "type": "Feature",
                    "geometry": geom,
                    "properties": props
                })
            geojson_data = {
                "type": "FeatureCollection",
                "features": features,
                "metadata": {
                    "total_features": len(features),
                    "exported_at": datetime.now().isoformat(),
                    "exported_by": user.username
                }
            }
            output_bytes = json.dumps(geojson_data, indent=2, default=str).encode("utf-8")
            return output_bytes, "application/geo+json", f"sentinel_cctv_registry_{timestamp}.geojson"

        elif format_type.lower() == "excel":
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "CCTV Asset Registry"

            # Gujarat Police styling headers
            header_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
            header_font = Font(name="Arial", size=10, bold=True, color="FFFFFF")
            ws.append([f.replace("_", " ").title() for f in fieldnames])

            for cell in ws[1]:
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal="center", vertical="center")

            for r in records:
                row_vals = [
                    str(r.get(f) if r.get(f) is not None else "")
                    for f in fieldnames
                ]
                ws.append(row_vals)

            # Auto fit columns
            for col in ws.columns:
                max_len = max(len(str(cell.value or "")) for cell in col)
                col_letter = col[0].column_letter
                ws.column_dimensions[col_letter].width = min(max(max_len + 3, 12), 40)

            out_stream = io.BytesIO()
            wb.save(out_stream)
            out_stream.seek(0)
            return out_stream.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", f"sentinel_cctv_registry_{timestamp}.xlsx"

        else: # CSV
            out_stream = io.StringIO()
            writer = csv.DictWriter(out_stream, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for r in records:
                row_clean = {
                    k: (str(v) if v is not None else "") for k, v in r.items()
                }
                writer.writerow(row_clean)
            return out_stream.getvalue().encode("utf-8"), "text/csv", f"sentinel_cctv_registry_{timestamp}.csv"
