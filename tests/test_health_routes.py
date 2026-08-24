"""app/health_routes 健康检查路由单元测试（task/26 D3 单环境收敛）。

GET /health 是 healthcheck.py 三进程探测的主应用入口，返回 200 + {"status": "ok"}
与嵌入/OCR 微服务 /health 保持同构。用 Flask test_client 断言，离线运行。
"""
from __future__ import annotations

from typing import Any, Generator

import pytest

from app import create_app


@pytest.fixture
def client() -> Generator[Any, None, None]:
    """基础 Flask 测试客户端（健康路由不依赖存储，无需隔离 db）。"""
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_health_route_ok(client) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


def test_health_route_rejects_post(client) -> None:
    resp = client.post("/health")
    assert resp.status_code == 405
