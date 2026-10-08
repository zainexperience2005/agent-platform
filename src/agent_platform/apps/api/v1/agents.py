import hashlib
import json
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_platform.apps.api.api.deps import TenantContext, get_owned_agent, get_tenant_ctx, require_role
from agent_platform.apps.api.db.models import Agent, AgentVersion
from agent_platform.apps.api.db.session import get_session

router = APIRouter(prefix="/agents", tags=["agents"])


def _checksum(config: dict) -> str:
    canonical = json.dumps(config, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


class AgentCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    description: str | None = None


class AgentOut(BaseModel):
    id: str
    name: str
    description: str | None
    created_at: datetime


class VersionCreate(BaseModel):
    config: dict


class VersionOut(BaseModel):
    id: str
    version: int
    checksum: str
    config: dict
    created_at: datetime


def _agent_out(a: Agent) -> AgentOut:
    return AgentOut(id=str(a.id), name=a.name, description=a.description, created_at=a.created_at)


def _version_out(v: AgentVersion) -> VersionOut:
    return VersionOut(
        id=str(v.id), version=v.version, checksum=v.checksum,
        config=v.config, created_at=v.created_at,
    )


@router.post("", status_code=status.HTTP_201_CREATED, response_model=AgentOut)
async def create_agent(
    body: AgentCreate,
    ctx: TenantContext = Depends(require_role("member")),
    session: AsyncSession = Depends(get_session),
):
    agent = Agent(tenant_id=UUID(ctx.tenant_id), name=body.name, description=body.description)
    session.add(agent)
    await session.commit()
    return _agent_out(agent)


@router.get("", response_model=list[AgentOut])
async def list_agents(
    ctx: TenantContext = Depends(get_tenant_ctx),
    session: AsyncSession = Depends(get_session),
):
    agents = (
        await session.scalars(
            select(Agent).where(Agent.tenant_id == UUID(ctx.tenant_id)).order_by(Agent.created_at)
        )
    ).all()
    return [_agent_out(a) for a in agents]


@router.get("/{agent_id}", response_model=AgentOut)
async def get_agent(
    agent_id: UUID,
    ctx: TenantContext = Depends(get_tenant_ctx),
    session: AsyncSession = Depends(get_session),
):
    return _agent_out(await get_owned_agent(agent_id, ctx, session))


@router.post("/{agent_id}/versions", status_code=status.HTTP_201_CREATED, response_model=VersionOut)
async def register_version(
    agent_id: UUID,
    body: VersionCreate,
    ctx: TenantContext = Depends(require_role("member")),
    session: AsyncSession = Depends(get_session),
):
    agent = await get_owned_agent(agent_id, ctx, session)
    max_v = await session.scalar(
        select(func.max(AgentVersion.version)).where(AgentVersion.agent_id == agent.id)
    )
    av = AgentVersion(
        agent_id=agent.id,
        tenant_id=agent.tenant_id,
        version=(max_v or 0) + 1,
        config=body.config,
        checksum=_checksum(body.config),
    )
    session.add(av)
    await session.commit()
    return _version_out(av)


@router.get("/{agent_id}/versions", response_model=list[VersionOut])
async def list_versions(
    agent_id: UUID,
    ctx: TenantContext = Depends(get_tenant_ctx),
    session: AsyncSession = Depends(get_session),
):
    agent = await get_owned_agent(agent_id, ctx, session)
    versions = (
        await session.scalars(
            select(AgentVersion)
            .where(AgentVersion.agent_id == agent.id)
            .order_by(AgentVersion.version)
        )
    ).all()
    return [_version_out(v) for v in versions]


@router.get("/{agent_id}/versions/{version}", response_model=VersionOut)
async def get_version(
    agent_id: UUID,
    version: int,
    ctx: TenantContext = Depends(get_tenant_ctx),
    session: AsyncSession = Depends(get_session),
):
    agent = await get_owned_agent(agent_id, ctx, session)
    av = await session.scalar(
        select(AgentVersion).where(
            AgentVersion.agent_id == agent.id, AgentVersion.version == version
        )
    )
    if av is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Version not found")
    return _version_out(av)
