-- ==============================================================================
-- SENTINEL PHASE 1: CCTV ASSET REGISTRY & GIS ASSET MANAGEMENT SCHEMA
-- File: backend/sql/005_cctv_asset_registry.sql
-- ==============================================================================

-- Extension setup (optional if installed on server)
DO $$
BEGIN
    PERFORM 1 FROM pg_available_extensions WHERE name = 'postgis';
    IF FOUND THEN
        EXECUTE 'CREATE EXTENSION IF NOT EXISTS postgis';
    END IF;
END $$;


-- ------------------------------------------------------------------------------
-- 1. DEPARTMENTS & ORGANIZATIONAL HIERARCHY
-- ------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.departments (
    id SERIAL PRIMARY KEY,
    department_id VARCHAR(50) UNIQUE NOT NULL,
    code VARCHAR(30) UNIQUE NOT NULL,
    name VARCHAR(200) NOT NULL,
    department_type VARCHAR(50) NOT NULL, -- STATE, ZONE, RANGE, DISTRICT, POLICE_STATION, OPERATIONAL_UNIT
    parent_id INTEGER REFERENCES public.departments(id) ON DELETE SET NULL,
    district VARCHAR(100),
    state VARCHAR(50) DEFAULT 'Gujarat',
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_departments_parent ON public.departments(parent_id);
CREATE INDEX IF NOT EXISTS idx_departments_district ON public.departments(district);
CREATE INDEX IF NOT EXISTS idx_departments_type ON public.departments(department_type);

-- ------------------------------------------------------------------------------
-- 2. USERS & ROLE-BASED ACCESS CONTROL (RBAC)
-- ------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.users (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) UNIQUE NOT NULL,
    username VARCHAR(100) UNIQUE NOT NULL,
    email VARCHAR(150) UNIQUE,
    full_name VARCHAR(150),
    role VARCHAR(50) NOT NULL DEFAULT 'OPERATOR', -- SUPER_ADMIN, DEPARTMENT_ADMIN, OPERATOR, VIEWER, AUDITOR
    department_id INTEGER REFERENCES public.departments(id) ON DELETE SET NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_role ON public.users(role);

-- ------------------------------------------------------------------------------
-- 3. CCTV ASSET REGISTRY (Model 1 Canonical Asset Layer)
-- ------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.cctv_assets (
    id BIGSERIAL PRIMARY KEY,
    camera_id VARCHAR(100) UNIQUE NOT NULL, -- Foreign/Canonical ID shared with public.cameras(camera_id)
    source_camera_id VARCHAR(100),
    name VARCHAR(250) NOT NULL,
    display_name VARCHAR(250),
    description TEXT,

    -- Ownership & Governance
    department_id INTEGER REFERENCES public.departments(id) ON DELETE SET NULL,
    owning_department VARCHAR(200),
    operating_department VARCHAR(200),
    ownership_type VARCHAR(50) DEFAULT 'GOVERNMENT', -- GOVERNMENT, POLICE, MUNICIPAL, HIGHWAY_AUTHORITY, PRIVATE_PARTNERSHIP

    -- Classification
    camera_type VARCHAR(50) DEFAULT 'FIXED_BULLET', -- FIXED_BULLET, FIXED_DOME, PTZ, ANPR, PANORAMIC_360, THERMAL
    camera_category VARCHAR(50) DEFAULT 'TRAFFIC', -- TRAFFIC, PUBLIC_SAFETY, PERIMETER, BORDER, FACILITY
    form_factor VARCHAR(30) DEFAULT 'FIXED', -- FIXED, PTZ
    environment VARCHAR(30) DEFAULT 'OUTDOOR', -- OUTDOOR, INDOOR
    purpose VARCHAR(100) DEFAULT 'JUNCTION_MONITORING',

    -- Physical Location & GIS
    address TEXT,
    city VARCHAR(100),
    district VARCHAR(100),
    state VARCHAR(50) DEFAULT 'Gujarat',
    pincode VARCHAR(20),
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    geom TEXT, -- GeoJSON Point string or WKT geometry representation
    location_source VARCHAR(50) DEFAULT 'CATALOGUE', -- SURVEY, GPS_DEVICE, CATALOGUE, MANUAL_ONBOARDING, MAP_SELECTION
    gis_verification_status VARCHAR(50) DEFAULT 'UNVERIFIED', -- VERIFIED, UNVERIFIED, PENDING_SURVEY, COORDINATES_UNAVAILABLE

    -- Infrastructure & Site
    mounting_type VARCHAR(50) DEFAULT 'POLE', -- POLE, GANTRY, BUILDING_WALL, ROOFTOP, TRAFFIC_LIGHT
    site_id VARCHAR(100),
    pole_id VARCHAR(100),
    power_source VARCHAR(50) DEFAULT 'GRID', -- GRID, SOLAR, UPS_BACKUP, BATTERY
    network_provider VARCHAR(100),
    connectivity_type VARCHAR(50) DEFAULT 'OPTICAL_FIBER', -- OPTICAL_FIBER, 4G_LTE, 5G, WIRELESS_PTP, COPPER_LAN
    bandwidth_mbps DOUBLE PRECISION,

    -- Technical & Stream Properties
    manufacturer VARCHAR(100),
    model_number VARCHAR(100),
    serial_number VARCHAR(100),
    firmware_version VARCHAR(50),
    ip_address VARCHAR(50),
    mac_address VARCHAR(50),
    rtsp_port INTEGER DEFAULT 8554,
    codec VARCHAR(30) DEFAULT 'h264',
    resolution VARCHAR(30),
    fps DOUBLE PRECISION,
    bitrate_kbps INTEGER,
    stream_protocol VARCHAR(30) DEFAULT 'HLS',
    rtsp_available BOOLEAN NOT NULL DEFAULT true,
    hls_available BOOLEAN NOT NULL DEFAULT true,
    webrtc_available BOOLEAN NOT NULL DEFAULT true,

    -- Lifecyle & Dates (Ageing Analysis)
    installation_date DATE,
    commissioning_date DATE,
    warranty_expiry_date DATE,

    -- Storage & Retention
    storage_type VARCHAR(50) DEFAULT 'CENTRAL_SAN', -- EDGE_SD, NVR_LOCAL, CENTRAL_SAN, CLOUD_HYBRID
    storage_location VARCHAR(150),
    retention_days INTEGER DEFAULT 30,
    storage_capacity_gb DOUBLE PRECISION,
    recording_enabled BOOLEAN NOT NULL DEFAULT true,

    -- Operational & Health
    operational_status VARCHAR(50) NOT NULL DEFAULT 'ACTIVE', -- ACTIVE, INACTIVE, DECOMMISSIONED, DISCOVERED_PENDING_REGISTRATION
    health_status VARCHAR(30) NOT NULL DEFAULT 'UNKNOWN', -- ONLINE, OFFLINE, DEGRADED, MAINTENANCE, UNKNOWN
    last_seen TIMESTAMPTZ,
    last_health_check TIMESTAMPTZ,
    maintenance_status VARCHAR(50) NOT NULL DEFAULT 'OPERATIONAL', -- OPERATIONAL, MAINTENANCE_REQUIRED, UNDER_MAINTENANCE, REPLACEMENT_SCHEDULED

    -- Administrative Metadata
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by VARCHAR(100) DEFAULT 'SYSTEM',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by VARCHAR(100) DEFAULT 'SYSTEM'
);

-- Spatial and Filtering Indexes
CREATE INDEX IF NOT EXISTS idx_cctv_assets_coords ON public.cctv_assets(latitude, longitude);
CREATE INDEX IF NOT EXISTS idx_cctv_assets_district ON public.cctv_assets(district);
CREATE INDEX IF NOT EXISTS idx_cctv_assets_city ON public.cctv_assets(city);
CREATE INDEX IF NOT EXISTS idx_cctv_assets_dept ON public.cctv_assets(department_id);
CREATE INDEX IF NOT EXISTS idx_cctv_assets_type ON public.cctv_assets(camera_type);
CREATE INDEX IF NOT EXISTS idx_cctv_assets_op_status ON public.cctv_assets(operational_status);
CREATE INDEX IF NOT EXISTS idx_cctv_assets_health ON public.cctv_assets(health_status);
CREATE INDEX IF NOT EXISTS idx_cctv_assets_install_date ON public.cctv_assets(installation_date);

-- ------------------------------------------------------------------------------
-- 4. CCTV MAINTENANCE MANAGEMENT
-- ------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.cctv_maintenance (
    id BIGSERIAL PRIMARY KEY,
    ticket_number VARCHAR(50) UNIQUE NOT NULL,
    camera_id VARCHAR(100) NOT NULL,
    issue_description TEXT NOT NULL,
    maintenance_type VARCHAR(50) NOT NULL, -- PREVENTIVE, CORRECTIVE, ROUTINE_INSPECTION, HARDWARE_REPLACEMENT, FIRMWARE_UPGRADE, OPTICAL_CLEANING, CALIBRATION
    priority VARCHAR(20) NOT NULL DEFAULT 'MEDIUM', -- LOW, MEDIUM, HIGH, CRITICAL
    status VARCHAR(30) NOT NULL DEFAULT 'OPEN', -- OPEN, SCHEDULED, IN_PROGRESS, COMPLETED, CANCELLED
    reported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    scheduled_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    assigned_to VARCHAR(150),
    reported_by VARCHAR(150) DEFAULT 'SYSTEM_MONITOR',
    resolution TEXT,
    notes TEXT,
    cost_inr NUMERIC(12, 2),
    created_by VARCHAR(100) DEFAULT 'SYSTEM',
    updated_by VARCHAR(100) DEFAULT 'SYSTEM',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cctv_maint_camera ON public.cctv_maintenance(camera_id);
CREATE INDEX IF NOT EXISTS idx_cctv_maint_status ON public.cctv_maintenance(status);
CREATE INDEX IF NOT EXISTS idx_cctv_maint_reported ON public.cctv_maintenance(reported_at DESC);

-- ------------------------------------------------------------------------------
-- 5. IMMUTABLE APPEND-ONLY AUDIT LOG
-- ------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.cctv_audit_log (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    user_id VARCHAR(50),
    username VARCHAR(100) NOT NULL DEFAULT 'OPERATOR',
    role VARCHAR(50) NOT NULL DEFAULT 'OPERATOR',
    action VARCHAR(50) NOT NULL, -- CREATE, UPDATE, DELETE, IMPORT, EXPORT, STATUS_CHANGE, MAINTENANCE_CHANGE, DEPARTMENT_CHANGE, CALIBRATION_CHANGE
    entity_type VARCHAR(50) NOT NULL, -- CAMERA_ASSET, DEPARTMENT, MAINTENANCE_TICKET, REGISTRY_EXPORT
    entity_id VARCHAR(100) NOT NULL,
    camera_id VARCHAR(100),
    old_value JSONB,
    new_value JSONB,
    reason TEXT,
    ip_address VARCHAR(50)
);

CREATE INDEX IF NOT EXISTS idx_cctv_audit_cam ON public.cctv_audit_log(camera_id);
CREATE INDEX IF NOT EXISTS idx_cctv_audit_time ON public.cctv_audit_log(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_cctv_audit_action ON public.cctv_audit_log(action);

-- ------------------------------------------------------------------------------
-- 6. SEED AUTHORITATIVE GUJARAT POLICE DEPARTMENT HIERARCHY
-- ------------------------------------------------------------------------------

INSERT INTO public.departments (id, department_id, code, name, department_type, parent_id, district)
VALUES
    (1, 'DEPT_GUJ_HQ', 'DGP_GUJ', 'Gujarat State Police Headquarters', 'STATE', NULL, 'Gandhinagar'),
    (2, 'DEPT_AHM_CITY', 'CP_AHM', 'Ahmedabad City Police Commissionerate', 'ZONE', 1, 'Ahmedabad'),
    (3, 'DEPT_SUR_CITY', 'CP_SUR', 'Surat City Police Commissionerate', 'ZONE', 1, 'Surat'),
    (4, 'DEPT_RJK_CITY', 'CP_RJK', 'Rajkot City Police Commissionerate', 'ZONE', 1, 'Rajkot'),
    (5, 'DEPT_GND_RANGE', 'DIG_GND', 'Gandhinagar Police Range', 'RANGE', 1, 'Gandhinagar'),
    (6, 'DEPT_JUN_DIST', 'SP_JUN', 'Junagadh District Police Office', 'DISTRICT', 1, 'Junagadh'),
    (7, 'DEPT_NAV_DIST', 'SP_NAV', 'Navsari District Police Office', 'DISTRICT', 1, 'Navsari'),
    (8, 'DEPT_PAT_DIST', 'SP_PAT', 'Patan District Police Office', 'DISTRICT', 1, 'Patan'),
    (9, 'DEPT_BAN_DIST', 'SP_BAN', 'Banaskantha District Police Office', 'DISTRICT', 1, 'Banaskantha'),
    (10, 'DEPT_KUT_DIST', 'SP_KUT', 'Kutch East (Gandhidham) District Police', 'DISTRICT', 1, 'Gandhidham'),
    (11, 'DEPT_SOM_DIST', 'SP_SOM', 'Gir Somnath District Police Office', 'DISTRICT', 1, 'Gir Somnath')
ON CONFLICT (department_id) DO UPDATE
SET name = EXCLUDED.name, department_type = EXCLUDED.department_type, district = EXCLUDED.district;

-- Update the serial sequence so next auto-generated id starts from 12+
SELECT setval('public.departments_id_seq', (SELECT MAX(id) FROM public.departments));

-- Ensure statewide registry ingestion node exists in edge_nodes
INSERT INTO public.edge_nodes (node_id, name, city, latitude, longitude, status)
VALUES ('NODE_GUJ_01', 'Statewide Registry Ingestion Node', 'Gandhinagar', 23.2156, 72.6369, 'online')
ON CONFLICT (node_id) DO UPDATE SET status = 'online';

-- ------------------------------------------------------------------------------
-- 7. SEED INITIAL SYSTEM ROLES / USERS
-- ------------------------------------------------------------------------------

INSERT INTO public.users (user_id, username, email, full_name, role, department_id)
VALUES
    ('USR_SUPER_01', 'admin', 'admin@police.gujarat.gov.in', 'State Surveillance Controller', 'SUPER_ADMIN', 1),
    ('USR_DEPT_AHM', 'dept_admin_ahm', 'cp.ahmedabad@police.gujarat.gov.in', 'Ahmedabad Command Incharge', 'DEPARTMENT_ADMIN', 2),
    ('USR_OPERATOR_01', 'operator', 'operator@sentinel.police.gujarat.gov.in', 'Sentinel Operations Officer', 'OPERATOR', 1),
    ('USR_AUDITOR_01', 'auditor', 'vigilance@police.gujarat.gov.in', 'State Police Vigilance Auditor', 'AUDITOR', 1),
    ('USR_VIEWER_01', 'viewer', 'public.relations@police.gujarat.gov.in', 'Operations Watch Viewer', 'VIEWER', 1)
ON CONFLICT (username) DO UPDATE
SET role = EXCLUDED.role, full_name = EXCLUDED.full_name;

-- ------------------------------------------------------------------------------
-- 8. RECONCILE PHASE 0 CAMERAS INTO CANONICAL CCTV ASSET REGISTRY
-- ------------------------------------------------------------------------------

INSERT INTO public.cctv_assets (
    camera_id,
    source_camera_id,
    name,
    display_name,
    city,
    district,
    latitude,
    longitude,
    geom,
    location_source,
    gis_verification_status,
    department_id,
    owning_department,
    operational_status,
    health_status,
    is_active
)
SELECT
    c.camera_id,
    c.camera_id AS source_camera_id,
    c.name,
    c.name AS display_name,
    c.city,
    c.city AS district,
    c.latitude,
    c.longitude,
    CASE 
        WHEN c.latitude IS NOT NULL AND c.longitude IS NOT NULL 
        THEN json_build_object('type', 'Point', 'coordinates', json_build_array(c.longitude, c.latitude))::text
        ELSE NULL 
    END AS geom,
    'CATALOGUE' AS location_source,
    CASE 
        WHEN c.latitude IS NOT NULL AND c.longitude IS NOT NULL THEN 'VERIFIED'
        ELSE 'COORDINATES_UNAVAILABLE'
    END AS gis_verification_status,
    d.id AS department_id,
    d.name AS owning_department,
    'ACTIVE' AS operational_status,
    CASE WHEN c.status = 'online' THEN 'ONLINE' ELSE 'UNKNOWN' END AS health_status,
    c.enabled AS is_active
FROM public.cameras c
LEFT JOIN (
    SELECT DISTINCT ON (UPPER(district)) id, name, district 
    FROM public.departments 
    WHERE district IS NOT NULL
    ORDER BY UPPER(district), id DESC
) d ON UPPER(c.city) = UPPER(d.district)
ON CONFLICT (camera_id) DO UPDATE
SET name = EXCLUDED.name,
    city = EXCLUDED.city,
    district = EXCLUDED.district,
    latitude = EXCLUDED.latitude,
    longitude = EXCLUDED.longitude,
    geom = EXCLUDED.geom,
    gis_verification_status = EXCLUDED.gis_verification_status,
    department_id = COALESCE(public.cctv_assets.department_id, EXCLUDED.department_id),
    owning_department = COALESCE(public.cctv_assets.owning_department, EXCLUDED.owning_department),
    updated_at = NOW();
