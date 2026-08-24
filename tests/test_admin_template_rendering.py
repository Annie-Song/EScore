"""admin.html 管理页模板渲染单元测试（F10 学校管理员权限体系）。

覆盖：admin 视角 h1 标题「学校管理」、新建学校卡片存在、currentRole 注入 admin、
成员角色 select 的 JS 渲染分支存在；school_admin 视角 h1 标题「本校管理」、
新建学校卡片隐藏、currentRole 注入 school_admin（JS 将渲染纯文本角色）；游客
无新建学校卡片且 currentRole 为空。离线独立运行。
"""
from __future__ import annotations

from typing import Any

import pytest

from app import create_app

_CREATE_CARD = 'id="createSchoolBtn"'


@pytest.fixture
def client() -> Any:
    """函数级 Flask 测试客户端，避免会话状态在用例间串扰。"""
    app = create_app()
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret-key"
    return app.test_client()


def _set_role(client: Any, role: str) -> None:
    """写入指定角色的会话；school_admin 额外带 school_id。"""
    with client.session_transaction() as sess:
        sess.clear()
        sess["user_id"] = "u-1"
        sess["display_name"] = "测试"
        sess["role"] = role
        sess["plan"] = "free"
        if role == "school_admin":
            sess["school_id"] = "s1"


def _admin_html(client: Any) -> str:
    """请求 /admin 并返回渲染 HTML，同时断言 200。"""
    resp = client.get("/admin")
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


def test_admin_view_shows_manage_title_and_create_card(client: Any) -> None:
    """admin 视角：h1「学校管理」、新建学校卡片存在、currentRole 为 admin。"""
    _set_role(client, "admin")
    html = _admin_html(client)
    assert "<h1>学校管理</h1>" in html
    assert _CREATE_CARD in html
    assert 'const currentRole = "admin";' in html


def test_school_admin_view_shows_own_title_and_hides_create_card(client: Any) -> None:
    """school_admin 视角：h1「本校管理」、新建学校卡片隐藏、currentRole 为 school_admin。"""
    _set_role(client, "school_admin")
    html = _admin_html(client)
    assert "<h1>本校管理</h1>" in html
    assert "<h1>学校管理</h1>" not in html
    assert _CREATE_CARD not in html
    assert 'const currentRole = "school_admin";' in html


def test_guest_view_manage_title_no_create_card(client: Any) -> None:
    """游客视角：h1「学校管理」、无新建学校卡片、currentRole 为空。"""
    html = _admin_html(client)
    assert "<h1>学校管理</h1>" in html
    assert _CREATE_CARD not in html
    assert 'const currentRole = "";' in html


def test_admin_view_role_select_js_branch_present(client: Any) -> None:
    """admin 视角：模板含成员角色 select 渲染分支（currentRole === 'admin'）。"""
    _set_role(client, "admin")
    html = _admin_html(client)
    assert 'currentRole === "admin"' in html
    assert '<select class="role-select" data-user-id="' in html


def test_school_admin_view_js_renders_text_role(client: Any) -> None:
    """school_admin 视角：currentRole 为 school_admin，JS 走纯文本角色分支。"""
    _set_role(client, "school_admin")
    html = _admin_html(client)
    assert 'const currentRole = "school_admin";' in html
    # JS 三元仅在 currentRole === 'admin' 时渲染 select，school_admin 走 escapeHtml 纯文本
    assert 'currentRole === "admin"' in html
