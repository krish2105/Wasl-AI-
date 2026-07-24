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


async def test_unimplemented_routes_answer_501_not_fabricated_data(
    client: AsyncClient,
) -> None:
    """A stub that returns plausible output survives into a demo. These do not."""
    for method, path in [
        ("POST", "/api/scan"),
        ("GET", "/api/scan/abc/events"),
        ("GET", "/api/scan/abc"),
        ("GET", "/api/scan/abc/artifacts.zip"),
        ("GET", "/api/leaderboard"),
    ]:
        response = await client.request(method, path)
        assert response.status_code == 501, f"{method} {path}"
        assert "Phase" in response.json()["detail"]
