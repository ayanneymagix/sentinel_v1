import json
import logging

from fastapi import APIRouter, HTTPException

from app.database.postgres import postgres
from app.database.redis import redis_client
from app.models.schemas import EventCreate, EventResponse


logger = logging.getLogger("sentinel.api.events")

router = APIRouter()

EVENT_STREAM = "sentinel:events"


from app.routers.websocket import manager
from app.routers.cross_camera import cross_camera_registry


@router.get("/events/recent")
async def get_recent_events(limit: int = 50):
    """
    Retrieve real CCTV detection events from PostgreSQL.
    """
    if postgres.pool is None:
        return []

    query = """
        SELECT 
            event_id,
            node_id,
            camera_id,
            event_type,
            confidence,
            event_timestamp,
            latitude,
            longitude,
            frame_number,
            inference_latency_ms,
            metadata
        FROM public.events
        ORDER BY event_timestamp DESC
        LIMIT $1;
    """

    try:
        async with postgres.pool.acquire() as conn:
            rows = await conn.fetch(query, limit)

        events_list = []
        for r in rows:
            raw_meta = r["metadata"]
            meta = json.loads(raw_meta) if isinstance(raw_meta, str) else (raw_meta or {})
            if not isinstance(meta, dict):
                meta = {}
            alpr = meta.get("alpr", {}) if isinstance(meta.get("alpr"), dict) else {}
            behavior = meta.get("behavior", {}) if isinstance(meta.get("behavior"), dict) else {}
            detections = meta.get("detections", []) if isinstance(meta.get("detections"), list) else []

            plate = alpr.get("plate") or meta.get("license_plate") or meta.get("plate")
            track_id = alpr.get("track_id") or behavior.get("track_id") or meta.get("track_id")

            if detections:
                first_det = detections[0] if isinstance(detections[0], dict) else {}
                if not plate:
                    plate = first_det.get("plate")
                if not track_id:
                    track_id = first_det.get("track_id")

            events_list.append({
                "event_id": str(r["event_id"]),
                "camera_id": r["camera_id"],
                "node_id": r["node_id"],
                "event_type": r["event_type"],
                "confidence": r["confidence"] or 0.90,
                "timestamp": r["event_timestamp"].isoformat() if r["event_timestamp"] else None,
                "latitude": r["latitude"],
                "longitude": r["longitude"],
                "city": (meta.get("city") if isinstance(meta, dict) else "Gujarat") or "Gujarat",
                "license_plate": plate,
                "track_id": track_id,
                "latency_ms": r["inference_latency_ms"] or 35.0,
                "metadata": meta,
            })
        return events_list
    except Exception as exc:
        logger.warning("Failed to fetch recent events: %s", exc)
        return []


@router.post(
    "/events",
    response_model=EventResponse
)
async def create_event(event: EventCreate):
    try:
        # Update Central Cross-Camera Surveillance Registry
        for detection in event.detections:
            det_dict = detection.model_dump()
            cross_camera_registry.record_detection(
                camera_id=event.camera_id,
                detection=det_dict,
                event_time_iso=event.timestamp.isoformat(),
            )

        redis_payload = {
            "event_id": str(event.event_id),

            "node_id": event.node_id,

            "camera_id": event.camera_id,

            "event_type": event.event_type,

            "timestamp": event.timestamp.isoformat(),

            "confidence": (
                str(event.confidence)
                if event.confidence is not None
                else ""
            ),

            "video_time_seconds": (
                str(getattr(event, "video_time_seconds", None))
                if getattr(event, "video_time_seconds", None) is not None
                else ""
            ),

            "risk_level": (
                str(getattr(event, "risk_level", None))
                if getattr(event, "risk_level", None) is not None
                else "LOW"
            ),

            "risk_reason": (
                str(getattr(event, "risk_reason", None))
                if getattr(event, "risk_reason", None) is not None
                else ""
            ),

            "latitude": (
                str(event.latitude)
                if event.latitude is not None
                else ""
            ),

            "longitude": (
                str(event.longitude)
                if event.longitude is not None
                else ""
            ),

            "frame_number": (
                str(event.frame_number)
                if event.frame_number is not None
                else ""
            ),

            "inference_latency_ms": (
                str(event.inference_latency_ms)
                if event.inference_latency_ms is not None
                else ""
            ),

            "detections": json.dumps(
                [
                    detection.model_dump()
                    for detection in event.detections
                ]
            ),

            "metadata": json.dumps(
                event.metadata
            ),
        }

        redis_id = None
        if redis_client.client is not None:
            try:
                redis_id = await redis_client.client.xadd(
                    EVENT_STREAM,
                    redis_payload,
                    maxlen=10000,
                    approximate=True,
                )
            except Exception as rx_err:
                logger.warning("Redis stream write notice: %s", rx_err)

        # Broadcast live detection to connected dashboards
        try:
            snapshot = event.metadata.get("incident_snapshot_base64") if event.metadata else None
            live_broadcast_payload = {
                "event_type": event.event_type or "LIVE_DETECTION",
                "event_id": str(event.event_id),
                "node_id": event.node_id,
                "camera_id": event.camera_id,
                "confidence": event.confidence,
                "timestamp": event.timestamp.isoformat(),
                "video_time_seconds": getattr(event, "video_time_seconds", None),
                "risk_level": getattr(event, "risk_level", None) or "LOW",
                "risk_reason": getattr(event, "risk_reason", None) or "",
                "latitude": event.latitude,
                "longitude": event.longitude,
                "frame_number": event.frame_number,
                "inference_latency_ms": event.inference_latency_ms,
                "detections": [detection.model_dump() for detection in event.detections],
                "incident_snapshot_base64": snapshot,
                "metadata": event.metadata,
            }
            serialized_payload = json.dumps(live_broadcast_payload)
            if redis_client.client is not None:
                try:
                    await redis_client.client.publish(
                        "sentinel:live_feed",
                        serialized_payload,
                    )
                    if event.event_type in ("VEHICLE_COLLISION", "THREAT_DETECTED") or event.risk_level == "CRITICAL":
                        await redis_client.client.publish(
                            "sentinel:alerts",
                            serialized_payload,
                        )
                except Exception as r_err:
                    logger.debug("Redis publish fallback to direct ws: %s", r_err)
                    await manager.broadcast(serialized_payload)
            else:
                # Direct WebSocket broadcast fallback when Redis is unavailable
                await manager.broadcast(serialized_payload)
        except Exception as b_exc:
            logger.warning("Dashboard broadcast notice: %s", b_exc)

        logger.info(
            "Event queued | event_id=%s | camera_id=%s | detections=%d",
            event.event_id,
            event.camera_id,
            len(event.detections),
        )

        return EventResponse(
            status="accepted",
            event_id=event.event_id,
            message="Event accepted into Sentinel event stream",
        )

    except Exception:

        logger.exception(
            "Failed to publish event"
        )

        raise HTTPException(
            status_code=500,
            detail="Failed to publish event"
        )