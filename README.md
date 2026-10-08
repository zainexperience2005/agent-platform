# Agent Platform

Multi-tenant AI agent platform — built week by week from the 8-week roadmap.
Control plane (tenants, auth, registry) → runtime workers → gateways → memory/RAG → policy → eval → K8s → load tests.

## Quickstart
uv sync
docker compose -f infra/docker-compose.yml up -d
uv run uvicorn agent_platform.apps.api.main:app --reload
