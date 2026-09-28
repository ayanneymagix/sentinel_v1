-- ==============================================================================
-- SENTINEL STATEWIDE CCTV INTELLIGENCE ENGINE (GUJARAT POLICE PoC)
-- MODULE 2: POSTGIS SPATIOTEMPORAL TRAJECTORY ENGINE & eGujCop WATCHLIST
-- 
-- Target Scale: 80,000-Node Gujarat Highway CCTV Grid (1,000 km Coverage)
-- Features:
--   1. PostGIS Spatial Extension & Topology Configuration
--   2. Dynamic Schemas: edge_nodes, cameras, events, and egujcop_watchlist
--   3. Spatial GIST Indexes & JSONB GIN Indexes (Sub-second Spatial Slicing)
--   4. RFC 7946 GeoJSON Trajectory Reconstruction Function (LineString + Points)
--   5. Seed Data: 10 Major Gujarat City Nodes & NH48/SG Highway Checkpoints
-- ==============================================================================

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ------------------------------------------------------------------------------
-- 1. EDGE NODES SCHEMA (Distributed Edge Sharding by District/Substation)
-- ------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.edge_nodes (
    node_id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    city VARCHAR(100) NOT NULL,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'online',
    heartbeat_interval_sec INTEGER NOT NULL DEFAULT 5,
    last_heartbeat TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ------------------------------------------------------------------------------
-- 2. DYNAMIC CAMERAS SCHEMA (Vendor-Agnostic, Multi-Protocol Ingestion)
-- ------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.cameras (
    camera_id VARCHAR(50) PRIMARY KEY,
    node_id VARCHAR(50) REFERENCES public.edge_nodes(node_id) ON DELETE SET NULL,
    name VARCHAR(200) NOT NULL,
    city VARCHAR(100),
    source VARCHAR(500) NOT NULL,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    geom geometry(Point, 4326),
    enabled BOOLEAN NOT NULL DEFAULT true,
    status VARCHAR(20) NOT NULL DEFAULT 'online',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Spatial GIST Index for Sub-second Proximity and Radius Queries
CREATE INDEX IF NOT EXISTS idx_cameras_geom_gist
ON public.cameras USING GIST (geom);

CREATE INDEX IF NOT EXISTS idx_cameras_node
ON public.cameras (node_id);

-- ------------------------------------------------------------------------------
-- 2b. CAMERA PHYSICAL CALIBRATION SCHEMA (Homography / Metric Ground Plane)
-- ------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.camera_calibrations (
    calibration_id VARCHAR(50) PRIMARY KEY,
    camera_id VARCHAR(50) NOT NULL REFERENCES public.cameras(camera_id) ON DELETE CASCADE,
    polygon_points JSONB NOT NULL,
    real_width_meters DOUBLE PRECISION NOT NULL,
    real_length_meters DOUBLE PRECISION NOT NULL,
    homography_matrix JSONB NOT NULL,
    calibrated_by VARCHAR(100) NOT NULL DEFAULT 'SYSTEM',
    calibrated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_active BOOLEAN NOT NULL DEFAULT true
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_active_camera_calib 
ON public.camera_calibrations (camera_id) WHERE is_active = true;

CREATE INDEX IF NOT EXISTS idx_camera_calib_cam_id
ON public.camera_calibrations (camera_id);

-- ------------------------------------------------------------------------------
-- 3. STATEWIDE EVENTS SCHEMA (ALPR, Kinematics, Anomaly & Threat Detection)
-- ------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.events (
    id BIGSERIAL PRIMARY KEY,
    event_id UUID UNIQUE NOT NULL,
    node_id VARCHAR(50) NOT NULL,
    camera_id VARCHAR(50) NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    confidence DOUBLE PRECISION,
    event_timestamp TIMESTAMPTZ NOT NULL,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    geom geometry(Point, 4326),
    frame_number BIGINT NOT NULL DEFAULT 0,
    inference_latency_ms DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    processing_status VARCHAR(20) NOT NULL DEFAULT 'unprocessed',
    processing_attempts INTEGER NOT NULL DEFAULT 0,
    processed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Spatial GIST Index for Event Trajectory Reconstruction
CREATE INDEX IF NOT EXISTS idx_events_geom_gist
ON public.events USING GIST (geom);

-- GIN Index for Ultra-Fast JSONB Deep Querying (alpr, kinematics, track_ids)
CREATE INDEX IF NOT EXISTS idx_events_metadata_gin
ON public.events USING GIN (metadata jsonb_path_ops);

-- B-Tree Index on License Plate Variant Keys
CREATE INDEX IF NOT EXISTS idx_events_plate_extracted
ON public.events ((UPPER(COALESCE(metadata->'alpr'->>'plate', metadata->>'license_plate', metadata->>'plate'))));

-- Composite Temporal Indexes for Cross-Camera Time Slicing
CREATE INDEX IF NOT EXISTS idx_events_camera_timestamp
ON public.events (camera_id, event_timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_events_type_timestamp
ON public.events (event_type, event_timestamp DESC);

-- ------------------------------------------------------------------------------
-- 4. eGujCop / VAHAN WATCHLIST SCHEMA (O(1) Memory Sync & Persistence)
-- ------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.egujcop_watchlist (
    id BIGSERIAL PRIMARY KEY,
    license_plate VARCHAR(30) UNIQUE NOT NULL,
    vehicle_make VARCHAR(100),
    vehicle_model VARCHAR(100),
    vehicle_color VARCHAR(50),
    owner_name VARCHAR(200),
    category VARCHAR(50) NOT NULL DEFAULT 'STOLEN',
    severity VARCHAR(20) NOT NULL DEFAULT 'CRITICAL',
    notes TEXT,
    flagged_by VARCHAR(100) DEFAULT 'eGujCop / CID Crime Gujarat',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_watchlist_plate
ON public.egujcop_watchlist (license_plate);

CREATE INDEX IF NOT EXISTS idx_watchlist_severity
ON public.egujcop_watchlist (severity);

-- ------------------------------------------------------------------------------
-- 5. OPTIMIZED SPATIOTEMPORAL TRAJECTORY STITCHING FUNCTION (RFC 7946 GeoJSON)
-- ------------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION get_vehicle_trajectory_geojson(
    p_license_plate TEXT,
    p_start_time TIMESTAMPTZ DEFAULT NULL,
    p_end_time TIMESTAMPTZ DEFAULT NULL
)
RETURNS JSONB
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    v_result JSONB;
BEGIN
    WITH sightings AS (
        SELECT 
            e.camera_id,
            COALESCE(c.name, 'Camera ' || e.camera_id) AS camera_name,
            COALESCE(c.city, e.metadata->>'city', 'Gujarat') AS city,
            COALESCE(e.longitude, c.longitude) AS longitude,
            COALESCE(e.latitude, c.latitude) AS latitude,
            COALESCE(e.geom, c.geom, ST_SetSRID(ST_MakePoint(COALESCE(e.longitude, c.longitude), COALESCE(e.latitude, c.latitude)), 4326)) AS geom,
            MIN(e.event_timestamp) AS first_seen,
            MAX(e.event_timestamp) AS last_seen,
            COUNT(e.id) AS detections_count,
            ROUND(AVG(e.confidence)::numeric, 4) AS avg_confidence,
            ROUND(MAX(COALESCE((e.metadata->'alpr'->>'plate_confidence')::float, e.confidence))::numeric, 4) AS best_confidence,
            COALESCE(c.source, e.metadata->>'source') AS stream_source
        FROM public.events e
        LEFT JOIN public.cameras c ON e.camera_id = c.camera_id
        WHERE e.event_type = 'ALPR_DETECTED'
          AND UPPER(COALESCE(e.metadata->'alpr'->>'plate', e.metadata->>'license_plate', e.metadata->>'plate')) = UPPER(p_license_plate)
          AND (p_start_time IS NULL OR e.event_timestamp >= p_start_time)
          AND (p_end_time IS NULL OR e.event_timestamp <= p_end_time)
          AND (e.latitude IS NOT NULL OR c.latitude IS NOT NULL)
          AND (e.longitude IS NOT NULL OR c.longitude IS NOT NULL)
        GROUP BY 
            e.camera_id, c.name, c.city, e.metadata->>'city', 
            e.longitude, c.longitude, e.latitude, c.latitude,
            e.geom, c.geom, c.source, e.metadata->>'source'
        ORDER BY MIN(e.event_timestamp) ASC
    ),
    point_features AS (
        SELECT 
            jsonb_build_object(
                'type', 'Feature',
                'geometry', ST_AsGeoJSON(geom)::jsonb,
                'properties', jsonb_build_object(
                    'checkpoint_order', row_number() OVER (ORDER BY first_seen ASC),
                    'camera_id', camera_id,
                    'camera_name', camera_name,
                    'city', city,
                    'first_seen', first_seen,
                    'last_seen', last_seen,
                    'detections_count', detections_count,
                    'avg_confidence', avg_confidence,
                    'best_confidence', best_confidence,
                    'stream_source', stream_source
                )
            ) AS feature,
            geom,
            first_seen,
            last_seen,
            detections_count
        FROM sightings
    ),
    line_feature AS (
        SELECT 
            CASE 
                WHEN COUNT(geom) >= 2 THEN
                    jsonb_build_object(
                        'type', 'Feature',
                        'geometry', ST_AsGeoJSON(ST_MakeLine(geom ORDER BY first_seen ASC))::jsonb,
                        'properties', jsonb_build_object(
                            'route_name', 'Traversed Route (' || UPPER(p_license_plate) || ')',
                            'checkpoint_count', COUNT(geom),
                            'total_distance_km', ROUND((ST_Length(ST_MakeLine(geom ORDER BY first_seen ASC)::geography) / 1000.0)::numeric, 2),
                            'start_time', MIN(first_seen),
                            'end_time', MAX(last_seen)
                        )
                    )
                ELSE NULL
            END AS feature
        FROM sightings
    )
    SELECT 
        jsonb_build_object(
            'type', 'FeatureCollection',
            'properties', jsonb_build_object(
                'license_plate', UPPER(p_license_plate),
                'total_sightings', COALESCE((SELECT SUM(detections_count) FROM sightings), 0),
                'unique_cameras', (SELECT COUNT(*) FROM sightings),
                'start_time', (SELECT MIN(first_seen) FROM sightings),
                'end_time', (SELECT MAX(last_seen) FROM sightings),
                'total_distance_km', COALESCE((SELECT ROUND((ST_Length(ST_MakeLine(geom ORDER BY first_seen ASC)::geography) / 1000.0)::numeric, 2) FROM sightings HAVING COUNT(geom) >= 2), 0)
            ),
            'features', (
                SELECT COALESCE(
                    jsonb_agg(feature) FILTER (WHERE feature IS NOT NULL),
                    '[]'::jsonb
                )
                FROM (
                    SELECT feature FROM point_features
                    UNION ALL
                    SELECT feature FROM line_feature WHERE feature IS NOT NULL
                ) combined
            )
        )
    INTO v_result;

    RETURN v_result;
END;
$$;

-- ------------------------------------------------------------------------------
-- 6. PRIMARY NODE INITIALIZATION (Regional Gujarat Edge Hubs)
-- ------------------------------------------------------------------------------

INSERT INTO public.edge_nodes (node_id, name, city, latitude, longitude, status)
VALUES
    ('NODE_AHM_01', 'Ahmedabad Metro Control Node', 'Ahmedabad', 23.0225, 72.5714, 'online'),
    ('NODE_GND_01', 'Gandhinagar Capital Surveillance Hub', 'Gandhinagar', 23.2156, 72.6369, 'online'),
    ('NODE_JUN_01', 'Junagadh District Surveillance Node', 'Junagadh', 21.5222, 70.4579, 'online'),
    ('NODE_SOM_01', 'Gir Somnath Coastal Command Hub', 'Gir Somnath', 20.9000, 70.3700, 'online'),
    ('NODE_RJK_01', 'Rajkot Central Traffic Command Node', 'Rajkot', 22.3039, 70.8022, 'online'),
    ('NODE_NAV_01', 'Navsari South Gujarat CCTV Node', 'Navsari', 20.9467, 72.9520, 'online'),
    ('NODE_PAT_01', 'Patan North Gujarat Surveillance Hub', 'Patan', 23.8493, 72.1266, 'online'),
    ('NODE_BAN_01', 'Banaskantha Border Surveillance Hub', 'Banaskantha', 24.1725, 72.4382, 'online'),
    ('NODE_KUT_01', 'Kutch Gandhidham Port Security Hub', 'Gandhidham', 23.0782, 70.1345, 'online')
ON CONFLICT (node_id) DO UPDATE 
SET name = EXCLUDED.name, city = EXCLUDED.city, latitude = EXCLUDED.latitude, longitude = EXCLUDED.longitude;

-- ------------------------------------------------------------------------------
-- 7. ALL 30 GUJARAT STATEWIDE CAMERAS (https://cctv.corp8.cloud)
-- ------------------------------------------------------------------------------

INSERT INTO public.cameras (camera_id, node_id, name, city, source, latitude, longitude, geom, enabled, status)
VALUES
    ('cam01', 'NODE_AHM_01', '01 Chiman bhai Bridge', 'Ahmedabad', 'https://cctv.corp8.cloud/cam01/index.m3u8', 23.0645, 72.5802, ST_SetSRID(ST_MakePoint(72.5802, 23.0645), 4326), true, 'online'),
    ('cam02', 'NODE_AHM_01', '02 Janpath', 'Ahmedabad', 'https://cctv.corp8.cloud/cam02/index.m3u8', 23.0556, 72.5739, ST_SetSRID(ST_MakePoint(72.5739, 23.0556), 4326), true, 'online'),
    ('cam03', 'NODE_AHM_01', '03 O.N.G.C. Office', 'Ahmedabad', 'https://cctv.corp8.cloud/cam03/index.m3u8', 23.1042, 72.5931, ST_SetSRID(ST_MakePoint(72.5931, 23.1042), 4326), true, 'online'),
    ('cam04', 'NODE_AHM_01', '04 Paldi Circle', 'Ahmedabad', 'https://cctv.corp8.cloud/cam04/index.m3u8', 23.0125, 72.5628, ST_SetSRID(ST_MakePoint(72.5628, 23.0125), 4326), true, 'online'),
    ('cam05', 'NODE_AHM_01', '05 Visat teen Rasta', 'Ahmedabad', 'https://cctv.corp8.cloud/cam05/index.m3u8', 23.0975, 72.5878, ST_SetSRID(ST_MakePoint(72.5878, 23.0975), 4326), true, 'online'),
    ('cam06', 'NODE_JUN_01', '06 Timbavadi gate-Junagadh', 'Junagadh', 'https://cctv.corp8.cloud/cam06/index.m3u8', 21.5034, 70.4412, ST_SetSRID(ST_MakePoint(70.4412, 21.5034), 4326), true, 'online'),
    ('cam07', 'NODE_SOM_01', '07 hero-showroom-gir-somnath', 'Gir Somnath', 'https://cctv.corp8.cloud/cam07/index.m3u8', 20.9125, 70.3688, ST_SetSRID(ST_MakePoint(70.3688, 20.9125), 4326), true, 'online'),
    ('cam08', 'NODE_JUN_01', '08 majewadi-gate-junagadh', 'Junagadh', 'https://cctv.corp8.cloud/cam08/index.m3u8', 21.5248, 70.4632, ST_SetSRID(ST_MakePoint(70.4632, 21.5248), 4326), true, 'online'),
    ('cam09', 'NODE_JUN_01', '09 new-bypass-near-by-circle-junagadh-2', 'Junagadh', 'https://cctv.corp8.cloud/cam09/index.m3u8', 21.5412, 70.4358, ST_SetSRID(ST_MakePoint(70.4358, 21.5412), 4326), true, 'online'),
    ('cam10', 'NODE_JUN_01', '10 char-chowk-road-2-junagadh', 'Junagadh', 'https://cctv.corp8.cloud/cam10/index.m3u8', 21.5186, 70.4574, ST_SetSRID(ST_MakePoint(70.4574, 21.5186), 4326), true, 'online'),
    ('cam11', 'NODE_JUN_01', '11 dolatpara-junagadh', 'Junagadh', 'https://cctv.corp8.cloud/cam11/index.m3u8', 21.5542, 70.4685, ST_SetSRID(ST_MakePoint(70.4685, 21.5542), 4326), true, 'online'),
    ('cam12', 'NODE_GND_01', '12 Tri Mandir Adalaj Tollnaka', 'Gandhinagar', 'https://cctv.corp8.cloud/cam12/index.m3u8', 23.1678, 72.5812, ST_SetSRID(ST_MakePoint(72.5812, 23.1678), 4326), true, 'online'),
    ('cam13', 'NODE_AHM_01', '13 CN Vidhyalaya', 'Ahmedabad', 'https://cctv.corp8.cloud/cam13/index.m3u8', 23.0232, 72.5488, ST_SetSRID(ST_MakePoint(72.5488, 23.0232), 4326), true, 'online'),
    ('cam14', 'NODE_AHM_01', '14 Delight RLVD', 'Ahmedabad', 'https://cctv.corp8.cloud/cam14/index.m3u8', 23.0118, 72.5085, ST_SetSRID(ST_MakePoint(72.5085, 23.0118), 4326), true, 'online'),
    ('cam15', 'NODE_AHM_01', '15 Suvidha park', 'Ahmedabad', 'https://cctv.corp8.cloud/cam15/index.m3u8', 23.0441, 72.5516, ST_SetSRID(ST_MakePoint(72.5516, 23.0441), 4326), true, 'online'),
    ('cam16', 'NODE_AHM_01', '16 Visat P2', 'Ahmedabad', 'https://cctv.corp8.cloud/cam16/index.m3u8', 23.0991, 72.5892, ST_SetSRID(ST_MakePoint(72.5892, 23.0991), 4326), true, 'online'),
    ('cam17', 'NODE_RJK_01', '17 Rajkot Bus Port CCTV', 'Rajkot', 'https://cctv.corp8.cloud/cam17/index.m3u8', 22.2965, 70.8012, ST_SetSRID(ST_MakePoint(70.8012, 22.2965), 4326), true, 'online'),
    ('cam18', 'NODE_RJK_01', '18 Rajkot CCTV', 'Rajkot', 'https://cctv.corp8.cloud/cam18/index.m3u8', 22.3028, 70.8025, ST_SetSRID(ST_MakePoint(70.8025, 22.3028), 4326), true, 'online'),
    ('cam19', 'NODE_NAV_01', '19 KHAPARIA GRAM PANCHAYAT , TALUKA GANDEVI, DISTRICT NAVSARI', 'Navsari', 'https://cctv.corp8.cloud/cam19/index.m3u8', 20.8142, 72.9856, ST_SetSRID(ST_MakePoint(72.9856, 20.8142), 4326), true, 'online'),
    ('cam20', 'NODE_AHM_01', '20 Mohanpura', 'Ahmedabad', 'https://cctv.corp8.cloud/cam20/index.m3u8', 23.0368, 72.6042, ST_SetSRID(ST_MakePoint(72.6042, 23.0368), 4326), true, 'online'),
    ('cam21', 'NODE_PAT_01', '23 Patan Dethali Char Rasta', 'Patan', 'https://cctv.corp8.cloud/cam21/index.m3u8', 23.8375, 72.1284, ST_SetSRID(ST_MakePoint(72.1284, 23.8375), 4326), true, 'online'),
    ('cam22', 'NODE_BAN_01', '28 BK Mervada tran Rasta', 'Banaskantha', 'https://cctv.corp8.cloud/cam22/index.m3u8', 24.1725, 72.4382, ST_SetSRID(ST_MakePoint(72.4382, 24.1725), 4326), true, 'online'),
    ('cam23', 'NODE_NAV_01', '30 kheram', 'Navsari', 'https://cctv.corp8.cloud/cam23/index.m3u8', 20.7385, 73.0512, ST_SetSRID(ST_MakePoint(73.0512, 20.7385), 4326), true, 'online'),
    ('cam24', 'NODE_GND_01', '33 dehgam', 'Gandhinagar', 'https://cctv.corp8.cloud/cam24/index.m3u8', 23.1682, 72.8125, ST_SetSRID(ST_MakePoint(72.8125, 23.1682), 4326), true, 'online'),
    ('cam25', 'NODE_NAV_01', '34 dhanori', 'Navsari', 'https://cctv.corp8.cloud/cam25/index.m3u8', 20.8325, 72.9715, ST_SetSRID(ST_MakePoint(72.9715, 20.8325), 4326), true, 'online'),
    ('cam26', 'NODE_NAV_01', '35 TANKAL', 'Navsari', 'https://cctv.corp8.cloud/cam26/index.m3u8', 20.7612, 73.0845, ST_SetSRID(ST_MakePoint(73.0845, 20.7612), 4326), true, 'online'),
    ('cam27', 'NODE_NAV_01', '36 bilimora', 'Navsari', 'https://cctv.corp8.cloud/cam27/index.m3u8', 20.7628, 72.9642, ST_SetSRID(ST_MakePoint(72.9642, 20.7628), 4326), true, 'online'),
    ('cam28', 'NODE_NAV_01', '37 bilimora', 'Navsari', 'https://cctv.corp8.cloud/cam28/index.m3u8', 20.7584, 72.9718, ST_SetSRID(ST_MakePoint(72.9718, 20.7584), 4326), true, 'online'),
    ('cam29', 'NODE_NAV_01', '38 bilimora', 'Navsari', 'https://cctv.corp8.cloud/cam29/index.m3u8', 20.7512, 72.9585, ST_SetSRID(ST_MakePoint(72.9585, 20.7512), 4326), true, 'online'),
    ('cam30', 'NODE_KUT_01', 'Gandhidham Rambaugh p2', 'Gandhidham', 'https://cctv.corp8.cloud/cam30/index.m3u8', 23.0782, 70.1345, ST_SetSRID(ST_MakePoint(70.1345, 23.0782), 4326), true, 'online')
ON CONFLICT (camera_id) DO UPDATE
SET node_id = EXCLUDED.node_id,
    name = EXCLUDED.name,
    city = EXCLUDED.city,
    source = EXCLUDED.source,
    latitude = EXCLUDED.latitude,
    longitude = EXCLUDED.longitude,
    geom = EXCLUDED.geom,
    enabled = true,
    status = 'online',
    updated_at = NOW();

