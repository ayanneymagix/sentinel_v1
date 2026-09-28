import json
import logging
from typing import Any, Optional
from datetime import datetime
import asyncpg
from app.models.registry_schemas import UserContext, UserRole

logger = logging.getLogger("sentinel.registry.audit")

class AuditService:
    @staticmethod
    async def log_event(
        pool: asyncpg.Pool,
        action: str,
        entity_type: str,
        entity_id: str,
        camera_id: Optional[str] = None,
        old_value: Optional[Any] = None,
        new_value: Optional[Any] = None,
        user: Optional[UserContext] = None,
        reason: Optional[str] = None,
        ip_address: Optional[str] = None
    ) -> Optional[int]:
        """Appends an immutable audit record to public.cctv_audit_log."""
        user_id = user.user_id if user else "SYSTEM"
        username = user.username if user else "SYSTEM"
        role = user.role if user else UserRole.OPERATOR

        # Convert dict or objects to json string if necessary
        def _serialize(val):
            if val is None:
                return None
            if isinstance(val, (dict, list)):
                return json.dumps(val, default=str)
            if hasattr(val, "model_dump"):
                return json.dumps(val.model_dump(), default=str)
            return json.dumps(str(val))

        old_json = _serialize(old_value)
        new_json = _serialize(new_value)

        sql = """
            INSERT INTO public.cctv_audit_log (
                timestamp, user_id, username, role, action,
                entity_type, entity_id, camera_id,
                old_value, new_value, reason, ip_address
            ) VALUES (
                NOW(), $1, $2, $3, $4,
                $5, $6, $7,
                $8::jsonb, $9::jsonb, $10, $11
            ) RETURNING id;
        """

        try:
            async with pool.acquire() as conn:
                audit_id = await conn.fetchval(
                    sql,
                    user_id,
                    username,
                    role,
                    action,
                    entity_type,
                    str(entity_id),
                    camera_id,
                    old_json,
                    new_json,
                    reason,
                    ip_address
                )
                logger.info(f"Audit log #{audit_id} recorded: {action} on {entity_type} {entity_id} by {username} ({role})")
                return audit_id
        except Exception as e:
            logger.error(f"Failed to record audit log: {e}", exc_info=True)
            return None
