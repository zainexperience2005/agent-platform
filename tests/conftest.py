import pytest_asyncio
from agent_platform.apps.api.db.session import engine


@pytest_asyncio.fixture(autouse=True)
async def cleanup():
    yield
    await engine.dispose()
