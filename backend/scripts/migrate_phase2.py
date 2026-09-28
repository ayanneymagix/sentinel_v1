import os
import psycopg2

def run_migration():
    print("=== RUNNING MIGRATION 006: PHASE 2 VMS SOURCES & MODEL 2 ===")
    conn = psycopg2.connect(
        dbname=os.getenv("POSTGRES_DB", "sentinel"),
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASSWORD", "admin"),
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5432")
    )
    conn.autocommit = False
    cur = conn.cursor()

    sql_path = os.path.join(os.path.dirname(__file__), "..", "sql", "006_vms_sources_and_model2.sql")
    with open(sql_path, "r", encoding="utf-8") as f:
        sql = f.read()

    try:
        cur.execute(sql)
        conn.commit()
        print("Migration 006 executed successfully!")

        # Verify tables and rows
        cur.execute("SELECT source_id, source_name, source_type, status, health_status FROM public.vms_sources;")
        sources = cur.fetchall()
        print(f"Sources in public.vms_sources: {len(sources)}")
        for s in sources:
            print(f"  [{s[0]}] {s[1]} ({s[2]}) -> Status: {s[3]}, Health: {s[4]}")

        cur.execute("SELECT count(*) FROM public.cctv_assets WHERE source_id = 'SRC_GUJ_GATEWAY';")
        print(f"Cameras associated with SRC_GUJ_GATEWAY: {cur.fetchone()[0]}")

        cur.execute("SELECT count(*) FROM public.camera_analytics_config;")
        print(f"Cameras with Selective Analytics config: {cur.fetchone()[0]}")

    except Exception as e:
        conn.rollback()
        print("Migration failed:", e)
        raise
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    run_migration()
