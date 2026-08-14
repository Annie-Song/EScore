"""/guide 快速开始教程页路由与入口回归单元测试。

独立验证实现 agent 的 F6 前端体验优化：
1. GET /guide 渲染静态模板 guide.html（200、text/html、含关键内容块）。
2. 首页 / 与批量页 /batch 均包含指向 /guide 的入口链接。
3. app/routes.py 公开函数仍不超过 5 个（模块约束门禁）。
"""
import inspect

import pytest

from app import create_app


@pytest.fixture
def client():
    """构造 Flask 测试客户端。"""
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _guide_html(client) -> str:
    """请求 /guide 并返回渲染后的 HTML。"""
    resp = client.get("/guide")
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


def test_guide_route_returns_200_html(client):
    """GET /guide 返回 200，Content-Type 为 text/html。"""
    resp = client.get("/guide")
    assert resp.status_code == 200
    assert resp.mimetype == "text/html"


def test_guide_contains_usage_tutorial_title(client):
    """/guide 页面标题块包含“使用教程”。"""
    html = _guide_html(client)
    assert "使用教程" in html


def test_guide_contains_single_photo_mode(client):
    """/guide 包含“方式一：单图快速批改”操作步骤块。"""
    html = _guide_html(client)
    assert "方式一：单图快速批改" in html


def test_guide_contains_batch_mode(client):
    """/guide 包含“方式二：批量批改”操作步骤块。"""
    html = _guide_html(client)
    assert "方式二：批量批改" in html


def test_guide_contains_feature_notes(client):
    """/guide 包含“功能说明”特性说明块。"""
    html = _guide_html(client)
    assert "功能说明" in html


def test_index_contains_guide_link(client):
    """首页 HTML 包含指向 /guide 的“使用教程”入口链接。"""
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'href="/guide"' in html
    assert "使用教程" in html


def test_batch_contains_guide_link(client):
    """批量批改页 HTML 包含指向 /guide 的“使用教程”入口链接。"""
    resp = client.get("/batch")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'href="/guide"' in html
    assert "使用教程" in html


def test_routes_public_functions_still_within_limit():
    """app/routes.py 公开函数不超过 5 个（模块约束门禁）。"""
    import app.routes as routes_mod

    public_funcs = [
        name
        for name, func in inspect.getmembers(routes_mod, inspect.isfunction)
        if func.__module__ == "app.routes" and not name.startswith("_")
    ]
    assert len(public_funcs) <= 5
