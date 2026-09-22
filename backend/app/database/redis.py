from typing import Optional

try:
    import redis.asyncio as redis
except ImportError:
    redis = None

from app.config import get_settings


class RedisClient:

    def __init__(self):
        self.client = None

    async def connect(self):
        if redis is None:
            self.client = None
            return

        settings = get_settings()

        try:
            client = redis.from_url(
                settings.redis_url,
                decode_responses=True,
            )
            await client.ping()
            self.client = client
        except Exception:
            self.client = None
            raise

    async def disconnect(self):

        if self.client:

            await self.client.aclose()

            self.client = None

    async def health_check(self) -> bool:

        if self.client is None:
            return False

        try:

            return bool(
                await self.client.ping()
            )

        except Exception:

            return False


redis_client = RedisClient()