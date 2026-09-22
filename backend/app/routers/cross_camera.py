from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

logger = logging.getLogger("sentinel.api.cross_camera")

router = APIRouter(prefix="/cross-camera", tags=["Cross-Camera Surveillance & Re-ID"])


class BackendCrossCameraRegistry:
    """
    Central Cross-Camera Vehicle Tracking & Re-Identification State.
    Aggregates vehicle observations across all cameras in the Gujarat CCTV surveillance grid.
    """

    def __init__(self) -> None:
        self.registry: Dict[str, Dict[str, Any]] = {}
        self.camera_names: Dict[str, str] = {}

    def set_camera_name(self, camera_id: str, name: str) -> None:
        if camera_id and name:
            self.camera_names[camera_id] = name

    def record_detection(
        self,
        camera_id: str,
        detection: Dict[str, Any],
        event_time_iso: Optional[str] = None,
        event_timestamp: Optional[float] = None,
    ) -> None:
        gid = detection.get("global_id")
        if not gid:
            tid = detection.get("track_id")
            if tid is not None:
                gid = f"SENTINEL-CAM-{camera_id}-T{tid}"
            else:
                return

        now_ts = event_timestamp or time.time()
        now_iso = event_time_iso or datetime.now(timezone.utc).isoformat()
        cam_name = detection.get("camera_name") or self.camera_names.get(camera_id, f"Camera {camera_id.upper()}")
        self.camera_names[camera_id] = cam_name

        direction = detection.get("direction", "Stationary / Slow")
        speed_kmh = detection.get("speed_kmh")
        plate = detection.get("plate")
        make = detection.get("make", "Passenger Vehicle (LMV)")
        subtype = detection.get("model_subtype", detection.get("object_type", "Vehicle"))
        color = detection.get("color", "White")
        full_name = detection.get("full_name") or f"{color} {subtype}"
        color_rgb = detection.get("color_rgb", [200, 200, 200])
        heading_deg = detection.get("heading_deg")
        trajectory = detection.get("trajectory", [])

        if gid not in self.registry:
            self.registry[gid] = {
                "global_id": gid,
                "plate": plate,
                "make": make,
                "model_subtype": subtype,
                "color": color,
                "color_rgb": color_rgb,
                "full_name": full_name,
                "current_camera_id": camera_id,
                "current_camera_name": cam_name,
                "current_direction": direction,
                "current_speed_kmh": speed_kmh,
                "heading_deg": heading_deg,
                "first_seen": now_iso,
                "last_seen": now_iso,
                "last_seen_ts": now_ts,
                "journey": [
                    {
                        "camera_id": camera_id,
                        "camera_name": cam_name,
                        "timestamp": now_iso,
                        "timestamp_ts": now_ts,
                        "direction": direction,
                        "speed_kmh": speed_kmh,
                    }
                ],
            }
        else:
            veh = self.registry[gid]
            veh["last_seen"] = now_iso
            veh["last_seen_ts"] = now_ts
            veh["current_camera_id"] = camera_id
            veh["current_camera_name"] = cam_name
            veh["current_direction"] = direction
            veh["current_speed_kmh"] = speed_kmh
            veh["heading_deg"] = heading_deg
            if plate and not veh.get("plate"):
                veh["plate"] = plate
            if make and make != "Vehicle":
                veh["make"] = make
                veh["model_subtype"] = subtype
                veh["color"] = color
                veh["full_name"] = full_name
                veh["color_rgb"] = color_rgb

            # Check if entering a new camera
            last_hop = veh["journey"][-1] if veh["journey"] else None
            if not last_hop or last_hop.get("camera_id") != camera_id:
                veh["journey"].append({
                    "camera_id": camera_id,
                    "camera_name": cam_name,
                    "timestamp": now_iso,
                    "timestamp_ts": now_ts,
                    "direction": direction,
                    "speed_kmh": speed_kmh,
                })
                logger.info("Vehicle %s hopped to camera %s (%s)", gid, camera_id, cam_name)

    async def hydrate_from_db(self, limit: int = 150) -> None:
        """
        Hydrate actively tracked vehicles from real detection events in PostgreSQL.
        Ensures cross-camera surveillance tracking is populated across restarts.
        """
        import json
        from app.database.postgres import postgres
        if postgres.pool is None:
            return
        try:
            async with postgres.pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT camera_id, event_timestamp, metadata
                    FROM public.events
                    WHERE metadata->'detections' IS NOT NULL
                    ORDER BY event_timestamp DESC
                    LIMIT $1;
                    """,
                    limit,
                )
            for r in rows:
                raw_meta = r["metadata"]
                meta = json.loads(raw_meta) if isinstance(raw_meta, str) else (raw_meta or {})
                dets = meta.get("detections", [])
                iso_time = r["event_timestamp"].isoformat() if r["event_timestamp"] else None
                ts = r["event_timestamp"].timestamp() if r["event_timestamp"] else time.time()
                for d in dets:
                    if isinstance(d, dict) and (d.get("track_id") is not None or d.get("global_id")):
                        self.record_detection(
                            camera_id=r["camera_id"],
                            detection=d,
                            event_time_iso=iso_time,
                            event_timestamp=ts,
                        )
        except Exception as err:
            logger.debug("Database hydration notice: %s", err)

    def get_active_vehicles(self, max_age_seconds: float = 900.0) -> List[Dict[str, Any]]:
        now = time.time()
        active = []
        for veh in self.registry.values():
            if (now - veh.get("last_seen_ts", 0) <= max_age_seconds) or len(active) < 40:
                item = dict(veh)
                item["journey_hops"] = len(veh.get("journey", []))
                active.append(item)
        active.sort(key=lambda x: x.get("last_seen_ts", 0), reverse=True)
        return active[:50]

    def get_vehicle_journey(self, global_id: str) -> Optional[Dict[str, Any]]:
        return self.registry.get(global_id)


cross_camera_registry = BackendCrossCameraRegistry()


@router.get("/active")
async def get_active_vehicles():
    """
    Retrieve all actively tracked vehicles across cameras in the surveillance network.
    Includes vehicle identity, brand, model subtype, color, plate, current camera, direction, and journey hops.
    """
    if len(cross_camera_registry.registry) == 0:
        await cross_camera_registry.hydrate_from_db()

    vehicles = cross_camera_registry.get_active_vehicles()
    return {
        "status": "success",
        "total_active": len(vehicles),
        "multi_camera_crossings": sum(1 for v in vehicles if v.get("journey_hops", 1) > 1),
        "vehicles": vehicles,
    }


@router.get("/journey/{global_id}")
async def get_vehicle_journey(global_id: str):
    """
    Retrieve full multi-camera journey timeline and hops for a specific tracked vehicle.
    """
    if len(cross_camera_registry.registry) == 0:
        await cross_camera_registry.hydrate_from_db()

    veh = cross_camera_registry.get_vehicle_journey(global_id)
    if not veh:
        raise HTTPException(status_code=404, detail=f"Vehicle {global_id} not found in active registry")
    return {
        "status": "success",
        "vehicle": veh,
    }


@router.get("/grid-matrix")
async def get_grid_matrix():
    """
    Returns transition matrix and active load per surveillance camera node.
    """
    if len(cross_camera_registry.registry) == 0:
        await cross_camera_registry.hydrate_from_db()

    vehicles = cross_camera_registry.get_active_vehicles()
    camera_counts: Dict[str, int] = {}
    transitions: Dict[str, int] = {}

    for v in vehicles:
        cam = v.get("current_camera_id", "unknown")
        camera_counts[cam] = camera_counts.get(cam, 0) + 1
        journey = v.get("journey", [])
        for i in range(len(journey) - 1):
            hop_key = f"{journey[i]['camera_id']} -> {journey[i+1]['camera_id']}"
            transitions[hop_key] = transitions.get(hop_key, 0) + 1

    return {
        "status": "success",
        "camera_counts": camera_counts,
        "inter_camera_transitions": transitions,
    }
