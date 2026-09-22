-- =========================================================
-- SENTINEL: PostGIS, Geospatial Trajectories & eGujCop Watchlist
-- Phase 2 / Hackathon Production Migration
-- =========================================================

CREATE EXTENSION IF NOT EXISTS postgis;

-- ---------------------------------------------------------
-- 1. CAMERAS: Geospatial Columns & City Attribute
-- ---------------------------------------------------------

ALTER TABLE public.cameras
ADD COLUMN IF NOT EXISTS city VARCHAR(100);

ALTER TABLE public.cameras
ADD COLUMN IF NOT EXISTS geom geometry(Point, 4326);

UPDATE public.cameras
SET geom = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)
WHERE geom IS NULL AND longitude IS NOT NULL AND latitude IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_cameras_geom
ON public.cameras USING GIST (geom);

-- ---------------------------------------------------------
-- 2. EVENTS: Geospatial Columns & Plate Indexing
-- ---------------------------------------------------------

ALTER TABLE public.events
ADD COLUMN IF NOT EXISTS geom geometry(Point, 4326);

UPDATE public.events
SET geom = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)
WHERE geom IS NULL AND longitude IS NOT NULL AND latitude IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_events_geom
ON public.events USING GIST (geom);

CREATE INDEX IF NOT EXISTS idx_events_alpr_plate
ON public.events ((COALESCE(metadata->'alpr'->>'plate', metadata->>'license_plate', metadata->>'plate')));

-- ---------------------------------------------------------
-- 3. eGujCop WATCHLIST TABLE
-- ---------------------------------------------------------

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

-- ---------------------------------------------------------
-- Schema tables, extensions, and spatial indexes complete.
-- Operational tables are initialized cleanly with zero mock seeds.
-- ---------------------------------------------------------
