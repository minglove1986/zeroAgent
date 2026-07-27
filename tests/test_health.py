"""健康检查。

@author 赵振明
@date 2026-07-21 16:58:11
"""

from fastapi.testclient import TestClient

from app.main import create_app


def test_health_ok() -> None:
    with TestClient(create_app()) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


def test_runtime_info() -> None:
    with TestClient(create_app()) as client:
        resp = client.get("/api/v1/runtime")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert "litellm_model" in body["data"]
        assert "mock_external" in body["data"]
