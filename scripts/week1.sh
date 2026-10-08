#!/bin/bash
set -e
# Week 1 milestone demo: fresh infra, migrate, test, and prove tenancy end-to-end.
# NOTE: wipes local dev data (down -v) for a true clean-slate demo.

echo "=== 1. Fresh infra ==="
docker compose -f infra/docker-compose.yml down -v
docker compose -f infra/docker-compose.yml up -d
until docker compose -f infra/docker-compose.yml exec -T postgres pg_isready -U platform; do sleep 1; done

echo "=== 2. Migrate ==="
uv run alembic upgrade head

echo "=== 3. Start API ==="
uv run uvicorn main:app --app-dir apps/api --port 8000 &
API_PID=$!
sleep 4
trap "kill $API_PID 2>/dev/null || true" EXIT

echo "=== 4. Pytest (isolation gate) ==="
uv run pytest -q

echo "=== 5. Milestone checks ==="
if command -v python3 >/dev/null 2>&1 && python3 -c "" 2>/dev/null; then
    PY_CMD="python3"
else
    PY_CMD="python"
fi

$PY_CMD - << 'EOF'
import json, urllib.request, urllib.error

BASE = "http://localhost:8000/api/v1"

def req(method, path, token=None, api_key=None, body=None):
    r = urllib.request.Request(BASE + path, method=method,
        data=json.dumps(body).encode() if body is not None else None)
    if body is not None:
        r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", f"Bearer {token}")
    if api_key:
        r.add_header("X-API-Key", api_key)
    try:
        with urllib.request.urlopen(r) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, None

def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    assert cond, name

ta = req("POST", "/auth/signup", body={"tenant_name": "Acme", "email": "a@acme.test", "password": "password123"})
tb = req("POST", "/auth/signup", body={"tenant_name": "Globex", "email": "b@globex.test", "password": "password123"})
check("signup tenant A → 201", ta[0] == 201)
check("signup tenant B → 201", tb[0] == 201)
TA, TB = ta[1]["access_token"], tb[1]["access_token"]

ag = req("POST", "/agents", token=TA, body={"name": "invoice-bot"})
check("A creates agent → 201", ag[0] == 201)
aid = ag[1]["id"]

v1 = req("POST", f"/agents/{aid}/versions", token=TA, body={"config": {"model": "gpt-4o-mini"}})
v2 = req("POST", f"/agents/{aid}/versions", token=TA, body={"config": {"model": "gpt-4o"}})
check("v1 registered", v1[0] == 201 and v1[1]["version"] == 1)
check("v2 registered", v2[0] == 201 and v2[1]["version"] == 2)

g1 = req("GET", f"/agents/{aid}/versions/1", token=TA)
check("v1 immutable + retrievable", g1[0] == 200 and g1[1]["config"] == {"model": "gpt-4o-mini"})

c = req("GET", f"/agents/{aid}", token=TB)
check("B reads A's agent → 404 (not 403)", c[0] == 404)
l = req("GET", "/agents", token=TB)
check("B sees only its own agents", l[0] == 200 and l[1] == [])

k = req("POST", "/auth/api-keys", token=TA, body={"name": "ci"})
check("API key created", k[0] == 201)
kl = req("GET", "/agents", api_key=k[1]["key"])
check("API key authenticates", kl[0] == 200 and len(kl[1]) == 1)

print("\nWEEK 1 MILESTONE: ALL GREEN")
EOF
