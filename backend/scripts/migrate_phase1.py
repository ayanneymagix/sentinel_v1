import asyncio
import os
import asyncpg

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:admin@127.0.0.1:5432/sentinel")

async def run_migration():
    print(f"[+] Connecting to PostgreSQL at {DATABASE_URL}...")
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        print("[+] Checking if public.cameras table exists...")
        events_exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = 'events'
            );
        """)

        exts = [r["name"] for r in await conn.fetch("SELECT name FROM pg_available_extensions")]
        has_postgis = "postgis" in exts
        print(f"[+] PostGIS available on PostgreSQL server: {has_postgis}")

        if not events_exists:
            print("[+] Database tables do not exist completely. Initializing schema from init_statewide_postgis.sql...")
            sql_path = os.path.join(os.path.dirname(__file__), "..", "sql", "init_statewide_postgis.sql")
            with open(sql_path, "r", encoding="utf-8") as f:
                sql_content = f.read()
            if not has_postgis:
                print("[!] PostGIS is not installed in this PostgreSQL instance. Sanitizing schema to use native spatial/point fallbacks...")
                sql_content = sql_content.replace("CREATE EXTENSION IF NOT EXISTS postgis;", "-- PostGIS not installed on host, using point coordinates")
                sql_content = sql_content.replace("geom geometry(Point, 4326),", "geom TEXT,")
                import re
                sql_content = re.sub(r"CREATE INDEX IF NOT EXISTS \w+_geom_gist\s+ON public\.\w+\s+USING GIST\s*\(geom\);", "-- GIST index skipped", sql_content)
                sql_content = re.sub(r"ST_SetSRID\(ST_MakePoint\([^)]+\),\s*4326\)", "NULL", sql_content)
                sql_content = sql_content.replace("\r\n", "\n")
                func_start = sql_content.find("CREATE OR REPLACE FUNCTION get_vehicle_trajectory_geojson")
                if func_start != -1:
                    func_end = sql_content.find("END;\n$$;", func_start)
                    if func_end != -1:
                        func_end += len("END;\n$$;")
                        sql_content = sql_content[:func_start] + "-- Function get_vehicle_trajectory_geojson requires PostGIS\n" + sql_content[func_end:]
            stmts = [s.strip() for s in sql_content.split(";") if s.strip()]
            for idx, stmt in enumerate(stmts):
                try:
                    await conn.execute(stmt)
                except Exception as ex:
                    print(f"[!] Error on statement #{idx}:\n{stmt}\nError: {ex}")
                    raise ex
            print("[+] init_statewide_postgis.sql executed successfully!")

        print("[+] Applying Phase 1 schema changes and data updates...")
        async with conn.transaction():
            print("[+] Altering public.cameras to allow NULL latitude and longitude...")
            await conn.execute("""
                ALTER TABLE public.cameras ALTER COLUMN latitude DROP NOT NULL;
                ALTER TABLE public.cameras ALTER COLUMN longitude DROP NOT NULL;
            """)

            print("[+] Altering public.events to allow NULL confidence...")
            await conn.execute("""
                ALTER TABLE public.events ALTER COLUMN confidence DROP NOT NULL;
            """)

            print("[+] Creating public.camera_calibrations table if not exists...")
            await conn.execute("""
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
            """)

            print("[+] Upserting registered recorded CCTV test clips into public.cameras...")
            await conn.execute("""
                INSERT INTO public.cameras (camera_id, node_id, name, city, source, latitude, longitude, geom, enabled, status)
                VALUES
                    ('CAM_CCTV_0', 'NODE_AHM_01', 'CCTV Sector 1 (mycctv.mp4)', NULL, './media/mycctv.mp4', NULL, NULL, NULL, true, 'online'),
                    ('CAM_CCTV_1', 'NODE_AHM_01', 'CCTV Sector 2 (mycctv1.mp4)', NULL, './media/mycctv1.mp4', NULL, NULL, NULL, true, 'online'),
                    ('CAM_CCTV_2', 'NODE_AHM_01', 'CCTV Sector 3 (mycctv2.mp4)', NULL, './media/mycctv2.mp4', NULL, NULL, NULL, true, 'online'),
                    ('CAM_CCTV_3', 'NODE_AHM_01', 'CCTV Sector 4 (mycctv3.mp4)', NULL, './media/mycctv3.mp4', NULL, NULL, NULL, true, 'online'),
                    ('CAM_CCTV_4', 'NODE_AHM_01', 'CCTV Sector 5 (mycctv4.mp4)', NULL, './media/mycctv4.mp4', NULL, NULL, NULL, true, 'online')
                ON CONFLICT (camera_id) DO UPDATE
                SET source = EXCLUDED.source,
                    name = EXCLUDED.name,
                    status = 'online';
            """)

            print("[+] Purging synthetic GJ01AB1234 demonstration events from operational public.events...")
            res = await conn.execute("""
                DELETE FROM public.events 
                WHERE event_id IN (
                    'a0000001-0000-0000-0000-000000000001',
                    'a0000001-0000-0000-0000-000000000002',
                    'a0000001-0000-0000-0000-000000000003',
                    'a0000001-0000-0000-0000-000000000004',
                    'a0000001-0000-0000-0000-000000000005',
                    'a0000001-0000-0000-0000-000000000006'
                );
            """)
            print(f"[+] Purge result: {res}")

        print("[SUCCESS] Phase 1 database migration executed cleanly!")
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(run_migration())
