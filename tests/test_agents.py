import uuid
import pytest
from httpx import ASGITransport, AsyncClient

from agent_platform.apps.api.main import app


@pytest.mark.asyncio
async def test_api_keys_and_agents_flow():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Signup Tenant 1 (Owner)
        suffix1 = uuid.uuid4().hex[:8]
        signup1 = await client.post(
            "/api/v1/auth/signup",
            json={
                "tenant_name": f"Tenant 1 {suffix1}",
                "email": f"owner1_{suffix1}@example.com",
                "password": "password12345",
            },
        )
        assert signup1.status_code == 201
        data1 = signup1.json()
        token1 = data1["access_token"]
        headers1 = {"Authorization": f"Bearer {token1}"}

        # 2. Create API Key for Tenant 1
        create_key_res = await client.post(
            "/api/v1/auth/api-keys",
            headers=headers1,
            json={"name": "Production Key"},
        )
        assert create_key_res.status_code == 201, create_key_res.text
        key_data = create_key_res.json()
        assert "key" in key_data
        assert key_data["key"].startswith("ak_")
        assert key_data["key_prefix"] == key_data["key"][:12]
        raw_key = key_data["key"]
        key_id = key_data["id"]

        # 3. List API Keys
        list_keys_res = await client.get("/api/v1/auth/api-keys", headers=headers1)
        assert list_keys_res.status_code == 200
        keys_list = list_keys_res.json()
        assert any(k["id"] == key_id for k in keys_list)

        # 4. Use API Key to Create Agent (via X-API-Key header)
        api_key_headers = {"X-API-Key": raw_key}
        create_agent_res = await client.post(
            "/api/v1/agents",
            headers=api_key_headers,
            json={"name": "Support Bot", "description": "Customer support agent"},
        )
        assert create_agent_res.status_code == 201, create_agent_res.text
        agent1 = create_agent_res.json()
        agent1_id = agent1["id"]
        assert agent1["name"] == "Support Bot"

        # 5. List Agents via Bearer Token
        list_agents_res = await client.get("/api/v1/agents", headers=headers1)
        assert list_agents_res.status_code == 200
        assert any(a["id"] == agent1_id for a in list_agents_res.json())

        # 6. Get Agent by ID
        get_agent_res = await client.get(f"/api/v1/agents/{agent1_id}", headers=headers1)
        assert get_agent_res.status_code == 200
        assert get_agent_res.json()["name"] == "Support Bot"

        # 7. Register Version 1 for Agent
        config_v1 = {"model": "gpt-4o-mini", "temperature": 0.7, "system_prompt": "You are helpful."}
        v1_res = await client.post(
            f"/api/v1/agents/{agent1_id}/versions",
            headers=api_key_headers,
            json={"config": config_v1},
        )
        assert v1_res.status_code == 201, v1_res.text
        v1_data = v1_res.json()
        assert v1_data["version"] == 1
        assert "checksum" in v1_data
        assert v1_data["config"] == config_v1

        # 8. Register Version 2 for Agent
        config_v2 = {"model": "gpt-4o", "temperature": 0.2, "system_prompt": "You are precise."}
        v2_res = await client.post(
            f"/api/v1/agents/{agent1_id}/versions",
            headers=headers1,
            json={"config": config_v2},
        )
        assert v2_res.status_code == 201
        v2_data = v2_res.json()
        assert v2_data["version"] == 2
        assert v2_data["config"] == config_v2

        # 9. List Versions
        list_v_res = await client.get(f"/api/v1/agents/{agent1_id}/versions", headers=headers1)
        assert list_v_res.status_code == 200
        versions = list_v_res.json()
        assert len(versions) == 2
        assert [v["version"] for v in versions] == [1, 2]

        # 10. Get Specific Version
        get_v1_res = await client.get(f"/api/v1/agents/{agent1_id}/versions/1", headers=headers1)
        assert get_v1_res.status_code == 200
        assert get_v1_res.json()["version"] == 1

        get_v99_res = await client.get(f"/api/v1/agents/{agent1_id}/versions/99", headers=headers1)
        assert get_v99_res.status_code == 404

        # 11. Cross-Tenant Isolation: Tenant 2 cannot access Tenant 1's Agent
        suffix2 = uuid.uuid4().hex[:8]
        signup2 = await client.post(
            "/api/v1/auth/signup",
            json={
                "tenant_name": f"Tenant 2 {suffix2}",
                "email": f"owner2_{suffix2}@example.com",
                "password": "password12345",
            },
        )
        assert signup2.status_code == 201
        headers2 = {"Authorization": f"Bearer {signup2.json()['access_token']}"}

        # Tenant 2 gets 404 when querying Tenant 1's agent (prevent existence leak)
        cross_res = await client.get(f"/api/v1/agents/{agent1_id}", headers=headers2)
        assert cross_res.status_code == 404

        # Tenant 2's list does NOT contain Tenant 1's agent
        list2 = await client.get("/api/v1/agents", headers=headers2)
        assert not any(a["id"] == agent1_id for a in list2.json())

        # 12. Revoke API Key
        del_key_res = await client.delete(f"/api/v1/auth/api-keys/{key_id}", headers=headers1)
        assert del_key_res.status_code == 204

        # Using revoked API key returns 401
        revoked_call = await client.get("/api/v1/agents", headers=api_key_headers)
        assert revoked_call.status_code == 401
