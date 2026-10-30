from fastapi.testclient import TestClient

from firstweek_api import main
from firstweek_core import __version__

client = TestClient(main.app)


def test_health_is_dependency_free() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_ready_reports_each_dependency(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    async def ok() -> None:
        return None

    async def down() -> None:
        raise ConnectionError("no redis")

    monkeypatch.setattr(main, "_check_database", lambda: None)
    monkeypatch.setattr(main, "_check_redis", down)
    monkeypatch.setattr(main, "_check_temporal", ok)

    response = client.get("/ready")
    body = response.json()
    assert response.status_code == 503
    assert body["checks"] == {
        "database": "ok",
        "redis": "error: ConnectionError",
        "temporal": "ok",
    }
