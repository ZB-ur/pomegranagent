def test_health_returns_frozen_runtime_versions(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {
        "release_id": "2026.09.02-server-capabilities.1",
        "api_version": "3",
        "schema_version": "3",
        "db_mode": "test",
        "analysis_worker_status": "not_started",
    }


def test_version_manifest_is_no_store(client):
    response = client.get("/version.json")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "release_id": "2026.09.02-server-capabilities.1",
        "api_version": "3",
        "schema_version": "3",
    }


def test_health_stays_frozen_if_manifest_changes(client, monkeypatch, tmp_path):
    import app.backend.main as main_module

    changed = tmp_path / "version.json"
    changed.write_text(
        '{"release_id":"new-disk","api_version":"3","schema_version":"3"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(main_module, "VERSION_FILE", changed)
    assert client.get("/version.json").json()["release_id"] == "new-disk"
    assert client.get("/api/health").json()["release_id"] == (
        "2026.09.02-server-capabilities.1"
    )
