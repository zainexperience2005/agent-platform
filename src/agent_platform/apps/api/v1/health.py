import asyncpg
import redis.asyncio as aioredis
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from agent_platform.apps.api.core.config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    return {"status": "ok", "app": settings.app_name, "version": settings.app_version}


@router.get("/ready")
async def ready():
    try:
        conn = await asyncpg.connect(settings.database_url, timeout=5)
        await conn.execute("SELECT 1")
        await conn.close()
    except Exception as exc:  # noqa: BLE001 — a probe must never raise
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "not_ready", "postgres": "down", "detail": str(exc)},
        )
    try:
        r = aioredis.from_url(settings.redis_url, socket_timeout=5)
        await r.ping()
        await r.aclose()
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "not_ready", "redis": "down", "detail": str(exc)},
        )
    return {"status": "ready", "postgres": "up", "redis": "up"}
