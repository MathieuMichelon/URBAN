"""Tests for the single-service FastAPI deployment surface."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import create_app


def test_fastapi_serves_browser_frontend() -> None:
    """The Render web service should return the browser app from `/`."""
    app = create_app(Path(__file__).resolve().parents[1] / "data" / "cards.json")

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "Urban Duel Online" in response.text
    assert 'src="./app.js"' in response.text


def test_fastapi_serves_shared_assets() -> None:
    """Card illustrations and manifests stay available under `/assets/...`."""
    app = create_app(Path(__file__).resolve().parents[1] / "data" / "cards.json")

    with TestClient(app) as client:
        response = client.get("/assets/cards/manifest.json")

    assert response.status_code == 200
    assert len(response.json()["entries"]) == 30


def test_health_endpoint_stays_available_next_to_static_frontend() -> None:
    """The static frontend mount must not shadow operational endpoints."""
    app = create_app(Path(__file__).resolve().parents[1] / "data" / "cards.json")

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
