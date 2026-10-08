import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_platform.apps.api.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    hash_token,
    verify_password,
)

from fastapi import Request
from agent_platform.apps.api.core.oauth import oauth
from agent_platform.apps.api.api.deps import CurrentUser, get_current_user

from agent_platform.apps.api.db.models import RefreshToken, Tenant, User
from agent_platform.apps.api.db.session import get_session
# add to imports:
from datetime import datetime, timezone
from uuid import UUID
from agent_platform.apps.api.api.deps import TenantContext, require_role
from agent_platform.apps.api.core.security import generate_api_key
from agent_platform.apps.api.db.models import APIKey

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_DAYS = 7


class SignupRequest(BaseModel):
    tenant_name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    tenant_slug: str
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class SignupResponse(TokenPair):
    tenant_id: str
    user_id: str


class APIKeyCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)


class APIKeyOut(BaseModel):
    id: str
    name: str
    key_prefix: str
    created_at: datetime


class APIKeyCreated(APIKeyOut):
    key: str  # raw value — shown exactly once


@router.post("/api-keys", status_code=status.HTTP_201_CREATED, response_model=APIKeyCreated)
async def create_api_key(
    body: APIKeyCreate,
    ctx: TenantContext = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_session),
):
    raw, key_hash, prefix = generate_api_key()
    key = APIKey(
        tenant_id=UUID(ctx.tenant_id), name=body.name, key_hash=key_hash, key_prefix=prefix
    )
    session.add(key)
    await session.commit()
    return APIKeyCreated(
        id=str(key.id), name=key.name, key_prefix=prefix,
        created_at=key.created_at, key=raw,
    )


@router.get("/api-keys", response_model=list[APIKeyOut])
async def list_api_keys(
    ctx: TenantContext = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_session),
):
    keys = (
        await session.scalars(
            select(APIKey)
            .where(APIKey.tenant_id == UUID(ctx.tenant_id), APIKey.revoked_at.is_(None))
            .order_by(APIKey.created_at)
        )
    ).all()
    return [
        APIKeyOut(id=str(k.id), name=k.name, key_prefix=k.key_prefix, created_at=k.created_at)
        for k in keys
    ]


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    key_id: UUID,
    ctx: TenantContext = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_session),
):
    key = await session.get(APIKey, key_id)
    if key is None or str(key.tenant_id) != ctx.tenant_id or key.revoked_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "API key not found")
    key.revoked_at = datetime.now(timezone.utc)
    await session.commit()
    return None


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "tenant"


async def _issue_pair(session: AsyncSession, user: User) -> TokenPair:
    access = create_access_token(str(user.id), str(user.tenant_id), user.role)
    raw_refresh = create_refresh_token()
    session.add(
        RefreshToken(
            user_id=user.id,
            tenant_id=user.tenant_id,
            token_hash=hash_token(raw_refresh),
            expires_at=datetime.now(timezone.utc) + timedelta(days=REFRESH_DAYS),
        )
    )
    return TokenPair(access_token=access, refresh_token=raw_refresh)


@router.post("/signup", status_code=status.HTTP_201_CREATED, response_model=SignupResponse)
async def signup(body: SignupRequest, session: AsyncSession = Depends(get_session)):
    slug = _slugify(body.tenant_name)
    if await session.scalar(select(Tenant).where(Tenant.slug == slug)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Tenant name is taken")
    tenant = Tenant(name=body.tenant_name, slug=slug)
    session.add(tenant)
    await session.flush()
    user = User(
        tenant_id=tenant.id,
        email=body.email,
        password_hash=hash_password(body.password),
        role="owner",
    )
    session.add(user)
    await session.flush()
    pair = await _issue_pair(session, user)
    await session.commit()
    return SignupResponse(**pair.model_dump(), tenant_id=str(tenant.id), user_id=str(user.id))


@router.post("/login", response_model=TokenPair)
async def login(body: LoginRequest, session: AsyncSession = Depends(get_session)):
    user = await session.scalar(
        select(User)
        .join(Tenant, Tenant.id == User.tenant_id)
        .where(Tenant.slug == body.tenant_slug, User.email == body.email)
    )
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    pair = await _issue_pair(session, user)
    await session.commit()
    return pair


@router.post("/refresh", response_model=TokenPair)
async def refresh(body: RefreshRequest, session: AsyncSession = Depends(get_session)):
    now = datetime.now(timezone.utc)
    rt = await session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(body.refresh_token))
    )
    if not rt or rt.revoked_at is not None or rt.expires_at < now:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")
    rt.revoked_at = now  # rotation: the presented token dies here
    user = await session.get(User, rt.user_id)
    pair = await _issue_pair(session, user)
    await session.commit()
    return pair



@router.get("/me")
async def me(user: CurrentUser = Depends(get_current_user)):
    return {"user_id": user.user_id, "tenant_id": user.tenant_id, "role": user.role}


@router.get("/google/login")
async def google_login(request: Request, tenant_slug: str, session: AsyncSession = Depends(get_session)):
    tenant = await session.scalar(select(Tenant).where(Tenant.slug == tenant_slug))
    if not tenant:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant not found")
    request.session["oauth_tenant_slug"] = tenant_slug
    redirect_uri = request.url_for("google_callback")
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/google/callback", name="google_callback", response_model=TokenPair)
async def google_callback(request: Request, session: AsyncSession = Depends(get_session)):
    tenant_slug = request.session.pop("oauth_tenant_slug", None)
    if not tenant_slug:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Missing tenant context — restart login")
    try:
        token = await oauth.google.authorize_access_token(request)
        userinfo = await oauth.google.parse_id_token(request, token)
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Google authentication failed")
    if not userinfo.get("email_verified"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Google email is not verified")
    tenant = await session.scalar(select(Tenant).where(Tenant.slug == tenant_slug))
    if not tenant:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant not found")
    user = await session.scalar(
        select(User).where(User.tenant_id == tenant.id, User.email == userinfo["email"])
    )
    if not user:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "No account for this email in this tenant"
        )
    pair = await _issue_pair(session, user)
    await session.commit()
    return pair
