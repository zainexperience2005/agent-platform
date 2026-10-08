"""Dev seed: demo tenant + owner. Safe to re-run. Never run against prod."""

import asyncio

from sqlalchemy import select

from agent_platform.apps.api.core.security import hash_password
from agent_platform.apps.api.db.models import Tenant, User
from agent_platform.apps.api.db.session import SessionLocal


async def main() -> None:
    async with SessionLocal() as session:
        tenant = await session.scalar(select(Tenant).where(Tenant.slug == "demo"))
        if tenant is None:
            tenant = Tenant(name="Demo", slug="demo")
            session.add(tenant)
            await session.flush()
            session.add(
                User(
                    tenant_id=tenant.id,
                    email="owner@demo.test",
                    password_hash=hash_password("demo12345"),
                    role="owner",
                )
            )
            await session.commit()
            print("seeded demo tenant: owner@demo.test / demo12345")
        else:
            print("demo tenant already exists — nothing to do")


if __name__ == "__main__":
    asyncio.run(main())
