"""Health endpoint, against real Postgres and Redis.

The assertion worth having here is the negative one: /health must report 503 when
a dependency is down. A health check that stays green through an outage is worse
than none, because it converts a visible failure into a silent one.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.infra


async def test_health_reports_ok_with_dependencies_up(
    client: AsyncClient, require_infra: None
) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"]["database"]["ok"] is True
    assert body["checks"]["redis"]["ok"] is True
    assert body["version"]


async def test_health_surfaces_crawler_identity_configuration(
    client: AsyncClient, require_infra: None
) -> None:
    """Whether this deployment is permitted to crawl is visible from outside."""
    body = (await client.get("/health")).json()
    assert "crawler_identity_configured" in body
    assert isinstance(body["crawler_identity_configured"], bool)


async def test_health_reports_503_when_the_database_is_unreachable(
    monkeypatch: pytest.MonkeyPatch, client: AsyncClient, require_infra: None
) -> None:
    async def _down() -> tuple[bool, str]:
        return False, "ConnectionRefusedError: simulated outage"

    monkeypatch.setattr("wasl.main._check_database", _down)

    response = await client.get("/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["database"]["ok"] is False
    assert "simulated outage" in body["checks"]["database"]["detail"]


async def test_still_unimplemented_routes_answer_501_not_fabricated_data(
    client: AsyncClient,
) -> None:
    """A stub returning plausible output survives into a demo. This one does not."""
    response = await client.get("/api/leaderboard")
    assert response.status_code == 501
    assert "Phase" in response.json()["detail"]


async def test_unknown_jobs_are_404_not_empty_results(client: AsyncClient) -> None:
    """An empty report for a job that never existed reads as 'nothing found'."""
    for path in [
        "/api/scan/does-not-exist",
        "/api/scan/does-not-exist/events",
        "/api/scan/does-not-exist/artifacts.zip",
    ]:
        response = await client.get(path)
        assert response.status_code == 404, path


async def test_a_scan_needs_a_url_or_a_fixture(client: AsyncClient) -> None:
    response = await client.post("/api/scan", json={})
    assert response.status_code == 422
    assert "url or a fixture" in response.json()["detail"]


async def test_plain_http_urls_are_rejected_before_a_job_is_created(
    client: AsyncClient,
) -> None:
    """The https-only rule belongs at the edge, not halfway through a crawl."""
    response = await client.post("/api/scan", json={"url": "http://example.com"})
    assert response.status_code == 422
