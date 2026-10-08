import uuid
import pytest
from httpx import ASGITransport, AsyncClient

from agent_platform.apps.api.main import app
from agent_platform.apps.api.core.security import decode_token


@pytest.mark.asyncio
async def test_auth_full_flow():
    unique_suffix = uuid.uuid4().hex[:8]
    tenant_name = f"Test Tenant {unique_suffix}"
    email = f"user_{unique_suffix}@example.com"
    password = "supersecretpassword123"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Signup
        signup_payload = {
            "tenant_name": tenant_name,
            "email": email,
            "password": password,
        }
        res = await client.post("/api/v1/auth/signup", json=signup_payload)
        assert res.status_code == 201, res.text
        data = res.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert "tenant_id" in data
        assert "user_id" in data
        assert data["token_type"] == "bearer"

        # Verify decoded JWT
        claims = decode_token(data["access_token"])
        assert claims["sub"] == data["user_id"]
        assert claims["tenant_id"] == data["tenant_id"]
        assert claims["role"] == "owner"
        assert claims["type"] == "access"

        first_refresh = data["refresh_token"]

        # 2. Duplicate signup should return 409
        dup_res = await client.post("/api/v1/auth/signup", json=signup_payload)
        assert dup_res.status_code == 409

        # Derive slug
        tenant_slug = f"test-tenant-{unique_suffix}"

        # 3. Login with wrong password should fail
        bad_login = await client.post(
            "/api/v1/auth/login",
            json={"tenant_slug": tenant_slug, "email": email, "password": "wrongpassword"},
        )
        assert bad_login.status_code == 401

        # 4. Login with correct credentials
        good_login = await client.post(
            "/api/v1/auth/login",
            json={"tenant_slug": tenant_slug, "email": email, "password": password},
        )
        assert good_login.status_code == 200
        login_data = good_login.json()
        assert "access_token" in login_data
        assert "refresh_token" in login_data

        # 5. Refresh token rotation
        refresh_res = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": first_refresh},
        )
        assert refresh_res.status_code == 200
        rotated_data = refresh_res.json()
        assert "access_token" in rotated_data
        assert "refresh_token" in rotated_data
        second_refresh = rotated_data["refresh_token"]

        # 6. Reusing the old rotated refresh token must fail (401)
        reuse_res = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": first_refresh},
        )
        assert reuse_res.status_code == 401

        # 7. Using the new rotated token should succeed
        refresh2_res = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": second_refresh},
        )
        assert refresh2_res.status_code == 200

        # 8. Bogus refresh token must fail (401)
        bogus_res = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": "totally-invalid-token"},
        )
        assert bogus_res.status_code == 401

        # 9. GET /me without auth should fail
        no_auth = await client.get("/api/v1/auth/me")
        assert no_auth.status_code in (401, 403)

        # 10. GET /me with invalid token should fail (401)
        bad_token = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer invalid.token.here"},
        )
        assert bad_token.status_code == 401

        # 11. GET /me with valid access token should succeed
        me_res = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {data['access_token']}"},
        )
        assert me_res.status_code == 200
        me_data = me_res.json()
        assert me_data["user_id"] == data["user_id"]
        assert me_data["tenant_id"] == data["tenant_id"]
        assert me_data["role"] == "owner"

        # 12. GET /google/login for non-existent tenant should return 404
        google_404 = await client.get(
            "/api/v1/auth/google/login",
            params={"tenant_slug": "non-existent-tenant-xyz"},
        )
        assert google_404.status_code == 404

        # 13. GET /google/login for existing tenant should redirect to Google OAuth
        google_login_res = await client.get(
            "/api/v1/auth/google/login",
            params={"tenant_slug": tenant_slug},
            follow_redirects=False,
        )
        assert google_login_res.status_code in (302, 307)
        assert "accounts.google.com" in google_login_res.headers.get("location", "")

        # 14. GET /google/callback with session context but without valid Google auth code -> 401
        cb_res = await client.get("/api/v1/auth/google/callback")
        assert cb_res.status_code == 401

    # 15. GET /google/callback without tenant session cookie -> 400
    async with AsyncClient(transport=transport, base_url="http://test") as fresh_client:
        no_session_cb = await fresh_client.get("/api/v1/auth/google/callback")
        assert no_session_cb.status_code == 400
