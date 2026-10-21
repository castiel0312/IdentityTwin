from unittest.mock import patch

from fastapi.testclient import TestClient


def test_health_endpoint_liveness(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data
    assert "environment" in data
    assert "timestamp" in data


def test_ready_endpoint_success(client: TestClient):
    response = client.get("/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["database"] == "connected"


def test_ready_endpoint_db_failure(client: TestClient):
    with patch("app.api.routes.health.check_db_ready", return_value=False):
        response = client.get("/ready")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unavailable"
        assert data["database"] == "unhealthy"
