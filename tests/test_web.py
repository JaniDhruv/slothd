"""Tests for the slothd FastAPI web backend and endpoints."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from slothd.web.app import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_status_endpoint(client: TestClient) -> None:
    res = client.get("/api/status")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert "idle_seconds" in data
    assert "version" in data


def test_stats_endpoint(client: TestClient) -> None:
    with patch("slothd.web.routes.scan_directory", return_value=[]):
        res = client.get("/api/stats")
        assert res.status_code == 200
        data = res.json()
        assert "total_operations" in data
        assert "total_batches" in data


def test_scan_endpoint_valid_dir(client: TestClient, tmp_path: Path) -> None:
    (tmp_path / "doc.pdf").write_text("sample doc")
    (tmp_path / "img.png").write_bytes(b"\x89PNG sample img")

    res = client.post("/api/scan", json={"path": str(tmp_path)})
    assert res.status_code == 200
    data = res.json()
    assert data["total_files"] == 2
    assert "Documents" in data["categories"]


def test_scan_endpoint_missing_dir(client: TestClient) -> None:
    res = client.post("/api/scan", json={"path": "C:/nonexistent_sloth_dir_12345"})
    assert res.status_code == 404


def test_preview_endpoint(client: TestClient, tmp_path: Path) -> None:
    (tmp_path / "sample.txt").write_text("some sample text")

    with patch("slothd.web.routes.classify_batch", return_value=[]):
        res = client.post("/api/preview", json={"path": str(tmp_path), "batch_size": 10})
        assert res.status_code == 200
        data = res.json()
        assert "planned_moves" in data


def test_execute_and_undo_flow(client: TestClient, tmp_path: Path) -> None:
    test_file = tmp_path / "receipt.txt"
    test_file.write_text("Uber ride receipt $25.00")

    with patch("slothd.web.routes.classify_batch", return_value=[]):
        # Execute moves
        res = client.post("/api/execute", json={"path": str(tmp_path), "batch_size": 5})
        assert res.status_code == 200
        exec_data = res.json()
        assert "batch_id" in exec_data

        # Undo
        undo_res = client.post("/api/undo")
        assert undo_res.status_code == 200
        undo_data = undo_res.json()
        assert "restored_count" in undo_data


def test_search_endpoint(client: TestClient) -> None:
    res = client.post("/api/search", json={"query": "flight ticket", "limit": 3})
    assert res.status_code == 200
    data = res.json()
    assert data["query"] == "flight ticket"
    assert "results" in data


def test_recent_batches_endpoint(client: TestClient) -> None:
    res = client.get("/api/recent?limit=5")
    assert res.status_code == 200
    data = res.json()
    assert "recent_batches" in data


def test_briefing_endpoints(client: TestClient) -> None:
    with patch("slothd.web.routes.scan_directory", return_value=[]):
        # Briefing metadata
        res = client.get("/api/briefing")
        assert res.status_code == 200
        data = res.json()
        assert "script" in data
        assert "audio_url" in data

        # Audio stream
        audio_res = client.get("/api/briefing/audio")
        assert audio_res.status_code == 200
        assert len(audio_res.content) > 100


def test_index_html_served(client: TestClient) -> None:
    res = client.get("/")
    assert res.status_code == 200
    assert "slothd" in res.text
