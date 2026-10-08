from fastapi import FastAPI

from agent_platform.apps.api.core.config import settings
from agent_platform.apps.api.v1 import health

app = FastAPI(title=settings.app_name, version=settings.app_version)
app.include_router(health.router, prefix="/api/v1")
