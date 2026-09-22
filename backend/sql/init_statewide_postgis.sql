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
-- 6. PRIMARY NODE INITIALIZATION (Zero Mock Seeds)
-- ------------------------------------------------------------------------------

INSERT INTO public.edge_nodes (node_id, name, city, latitude, longitude, status)
VALUES
    ('NODE_AHM_01', 'Ahmedabad Metro Control Node', 'Ahmedabad', 23.0225, 72.5714, 'online')
ON CONFLICT (node_id) DO NOTHING;
