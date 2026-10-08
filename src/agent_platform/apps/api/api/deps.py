from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_platform.apps.api.core.security import decode_token, hash_token
from agent_platform.apps.api.db.models import Agent, APIKey
from agent_platform.apps.api.db.session import get_session

bearer_scheme = HTTPBearer(auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


class CurrentUser(BaseModel):
    user_id: str
    tenant_id: str
    role: str


class TenantContext(BaseModel):
    tenant_id: str
    user_id: str | None
    role: str
    auth_type: str  # "jwt" | "api_key"


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> CurrentUser:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        payload = decode_token(creds.credentials)
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    if payload.get("type") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token type")
    return CurrentUser(user_id=payload["sub"], tenant_id=payload["tenant_id"], role=payload["role"])


async def get_tenant_ctx(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    api_key: str | None = Depends(api_key_header),
    session: AsyncSession = Depends(get_session),
) -> TenantContext:
    if creds is not None:
        try:
            payload = decode_token(creds.credentials)
        except Exception:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
        if payload.get("type") != "access":
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token type")
        return TenantContext(
            tenant_id=payload["tenant_id"],
            user_id=payload["sub"],
            role=payload["role"],
            auth_type="jwt",
        )
    if api_key is not None:
        key = await session.scalar(
            select(APIKey).where(
                APIKey.key_hash == hash_token(api_key), APIKey.revoked_at.is_(None)
            )
        )
        if not key:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")
        # NOTE: keys act as admin; per-key capability scopes arrive in Week 3.
        return TenantContext(
            tenant_id=str(key.tenant_id), user_id=None, role="admin", auth_type="api_key"
        )
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")


_ROLE_RANK = {"viewer": 0, "member": 1, "admin": 2, "owner": 3}


def require_role(min_role: str):
    async def checker(ctx: TenantContext = Depends(get_tenant_ctx)) -> TenantContext:
        if _ROLE_RANK.get(ctx.role, -1) < _ROLE_RANK[min_role]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role")
        return ctx

    return checker


async def get_owned_agent(agent_id: UUID, ctx: TenantContext, session: AsyncSession) -> Agent:
    """Fetch an agent or 404 — never 403, so cross-tenant IDs leak no existence."""
    agent = await session.get(Agent, agent_id)
    if agent is None or str(agent.tenant_id) != ctx.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
    return agent
