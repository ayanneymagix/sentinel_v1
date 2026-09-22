import json
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.database.postgres import postgres
from app.database.redis import redis_client

logger = logging.getLogger("sentinel.api.watchlist")

router = APIRouter(prefix="/watchlist", tags=["eGujCop Watchlist"])


class WatchlistCreate(BaseModel):
    license_plate: str
    vehicle_make: Optional[str] = None
    vehicle_model: Optional[str] = None
    vehicle_color: Optional[str] = None
    owner_name: Optional[str] = None
    category: str = "STOLEN"
    severity: str = "CRITICAL"
    notes: Optional[str] = None
    flagged_by: str = "eGujCop / CID Crime Gujarat"



@router.get("")
async def get_watchlist():
    """
    Retrieve all registered vehicles on the eGujCop criminal/stolen watchlist.
    """
    if postgres.pool is None:
        raise HTTPException(status_code=503, detail="PostgreSQL is unavailable")

    query = """
        SELECT 
            id,
            license_plate,
            vehicle_make,
            vehicle_model,
            vehicle_color,
            owner_name,
            category,
            severity,
            notes,
            flagged_by,
            created_at,
            updated_at
        FROM public.egujcop_watchlist
        ORDER BY severity DESC, created_at DESC;
    """

    async with postgres.pool.acquire() as conn:
        rows = await conn.fetch(query)

    items = []
    for r in rows:
        items.append(
            {
                "id": r["id"],
                "license_plate": r["license_plate"],
                "vehicle_make": r["vehicle_make"],
                "vehicle_model": r["vehicle_model"],
                "vehicle_color": r["vehicle_color"],
                "owner_name": r["owner_name"],
                "category": r["category"],
                "severity": r["severity"],
                "notes": r["notes"],
                "flagged_by": r["flagged_by"],
                "created_at": r["created_at"].isoformat(),
            }
        )

    return {"count": len(items), "watchlist": items}


@router.post("")
async def add_to_watchlist(entry: WatchlistCreate):
    """
    Add a vehicle license plate to the eGujCop Watchlist (updates PostgreSQL and Redis).
    """
    if postgres.pool is None:
        raise HTTPException(status_code=503, detail="PostgreSQL is unavailable")

    plate = entry.license_plate.strip().upper()

    query = """
        INSERT INTO public.egujcop_watchlist (
            license_plate, vehicle_make, vehicle_model, vehicle_color,
            owner_name, category, severity, notes, flagged_by
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        ON CONFLICT (license_plate) DO UPDATE
        SET vehicle_make = EXCLUDED.vehicle_make,
            vehicle_model = EXCLUDED.vehicle_model,
            vehicle_color = EXCLUDED.vehicle_color,
            owner_name = EXCLUDED.owner_name,
            category = EXCLUDED.category,
            severity = EXCLUDED.severity,
            notes = EXCLUDED.notes,
            updated_at = NOW()
        RETURNING id;
    """

    async with postgres.pool.acquire() as conn:
        entry_id = await conn.fetchval(
            query,
            plate,
            entry.vehicle_make,
            entry.vehicle_model,
            entry.vehicle_color,
            entry.owner_name,
            entry.category.upper(),
            entry.severity.upper(),
            entry.notes,
            entry.flagged_by,
        )

    # Sync to Redis Set
    if redis_client.client:
        try:
            await redis_client.client.sadd("egujcop_watchlist", plate)
        except Exception:
            logger.warning("Failed to sync plate %s to Redis watchlist set", plate)

    return {
        "status": "success",
        "id": entry_id,
        "license_plate": plate,
        "message": f"License plate {plate} registered in eGujCop Watchlist",
    }




@router.delete("/{plate}")
async def delete_from_watchlist(plate: str):
    """
    Remove a vehicle license plate from the eGujCop Watchlist (updates PostgreSQL and Redis).
    """
    if postgres.pool is None:
        raise HTTPException(status_code=503, detail="PostgreSQL is unavailable")

    norm_plate = plate.strip().upper()

    async with postgres.pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM public.egujcop_watchlist WHERE UPPER(license_plate) = $1",
            norm_plate,
        )

    if redis_client.client:
        try:
            await redis_client.client.srem("egujcop_watchlist", norm_plate)
        except Exception:
            pass

    return {
        "status": "success",
        "license_plate": norm_plate,
        "message": f"License plate {norm_plate} removed from Watchlist",
    }

