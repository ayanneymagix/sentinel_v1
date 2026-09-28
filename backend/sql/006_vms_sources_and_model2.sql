-- ==============================================================================
-- SENTINEL PHASE 2 — MODEL 2: UNIFIED VIEWING + SELECTIVE ANALYTICS
-- Migration 006: VMS Sources, Source Adapters & Selective Analytics Configuration
-- ==============================================================================

-- 1. VMS Sources Table (Independent CCTV / VMS Source Systems)
CREATE TABLE IF NOT EXISTS public.vms_sources (
    id SERIAL PRIMARY KEY,
    source_id VARCHAR(64) UNIQUE NOT NULL,
    source_name VARCHAR(255) NOT NULL,
    source_type VARCHAR(64) NOT NULL, -- GATEWAY_CATALOGUE, ONVIF, RTSP, VMS_API, VENDOR_SDK, WEBRTC, HLS
    owner_department_id INTEGER REFERENCES public.departments(id) ON DELETE SET NULL,
    connection_type VARCHAR(64) NOT NULL, -- HTTP_REST, RTSP_TCP, ONVIF_SOAP, WEBSOCKET, SDK
    endpoint_url TEXT NOT NULL,
    credentials_ref VARCHAR(255), -- Secure secret reference key, NEVER exposed to client
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE', -- ACTIVE, INACTIVE, NOT_CONFIGURED, ERROR
    health_status VARCHAR(32) NOT NULL DEFAULT 'HEALTHY', -- HEALTHY, DEGRADED, OFFLINE, UNKNOWN
    capabilities JSONB NOT NULL DEFAULT '{"hls": true, "webrtc": true, "rtsp": true, "ptz": false, "discovery": true}'::jsonb,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_health_check TIMESTAMPTZ,
    last_sync TIMESTAMPTZ,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by VARCHAR(128) DEFAULT 'SYSTEM'
);

CREATE INDEX IF NOT EXISTS idx_vms_sources_type ON public.vms_sources(source_type);
CREATE INDEX IF NOT EXISTS idx_vms_sources_status ON public.vms_sources(status);
CREATE INDEX IF NOT EXISTS idx_vms_sources_health ON public.vms_sources(health_status);

-- 2. Extend public.cctv_assets with source_id (preserving existing records)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' AND table_name = 'cctv_assets' AND column_name = 'source_id'
    ) THEN
        ALTER TABLE public.cctv_assets 
        ADD COLUMN source_id VARCHAR(64) REFERENCES public.vms_sources(source_id) ON DELETE SET NULL;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_cctv_assets_source ON public.cctv_assets(source_id);

-- 3. Extend public.cameras with source_id
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' AND table_name = 'cameras' AND column_name = 'source_id'
    ) THEN
        ALTER TABLE public.cameras 
        ADD COLUMN source_id VARCHAR(64);
    END IF;
END $$;

-- 4. Selective Analytics Configuration Table
CREATE TABLE IF NOT EXISTS public.camera_analytics_config (
    id SERIAL PRIMARY KEY,
    camera_id VARCHAR(64) UNIQUE NOT NULL REFERENCES public.cctv_assets(camera_id) ON DELETE CASCADE,
    source_id VARCHAR(64) REFERENCES public.vms_sources(source_id) ON DELETE CASCADE,
    profile_name VARCHAR(64) NOT NULL DEFAULT 'STANDARD_SURVEILLANCE',
    enabled_analytics TEXT[] NOT NULL DEFAULT ARRAY['OBJECT_DETECTION', 'TRACKING']::TEXT[],
    confidence_threshold DOUBLE PRECISION NOT NULL DEFAULT 0.50,
    sampling_fps DOUBLE PRECISION NOT NULL DEFAULT 5.0,
    anpr_enabled BOOLEAN NOT NULL DEFAULT false,
    vehicle_counting_enabled BOOLEAN NOT NULL DEFAULT false,
    person_counting_enabled BOOLEAN NOT NULL DEFAULT false,
    behavior_analysis_enabled BOOLEAN NOT NULL DEFAULT false,
    reid_enabled BOOLEAN NOT NULL DEFAULT false,
    schedule JSONB DEFAULT '{"active_hours": "00:00-23:59", "days": ["MON","TUE","WED","THU","FRI","SAT","SUN"]}'::jsonb,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by VARCHAR(128) DEFAULT 'SYSTEM'
);

CREATE INDEX IF NOT EXISTS idx_analytics_config_cam ON public.camera_analytics_config(camera_id);
CREATE INDEX IF NOT EXISTS idx_analytics_config_active ON public.camera_analytics_config(is_active);

-- 5. Seed Authoritative Source A: Real Gujarat Camera Gateway
INSERT INTO public.vms_sources (
    source_id, source_name, source_type, owner_department_id, connection_type,
    endpoint_url, credentials_ref, status, health_status, capabilities, config
) VALUES (
    'SRC_GUJ_GATEWAY',
    'Gujarat Police Dynamic Camera Gateway',
    'GATEWAY_CATALOGUE',
    1, -- State Police Command Center
    'HTTP_REST',
    'http://cctv.corp8.cloud/api/ingest',
    'ENV_CCTV_CREDENTIALS',
    'ACTIVE',
    'HEALTHY',
    '{"hls": true, "webrtc": true, "rtsp": true, "ptz": false, "discovery": true, "analytics_ingestion": true}'::jsonb,
    '{"poll_interval_seconds": 30, "timeout_seconds": 10, "transport": "TCP"}'::jsonb
)
ON CONFLICT (source_id) DO UPDATE
SET source_name = EXCLUDED.source_name,
    endpoint_url = EXCLUDED.endpoint_url,
    status = EXCLUDED.status,
    health_status = EXCLUDED.health_status,
    updated_at = NOW();

-- 6. Seed Architecture Source B: Independent VMS / ONVIF Source (Explicitly Marked NOT_CONFIGURED)
INSERT INTO public.vms_sources (
    source_id, source_name, source_type, owner_department_id, connection_type,
    endpoint_url, credentials_ref, status, health_status, capabilities, config
) VALUES (
    'SRC_INDEP_VMS_02',
    'Departmental VMS Source B (Milestone / ONVIF)',
    'ONVIF',
    2, -- Ahmedabad Commissionerate
    'ONVIF_SOAP',
    'http://vms-source-b.internal:80/onvif/device_service',
    'ENV_VMS_B_CREDENTIALS',
    'NOT_CONFIGURED',
    'UNKNOWN',
    '{"hls": true, "webrtc": false, "rtsp": true, "ptz": true, "discovery": false, "analytics_ingestion": false}'::jsonb,
    '{"notes": "Independent Departmental VMS. Requires on-premise endpoint and ONVIF WS-UsernameToken credentials. Read-only consumption."}'::jsonb
)
ON CONFLICT (source_id) DO UPDATE
SET source_name = EXCLUDED.source_name,
    status = EXCLUDED.status,
    health_status = EXCLUDED.health_status,
    updated_at = NOW();

-- 7. Associate all existing 30 Gujarat cameras with the Gujarat Gateway source
UPDATE public.cctv_assets 
SET source_id = 'SRC_GUJ_GATEWAY' 
WHERE source_id IS NULL;

UPDATE public.cameras 
SET source_id = 'SRC_GUJ_GATEWAY' 
WHERE source_id IS NULL;

-- 8. Seed default analytics configurations for cameras based on purpose
INSERT INTO public.camera_analytics_config (
    camera_id, source_id, profile_name, enabled_analytics, confidence_threshold, sampling_fps, anpr_enabled
)
SELECT 
    camera_id, 
    'SRC_GUJ_GATEWAY',
    CASE 
        WHEN camera_id IN ('cam01', 'cam02', 'cam05', 'cam10', 'cam15', 'cam20') THEN 'HIGH_PRIORITY_ANPR'
        WHEN camera_type = 'PTZ' THEN 'PTZ_TRACKING'
        ELSE 'STANDARD_SURVEILLANCE'
    END,
    CASE 
        WHEN camera_id IN ('cam01', 'cam02', 'cam05', 'cam10', 'cam15', 'cam20') THEN ARRAY['OBJECT_DETECTION', 'TRACKING', 'ANPR']::TEXT[]
        ELSE ARRAY['OBJECT_DETECTION', 'TRACKING']::TEXT[]
    END,
    0.50,
    CASE 
        WHEN camera_id IN ('cam01', 'cam02', 'cam05') THEN 10.0
        ELSE 5.0
    END,
    CASE 
        WHEN camera_id IN ('cam01', 'cam02', 'cam05', 'cam10', 'cam15', 'cam20') THEN true
        ELSE false
    END
FROM public.cctv_assets
ON CONFLICT (camera_id) DO NOTHING;
