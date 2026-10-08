from fastapi import FastAPI

from agent_platform.apps.api.core.config import settings
from agent_platform.apps.api.v1 import auth, health, agents
from starlette.middleware.sessions import SessionMiddleware

app = FastAPI(title=settings.app_name, version=settings.app_version)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,  # change for production
)

app.include_router(health.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1")
app.include_router(agents.router, prefix="/api/v1")
