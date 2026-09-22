import json
import logging
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from app.database.postgres import postgres

try:
    from sentinel_edge.alpr.validator import PlateValidator
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "edge"))
    from sentinel_edge.alpr.validator import PlateValidator

logger = logging.getLogger("sentinel.api.tracking")

router = APIRouter(prefix="/tracking", tags=["Tracking & Route Reconstruction"])


def haversine_distance_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Calculate great-circle distance between two points on the Earth."""
    r = 6371.0  # Earth radius in kilometers
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(r * c, 2)


@router.get("/route/{license_plate:path}")
async def get_vehicle_route(license_plate: str):
    """
    Reconstruct chronological cross-camera route trajectory for a vehicle registration number,
    global target ID (SENTINEL-*), or local track ID.
    
    Returns an RFC 7946 GeoJSON FeatureCollection with Point checkpoint features and
    a LineString trajectory feature.
    """
    if postgres.pool is None:
        raise HTTPException(status_code=503, detail="PostgreSQL is unavailable")

    raw_id = license_plate.strip()
    norm_id = raw_id.upper()

    # Determine if identifier is numeric track ID or contains one
    track_id_int: Optional[int] = int(raw_id) if raw_id.isdigit() else None
    if not track_id_int and ("SENTINEL-" in norm_id or "-TR-" in norm_id or "TRACK-" in norm_id or "TR-" in norm_id):
        parts = norm_id.replace("TRACK-", "").replace("TR-", "-").split("-")
        for p in reversed(parts):
            if p.isdigit():
                try:
                    track_id_int = int(p)
                    break
                except ValueError:
                    pass
    track_id_str: Optional[str] = str(track_id_int) if track_id_int is not None else (raw_id if len(raw_id) <= 10 else None)

    # RTO jurisdiction analysis for Indian vehicle registrations
    rto_info = PlateValidator.get_rto_jurisdiction(norm_id) if len(norm_id) >= 4 else None

    query_sightings = """
        WITH sightings AS (
            SELECT 
                e.camera_id,
                COALESCE(c.name, 'Camera ' || e.camera_id) AS camera_name,
                COALESCE(c.city, e.metadata->>'city', 'Gujarat') AS city,
                COALESCE(e.longitude, c.longitude) AS longitude,
                COALESCE(e.latitude, c.latitude) AS latitude,
                MIN(e.event_timestamp) AS first_seen,
                MAX(e.event_timestamp) AS last_seen,
                COUNT(e.id) AS detections_count,
                ROUND(AVG(e.confidence)::numeric, 4) AS avg_confidence,
                ROUND(MAX(COALESCE((e.metadata->'alpr'->>'plate_confidence')::float, e.confidence))::numeric, 4) AS best_confidence,
                COALESCE(c.source, e.metadata->>'source') AS stream_source,
                MODE() WITHIN GROUP (ORDER BY COALESCE(e.metadata->'alpr'->>'plate', e.metadata->>'license_plate', e.metadata->>'plate')) AS detected_plate
            FROM public.events e
            LEFT JOIN public.cameras c ON e.camera_id = c.camera_id
            WHERE (
                -- Plate match
                UPPER(COALESCE(e.metadata->'alpr'->>'plate', e.metadata->>'license_plate', e.metadata->>'plate')) = $1
                OR ($1 != '' AND e.metadata->'detections' @> jsonb_build_array(jsonb_build_object('plate', $1)))
                -- Track ID match
                OR ($2::int IS NOT NULL AND e.metadata->'detections' @> jsonb_build_array(jsonb_build_object('track_id', $2::int)))
                OR ($3::text IS NOT NULL AND (e.metadata->'behavior'->>'track_id' = $3 OR e.metadata->>'track_id' = $3))
                -- Global ID match
                OR e.metadata->'detections' @> jsonb_build_array(jsonb_build_object('global_id', $1))
                OR e.metadata->>'global_id' = $1
            )
            AND (e.latitude IS NOT NULL OR c.latitude IS NOT NULL)
            AND (e.longitude IS NOT NULL OR c.longitude IS NOT NULL)
            GROUP BY 
                e.camera_id, 
                c.name, 
                c.city, 
                e.metadata->>'city', 
                e.longitude, 
                c.longitude, 
                e.latitude, 
                c.latitude,
                c.source,
                e.metadata->>'source'
            ORDER BY MIN(e.event_timestamp) ASC
        )
        SELECT 
            camera_id,
            camera_name,
            city,
            longitude,
            latitude,
            first_seen,
            last_seen,
            detections_count,
            avg_confidence,
            best_confidence,
            stream_source,
            detected_plate
        FROM sightings;
    """

    query_watchlist = """
        SELECT 
            license_plate,
            vehicle_make,
            vehicle_model,
            vehicle_color,
            owner_name,
            category,
            severity,
            notes,
            flagged_by
        FROM public.egujcop_watchlist
        WHERE UPPER(license_plate) = UPPER($1)
           OR ($2::text IS NOT NULL AND UPPER(license_plate) = UPPER($2));
    """

    async with postgres.pool.acquire() as conn:
        sightings_rows = await conn.fetch(query_sightings, norm_id, track_id_int, track_id_str)
        
        # Check detected plate from sightings if primary identifier wasn't a plate
        detected_target_plate = None
        for s in sightings_rows:
            if s["detected_plate"]:
                detected_target_plate = s["detected_plate"].strip().upper()
                break

        watchlist_row = await conn.fetchrow(query_watchlist, norm_id, detected_target_plate)

    watchlist_info = None
    if watchlist_row:
        watchlist_info = {
            "license_plate": watchlist_row["license_plate"],
            "vehicle_make": watchlist_row["vehicle_make"],
            "vehicle_model": watchlist_row["vehicle_model"],
            "vehicle_color": watchlist_row["vehicle_color"],
            "owner_name": watchlist_row["owner_name"],
            "category": watchlist_row["category"],
            "severity": watchlist_row["severity"],
            "notes": watchlist_row["notes"],
            "flagged_by": watchlist_row["flagged_by"],
        }

    # If target plate was detected from track, update RTO jurisdiction if not already set
    if not rto_info and detected_target_plate and len(detected_target_plate) >= 4:
        rto_info = PlateValidator.get_rto_jurisdiction(detected_target_plate)

    effective_plate = detected_target_plate or (norm_id if not raw_id.isdigit() else f"TRACK-{raw_id}")

    if not sightings_rows:
        return {
            "type": "FeatureCollection",
            "properties": {
                "license_plate": effective_plate,
                "target_identifier": raw_id,
                "rto_jurisdiction": rto_info,
                "total_sightings": 0,
                "unique_cameras": 0,
                "is_watchlist_match": watchlist_info is not None,
                "watchlist_details": watchlist_info,
                "message": f"No sightings detected for target '{raw_id}'",
            },
            "features": [],
        }

    features = []
    coordinates = []
    segments = []
    total_detections = 0
    total_distance_km = 0.0

    prev_row = None

    for idx, row in enumerate(sightings_rows, start=1):
        lon = float(row["longitude"])
        lat = float(row["latitude"])
        coordinates.append([lon, lat])

        segment_speed_kmh = 0.0
        segment_transit_minutes = 0.0
        segment_dist_km = 0.0
        prev_camera_id = None

        if prev_row is not None:
            prev_lon = float(prev_row["longitude"])
            prev_lat = float(prev_row["latitude"])
            segment_dist_km = haversine_distance_km(prev_lon, prev_lat, lon, lat)
            total_distance_km += segment_dist_km

            prev_time = prev_row["last_seen"] or prev_row["first_seen"]
            curr_time = row["first_seen"] or row["last_seen"]

            if prev_time and curr_time:
                dt_seconds = max(0.0, (curr_time - prev_time).total_seconds())
                segment_transit_minutes = round(dt_seconds / 60.0, 1)
                if dt_seconds > 5.0 and segment_dist_km > 0.05:
                    segment_speed_kmh = round((segment_dist_km / (dt_seconds / 3600.0)), 1)
                elif segment_dist_km <= 0.05:
                    segment_speed_kmh = 0.0

            prev_camera_id = prev_row["camera_id"]
            segments.append({
                "from_camera": prev_camera_id,
                "to_camera": row["camera_id"],
                "from_city": prev_row["city"],
                "to_city": row["city"],
                "distance_km": segment_dist_km,
                "transit_minutes": segment_transit_minutes,
                "avg_speed_kmh": segment_speed_kmh,
            })

        prev_row = row

        detections = int(row["detections_count"])
        total_detections += detections

        point_feature = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [lon, lat],
            },
            "properties": {
                "checkpoint_order": idx,
                "camera_id": row["camera_id"],
                "camera_name": row["camera_name"],
                "city": row["city"],
                "first_seen": row["first_seen"].isoformat() if row["first_seen"] else None,
                "last_seen": row["last_seen"].isoformat() if row["last_seen"] else None,
                "detections_count": detections,
                "avg_confidence": float(row["avg_confidence"]),
                "best_confidence": float(row["best_confidence"]),
                "stream_source": row["stream_source"],
                "is_threat": watchlist_info is not None,
                "prev_camera_id": prev_camera_id,
                "distance_from_prev_km": segment_dist_km,
                "transit_time_from_prev_minutes": segment_transit_minutes,
                "segment_speed_kmh": segment_speed_kmh,
            },
        }
        features.append(point_feature)

    start_time = sightings_rows[0]["first_seen"]
    end_time = sightings_rows[-1]["last_seen"]
    transit_duration_minutes = 0.0
    if start_time and end_time:
        transit_duration_minutes = round(
            max(0.0, (end_time - start_time).total_seconds() / 60.0), 1
        )

    overall_avg_speed = 0.0
    if transit_duration_minutes > 0.05 and total_distance_km > 0.05:
        overall_avg_speed = round(total_distance_km / (transit_duration_minutes / 60.0), 1)

    # Add connecting trajectory line if more than 1 point
    if len(coordinates) >= 2:
        line_feature = {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": coordinates,
            },
            "properties": {
                "route_name": f"Traversed Route ({effective_plate})",
                "checkpoint_count": len(coordinates),
                "total_distance_km": round(total_distance_km, 2),
                "start_time": start_time.isoformat() if start_time else None,
                "end_time": end_time.isoformat() if end_time else None,
                "duration_minutes": transit_duration_minutes,
                "average_speed_kmh": overall_avg_speed,
                "segments": segments,
                "is_threat": watchlist_info is not None,
            },
        }
        features.append(line_feature)

    return {
        "type": "FeatureCollection",
        "properties": {
            "license_plate": effective_plate,
            "target_identifier": raw_id,
            "rto_jurisdiction": rto_info,
            "total_sightings": total_detections,
            "unique_cameras": len(sightings_rows),
            "start_time": start_time.isoformat() if start_time else None,
            "end_time": end_time.isoformat() if end_time else None,
            "transit_duration_minutes": transit_duration_minutes,
            "total_distance_km": round(total_distance_km, 2),
            "average_speed_kmh": overall_avg_speed,
            "segments_count": len(segments),
            "is_watchlist_match": watchlist_info is not None,
            "watchlist_details": watchlist_info,
        },
        "features": features,
    }


@router.get("/plates")
async def get_tracked_plates(limit: int = Query(default=50, ge=1, le=200)):
    """
    List recently tracked vehicle registration numbers with sighting counts, RTO jurisdiction, and watchlist status.
    """
    if postgres.pool is None:
        raise HTTPException(status_code=503, detail="PostgreSQL is unavailable")

    query = """
        SELECT 
            UPPER(COALESCE(e.metadata->'alpr'->>'plate', e.metadata->>'license_plate', e.metadata->>'plate')) AS plate,
            MAX(e.event_timestamp) AS last_seen,
            MIN(e.event_timestamp) AS first_seen,
            COUNT(DISTINCT e.camera_id) AS camera_count,
            COUNT(e.id) AS total_detections,
            MAX(COALESCE(c.city, e.metadata->>'city', 'Gujarat')) AS last_city,
            w.category AS watchlist_category,
            w.severity AS watchlist_severity,
            w.vehicle_make,
            w.vehicle_model,
            w.owner_name
        FROM public.events e
        LEFT JOIN public.cameras c ON e.camera_id = c.camera_id
        LEFT JOIN public.egujcop_watchlist w 
            ON UPPER(COALESCE(e.metadata->'alpr'->>'plate', e.metadata->>'license_plate', e.metadata->>'plate')) = UPPER(w.license_plate)
        WHERE COALESCE(e.metadata->'alpr'->>'plate', e.metadata->>'license_plate', e.metadata->>'plate') IS NOT NULL
        GROUP BY 
            UPPER(COALESCE(e.metadata->'alpr'->>'plate', e.metadata->>'license_plate', e.metadata->>'plate')),
            w.category,
            w.severity,
            w.vehicle_make,
            w.vehicle_model,
            w.owner_name
        ORDER BY MAX(e.event_timestamp) DESC
        LIMIT $1;
    """

    async with postgres.pool.acquire() as conn:
        rows = await conn.fetch(query, limit)

    results = []
    for r in rows:
        plate_str = r["plate"]
        rto = PlateValidator.get_rto_jurisdiction(plate_str) if plate_str and len(plate_str) >= 4 else None
        results.append(
            {
                "plate": plate_str,
                "rto_jurisdiction": rto,
                "last_seen": r["last_seen"].isoformat() if r["last_seen"] else None,
                "first_seen": r["first_seen"].isoformat() if r["first_seen"] else None,
                "camera_count": int(r["camera_count"]),
                "total_detections": int(r["total_detections"]),
                "last_city": r["last_city"],
                "is_watchlist_match": r["watchlist_category"] is not None,
                "watchlist_category": r["watchlist_category"],
                "watchlist_severity": r["watchlist_severity"],
                "vehicle_make": r["vehicle_make"],
                "vehicle_model": r["vehicle_model"],
                "owner_name": r["owner_name"],
            }
        )

    return {"count": len(results), "plates": results}


@router.get("/targets")
async def get_tracked_targets(limit: int = Query(default=50, ge=1, le=200)):
    """
    List recently tracked computer vision targets (unplated and plated) across the surveillance grid.
    """
    if postgres.pool is None:
        raise HTTPException(status_code=503, detail="PostgreSQL is unavailable")

    query = """
        WITH recent_events AS (
            SELECT e.camera_id, e.event_timestamp, e.metadata
            FROM public.events e
            ORDER BY e.event_timestamp DESC
            LIMIT 500
        )
        SELECT 
            d.value->>'track_id' AS track_id,
            d.value->>'global_id' AS global_id,
            d.value->>'plate' AS plate,
            COALESCE(d.value->>'class_name', d.value->>'object_type') AS object_type,
            re.camera_id,
            MAX(re.event_timestamp) AS last_seen,
            MIN(re.event_timestamp) AS first_seen,
            COUNT(*) AS observations
        FROM recent_events re
        CROSS JOIN LATERAL jsonb_array_elements(
            CASE WHEN jsonb_typeof(re.metadata->'detections') = 'array' 
                 THEN re.metadata->'detections' 
                 ELSE '[]'::jsonb 
            END
        ) d(value)
        WHERE d.value->>'track_id' IS NOT NULL
        GROUP BY 
            d.value->>'track_id',
            d.value->>'global_id',
            d.value->>'plate',
            COALESCE(d.value->>'class_name', d.value->>'object_type'),
            re.camera_id
        ORDER BY MAX(re.event_timestamp) DESC
        LIMIT $1;
    """

    async with postgres.pool.acquire() as conn:
        rows = await conn.fetch(query, limit)

    targets = []
    for r in rows:
        targets.append({
            "track_id": r["track_id"],
            "global_id": r["global_id"],
            "plate": r["plate"],
            "object_type": r["object_type"],
            "camera_id": r["camera_id"],
            "last_seen": r["last_seen"].isoformat() if r["last_seen"] else None,
            "first_seen": r["first_seen"].isoformat() if r["first_seen"] else None,
            "observations": int(r["observations"]),
        })

    return {"count": len(targets), "targets": targets}


@router.get("/cameras")
async def get_surveillance_cameras():
    """
    Get all Gujarat surveillance cameras as a GeoJSON FeatureCollection with statuses and locations.
    """
    if postgres.pool is None:
        raise HTTPException(status_code=503, detail="PostgreSQL is unavailable")

    query = """
        SELECT 
            c.camera_id,
            c.name,
            c.node_id,
            COALESCE(c.city, MAX(e.metadata->>'city'), 'Gujarat') AS city,
            c.source,
            COALESCE(c.latitude, MAX(e.latitude)) AS latitude,
            COALESCE(c.longitude, MAX(e.longitude)) AS longitude,
            c.enabled,
            c.status,
            c.last_seen,
            COUNT(e.id) AS events_count
        FROM public.cameras c
        LEFT JOIN public.events e ON c.camera_id = e.camera_id
        GROUP BY c.camera_id, c.name, c.node_id, c.city, c.source, c.latitude, c.longitude, c.enabled, c.status, c.last_seen
        ORDER BY c.city, c.name;
    """

    async with postgres.pool.acquire() as conn:
        rows = await conn.fetch(query)

    features = []
    for r in rows:
        lat = float(r["latitude"]) if r["latitude"] is not None else None
        lon = float(r["longitude"]) if r["longitude"] is not None else None
        geom = {
            "type": "Point",
            "coordinates": [lon, lat],
        } if (lon is not None and lat is not None) else None

        features.append(
            {
                "type": "Feature",
                "geometry": geom,
                "properties": {
                    "camera_id": r["camera_id"],
                    "name": r["name"],
                    "node_id": r["node_id"],
                    "city": r["city"],
                    "source": r["source"],
                    "status": r["status"],
                    "enabled": r["enabled"],
                    "location_available": (lat is not None and lon is not None),
                    "last_seen": r["last_seen"].isoformat() if r["last_seen"] else None,
                    "events_count": int(r["events_count"]),
                },
            }
        )

    return {
        "type": "FeatureCollection",
        "properties": {
            "total_cameras": len(features),
            "region": "Gujarat Surveillance Grid",
        },
        "features": features,
    }
