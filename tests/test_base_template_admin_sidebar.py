"""base.html 管理侧栏入口与升级按钮模板渲染单元测试（F5）。

覆盖：
1. base.html 的 admin 侧栏入口：session.role=='admin' 渲染「学校管理」链接，
   teacher/游客不渲染。
2. base.html 直接内容含 admin 条件渲染标记。
3. me.html 升级按钮元素与升级页价格占位存在（若可测则测的按钮行为部分）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app import create_app

_BASE_DIR = Path(__file__).resolve().parent.parent
_TEMPLATE_DIR = _BASE_DIR / "templates"

_ADMIN_ENTRY = "学校管理"
_ADMIN_HREF = 'href="/admin"'


@pytest.fixture
def client() -> Any:
    """函数级 Flask 测试客户端，避免会话状态在用例间串扰。"""
    app = create_app()
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret-key"
    return app.test_client()


def _set_role(client: Any, role: str | None) -> None:
    """写入指定角色的会话；role=None 表示游客（清空会话）。"""
    with client.session_transaction() as sess:
        sess.clear()
        if role is not None:
            sess["user_id"] = "u-1"
            sess["display_name"] = "测试"
            sess["role"] = role
            sess["plan"] = "free"


def _sidebar_html(client: Any, path: str = "/") -> str:
    """请求 path 并返回 aside.sidebar 片段，同时断言 200。"""
    resp = client.get(path)
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    return html.split('<aside class="sidebar">', 1)[1].split("</aside>", 1)[0]


def test_admin_session_renders_school_management_link(client: Any) -> None:
    """session.role=='admin'：侧栏渲染「学校管理」入口链接。"""
    _set_role(client, "admin")
    sidebar = _sidebar_html(client)
    assert _ADMIN_HREF in sidebar
    assert _ADMIN_ENTRY in sidebar


def test_admin_sidebar_link_has_admin_active_class(client: Any) -> None:
    """访问 /admin 时管理入口带 active 高亮。"""
    _set_role(client, "admin")
    sidebar = _sidebar_html(client, "/admin")
    assert '<a href="/admin" class="nav-item active">学校管理</a>' in sidebar


def test_teacher_session_hides_school_management(client: Any) -> None:
    """session.role=='teacher'：侧栏不渲染「学校管理」入口。"""
    _set_role(client, "teacher")
    sidebar = _sidebar_html(client)
    assert _ADMIN_ENTRY not in sidebar
    assert _ADMIN_HREF not in sidebar


def test_guest_hides_school_management(client: Any) -> None:
    """游客：侧栏不渲染「学校管理」入口。"""
    _set_role(client, None)
    sidebar = _sidebar_html(client)
    assert _ADMIN_ENTRY not in sidebar
    assert _ADMIN_HREF not in sidebar


def test_base_template_contains_admin_conditional() -> None:
    """base.html 直接内容含 admin/school_admin 条件渲染。"""
    html = (_TEMPLATE_DIR / "base.html").read_text(encoding="utf-8")
    assert "{% if session.get('role') in ('admin', 'school_admin') %}" in html
    assert _ADMIN_HREF in html
    assert _ADMIN_ENTRY in html


def test_school_admin_session_renders_school_management_link(client: Any) -> None:
    """session.role=='school_admin'：侧栏渲染「学校管理」入口链接。"""
    _set_role(client, "school_admin")
    sidebar = _sidebar_html(client)
    assert _ADMIN_HREF in sidebar
    assert _ADMIN_ENTRY in sidebar


def test_me_page_renders_upgrade_button(client: Any) -> None:
    """/me 渲染升级专业版按钮与 id。"""
    html = client.get("/me").get_data(as_text=True)
    assert 'id="upgradeBtn"' in html
    assert "升级专业版" in html


def test_upgrade_page_renders_price_and_pricing(client: Any) -> None:
    """/upgrade 渲染价格占位与 PRICING 配置注入（tojson 已求值为 JSON）。"""
    resp = client.get("/upgrade")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'id="proPrice"' in html
    assert "const PRICING =" in html
    assert '"pro": 9900' in html
