import io
import json
import pytest
import httpx

BASE_URL = "http://127.0.0.1:8001"

@pytest.mark.asyncio
async def test_kpi_analytics_database_backed():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10.0) as client:
        resp = await client.get("/api/registry/analytics/kpis")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_cameras" in data
        assert data["total_cameras"] >= 30
        assert data["gis_mapped_count"] >= 30
        assert "by_department" in data
        assert "Ahmedabad City Police Commissionerate" in data["by_department"]
        assert "by_district" in data
        assert data["by_district"].get("Ahmedabad", 0) >= 10


@pytest.mark.asyncio
async def test_rbac_enforcement():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10.0) as client:
        # Viewer should be denied write access
        resp = await client.post(
            "/api/registry/cameras",
            headers={"X-User-Role": "VIEWER"},
            json={"camera_id": "TEST_RBAC_FAIL", "name": "Unauthorized Cam"}
        )
        assert resp.status_code == 403
        assert "Access Denied" in resp.json()["detail"]

        # Auditor should also be denied write access
        resp2 = await client.post(
            "/api/registry/cameras",
            headers={"X-User-Role": "AUDITOR"},
            json={"camera_id": "TEST_RBAC_FAIL_2", "name": "Unauthorized Cam"}
        )
        assert resp2.status_code == 403


@pytest.mark.asyncio
async def test_manual_camera_onboarding_and_validation():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10.0) as client:
        # 1. Invalid coordinates: Latitude > 90
        bad_lat = await client.post(
            "/api/registry/cameras",
            headers={"X-User-Role": "SUPER_ADMIN"},
            json={"camera_id": "CAM_INVALID_LAT", "name": "Bad Coordinates", "latitude": 99.5, "longitude": 72.5}
        )
        assert bad_lat.status_code == 422 or bad_lat.status_code == 400

        # 2. Invalid date logic: Commissioning date earlier than installation date
        bad_dates = await client.post(
            "/api/registry/cameras",
            headers={"X-User-Role": "SUPER_ADMIN"},
            json={
                "camera_id": "CAM_BAD_DATES",
                "name": "Bad Dates",
                "installation_date": "2024-05-10",
                "commissioning_date": "2023-01-01"
            }
        )
        assert bad_dates.status_code == 400
        assert "cannot be earlier than installation date" in bad_dates.json()["detail"]

        # 3. Valid camera creation
        import uuid
        test_cam_id = f"TEST_ONBOARD_{uuid.uuid4().hex[:8].upper()}"
        create_resp = await client.post(
            "/api/registry/cameras",
            headers={"X-User-Role": "SUPER_ADMIN"},
            json={
                "camera_id": test_cam_id,
                "name": "Test Onboarded Camera Gandhinagar",
                "city": "Gandhinagar",
                "district": "Gandhinagar",
                "latitude": 23.2156,
                "longitude": 72.6369,
                "camera_type": "PTZ",
                "camera_category": "TRAFFIC",
                "mounting_type": "GANTRY",
                "operational_status": "ACTIVE"
            }
        )
        assert create_resp.status_code in (201, 200)
        created_data = create_resp.json()
        assert created_data["camera_id"] == test_cam_id
        assert created_data["gis_verification_status"] == "VERIFIED"

        # 4. Duplicate rejection
        dup_resp = await client.post(
            "/api/registry/cameras",
            headers={"X-User-Role": "SUPER_ADMIN"},
            json={
                "camera_id": test_cam_id,
                "name": "Duplicate Test"
            }
        )
        assert dup_resp.status_code == 409

        # 5. Patch update
        patch_resp = await client.patch(
            f"/api/registry/cameras/{test_cam_id}",
            headers={"X-User-Role": "SUPER_ADMIN"},
            json={"display_name": "Updated Gandhinagar Junction", "description": "High resolution PTZ surveillance"}
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["display_name"] == "Updated Gandhinagar Junction"

        # 6. Deactivate and activate
        deact_resp = await client.post(
            f"/api/registry/cameras/{test_cam_id}/deactivate",
            headers={"X-User-Role": "SUPER_ADMIN"}
        )
        assert deact_resp.status_code == 200
        assert deact_resp.json()["operational_status"] == "INACTIVE"
        assert deact_resp.json()["is_active"] is False

        act_resp = await client.post(
            f"/api/registry/cameras/{test_cam_id}/activate",
            headers={"X-User-Role": "SUPER_ADMIN"}
        )
        assert act_resp.status_code == 200
        assert act_resp.json()["operational_status"] == "ACTIVE"


@pytest.mark.asyncio
async def test_csv_import_preview_and_row_errors():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10.0) as client:
        # Create CSV with 1 valid row, 1 invalid latitude row, 1 duplicate row
        csv_data = """camera_id,name,district,city,latitude,longitude,camera_type
CSV_TEST_01,Valid Test Cam,Ahmedabad,Ahmedabad,23.0225,72.5714,FIXED_BULLET
CSV_TEST_02,Invalid Lat Cam,Ahmedabad,Ahmedabad,150.0,72.5714,FIXED_BULLET
CSV_TEST_01,Duplicate Cam,Ahmedabad,Ahmedabad,23.0225,72.5714,FIXED_BULLET
"""
        files = {"file": ("test_import.csv", csv_data.encode("utf-8"), "text/csv")}
        
        # Test preview mode (commit=false)
        preview_resp = await client.post(
            "/api/registry/import/csv?commit=false",
            headers={"X-User-Role": "SUPER_ADMIN"},
            files=files
        )
        assert preview_resp.status_code == 200
        pdata = preview_resp.json()
        assert pdata["total_rows"] == 3
        assert pdata["valid_rows"] == 1
        assert pdata["invalid_rows"] >= 2
        assert len(pdata["errors"]) >= 2
        # Check specific row errors
        err_fields = [e["field"] for e in pdata["errors"]]
        assert "latitude" in err_fields
        assert "camera_id" in err_fields


@pytest.mark.asyncio
async def test_maintenance_ticket_lifecycle():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10.0) as client:
        # 1. Create maintenance ticket
        ticket_payload = {
            "camera_id": "cam01",
            "issue_description": "Optical lens obstruction detected during morning patrol",
            "maintenance_type": "OPTICAL_CLEANING",
            "priority": "HIGH",
            "status": "OPEN",
            "assigned_to": "Surveillance Field Unit 4"
        }
        create_ticket = await client.post(
            "/api/registry/maintenance",
            headers={"X-User-Role": "OPERATOR"},
            json=ticket_payload
        )
        assert create_ticket.status_code in (201, 200)
        t_data = create_ticket.json()
        assert t_data["ticket_number"].startswith("MNT-")
        assert t_data["camera_id"] == "cam01"
        assert t_data["status"] == "OPEN"

        # 2. Verify camera maintenance status updated
        cam_detail = await client.get("/api/registry/cameras/cam01")
        assert cam_detail.status_code == 200
        assert cam_detail.json()["maintenance_status"] in ("MAINTENANCE_REQUIRED", "UNDER_MAINTENANCE")

        # 3. Update ticket to COMPLETED
        patch_ticket = await client.patch(
            f"/api/registry/maintenance/{t_data['ticket_number']}",
            headers={"X-User-Role": "OPERATOR"},
            json={"status": "COMPLETED", "resolution": "Cleaned lens and verified clarity"}
        )
        assert patch_ticket.status_code == 200
        assert patch_ticket.json()["status"] == "COMPLETED"
        assert patch_ticket.json()["completed_at"] is not None


@pytest.mark.asyncio
async def test_audit_log_query():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10.0) as client:
        # Auditor should be able to view logs
        audit_resp = await client.get(
            "/api/registry/audit-log?limit=10",
            headers={"X-User-Role": "AUDITOR"}
        )
        assert audit_resp.status_code == 200
        logs = audit_resp.json()
        assert isinstance(logs, list)
        assert len(logs) > 0
        assert "action" in logs[0]
        assert "entity_type" in logs[0]


@pytest.mark.asyncio
async def test_export_formats():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10.0) as client:
        # 1. CSV Export
        csv_resp = await client.get("/api/registry/export?format=csv", headers={"X-User-Role": "SUPER_ADMIN"})
        assert csv_resp.status_code == 200
        assert "text/csv" in csv_resp.headers.get("content-type", "")
        assert "camera_id,name" in csv_resp.text

        # 2. GeoJSON Export
        geojson_resp = await client.get("/api/registry/export?format=geojson", headers={"X-User-Role": "SUPER_ADMIN"})
        assert geojson_resp.status_code == 200
        gj_data = geojson_resp.json()
        assert gj_data["type"] == "FeatureCollection"
        assert len(gj_data["features"]) >= 30

        # 3. Excel Export
        excel_resp = await client.get("/api/registry/export?format=excel", headers={"X-User-Role": "SUPER_ADMIN"})
        assert excel_resp.status_code == 200
        assert len(excel_resp.content) > 1000 # Valid binary zip/xlsx


@pytest.mark.asyncio
async def test_ageing_and_gap_analysis_integrity():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10.0) as client:
        # Ageing: strictly missing dates as UNKNOWN, zero fabrication
        ageing = await client.get("/api/registry/analytics/ageing?young_years=2.0&old_years=5.0")
        assert ageing.status_code == 200
        adata = ageing.json()
        assert adata["total_analyzed"] >= 30
        assert adata["missing_install_dates"] >= 30 # No fake installation dates were invented

        # Gap analysis: explicit transparent state when reference data is missing
        gap = await client.get("/api/registry/analytics/gap-analysis")
        assert gap.status_code == 200
        gdata = gap.json()
        assert gdata["gap_analysis_available"] is False
        assert len(gdata["reference_layers_required"]) > 0
        assert len(gdata["uncovered_priority_zones"]) == 0 # ZERO fabricated gap zones
