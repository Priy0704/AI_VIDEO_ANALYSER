import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_auth_me():
    """Verify user identity profile endpoint."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        res = await client.get("/api/v1/auth/me", headers={"X-User-Email": "priyanka@acme.com"})
        assert res.status_code == 200
        data = res.json()
        assert data["email"] == "priyanka@acme.com"
        assert data["role"] == "org_admin"
        assert "organization" in data


@pytest.mark.asyncio
async def test_cost_estimation():
    """Verify pre-processing video cost estimation."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        res = await client.get("/api/v1/costs/estimate?duration_seconds=300")
        assert res.status_code == 200
        data = res.json()
        assert data["duration_minutes"] == 5.0
        assert data["estimated_total_cost"] > 0.0


@pytest.mark.asyncio
async def test_projects_crud():
    """Verify Projects creation and listing."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        # Create project
        create_res = await client.post(
            "/api/v1/projects",
            json={"name": "Test CCTV Inspection", "description": "Automated test project container"},
            headers={"X-User-Email": "priyanka@acme.com"}
        )
        assert create_res.status_code == 200
        p_data = create_res.json()
        assert p_data["name"] == "Test CCTV Inspection"

        # List projects
        list_res = await client.get("/api/v1/projects", headers={"X-User-Email": "priyanka@acme.com"})
        assert list_res.status_code == 200
        projects = list_res.json()
        assert any(p["name"] == "Test CCTV Inspection" for p in projects)


@pytest.mark.asyncio
async def test_analytics_and_observability():
    """Verify enterprise analytics and observability metrics endpoints."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        analytics_res = await client.get("/api/v1/analytics/summary", headers={"X-User-Email": "priyanka@acme.com"})
        assert analytics_res.status_code == 200
        a_data = analytics_res.json()
        assert "videos_processed" in a_data
        assert "total_ai_spend_usd" in a_data

        obs_res = await client.get("/api/v1/observability/metrics", headers={"X-User-Email": "priyanka@acme.com"})
        assert obs_res.status_code == 200
        o_data = obs_res.json()
        assert o_data["system_health"]["status"] in ["Healthy", "Degraded"]


@pytest.mark.asyncio
async def test_audit_logs():
    """Verify audit log tracking endpoint."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        res = await client.get("/api/v1/audit-logs", headers={"X-User-Email": "priyanka@acme.com"})
        assert res.status_code == 200
        logs = res.json()
        assert isinstance(logs, list)
