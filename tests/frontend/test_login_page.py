"""登录/注册页面（templates/login.html）单元测试。

独立验证实现 agent 的 F5 登录界面缺口修复：
1. GET /login 返回 200，渲染登录页关键元素（标题、登录表单、注册表单）。
2. 双 tab（登录/注册）切换元素齐全。
3. 说明文案存在。
4. 页面继承 base.html：aside.sidebar、nav.top-nav 五链接、topbar 登录入口齐全。
"""
from __future__ import annotations

from typing import Any

import pytest

from backend.app import create_app

# 五个导航链接：href → 链接文本（base.html 继承渲染）
_NAV_LINKS: dict[str, str] = {
    "/": "首页",
    "/batch": "批量批改",
    "/bank": "分类题库",
    "/guide": "使用教程",
    "/me": "个人主页",
}


@pytest.fixture
def client() -> Any:
    """构造 Flask 测试客户端（默认游客态）。"""
    app = create_app()
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret-key"
    return app.test_client()


def _login_html(client: Any) -> str:
    """请求 /login 并返回渲染后的 HTML，同时断言 200。"""
    resp = client.get("/login")
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


def test_login页面_返回200并渲染标题(client: Any) -> None:
    """GET /login 返回 200，<title> 含「登录/注册」。"""
    resp = client.get("/login")
    assert resp.status_code == 200
    assert resp.mimetype == "text/html"
    html = resp.get_data(as_text=True)
    assert "<title>登录/注册 - 智能作业批改系统</title>" in html


def test_login页面_含登录表单(client: Any) -> None:
    """登录表单：用户名/密码输入与登录提交按钮齐全。"""
    html = _login_html(client)
    assert '<form id="loginForm" class="auth-form active">' in html
    assert '<input type="text" id="loginUsername"' in html
    assert '<input type="password" id="loginPassword"' in html
    assert '<button type="submit" class="auth-submit">登录</button>' in html


def test_login页面_含注册表单(client: Any) -> None:
    """注册表单：用户名/密码/确认密码输入与注册提交按钮齐全。"""
    html = _login_html(client)
    assert '<form id="registerForm" class="auth-form">' in html
    assert '<input type="text" id="registerUsername"' in html
    assert '<input type="password" id="registerPassword"' in html
    assert '<input type="password" id="registerPasswordConfirm"' in html
    assert '<button type="submit" class="auth-submit">注册</button>' in html


def test_login页面_注册表单含昵称输入(client: Any) -> None:
    """注册表单含「昵称（可选）」输入框。"""
    html = _login_html(client)
    assert '<input type="text" id="registerNickname"' in html
    assert "昵称（可选）" in html


def test_login页面_双tab切换元素齐全(client: Any) -> None:
    """页面含「登录」与「注册」两个 tab 元素（登录 tab 默认激活）。"""
    html = _login_html(client)
    assert '<button type="button" class="auth-tab active" id="loginTab">登录</button>' in html
    assert '<button type="button" class="auth-tab" id="registerTab">注册</button>' in html


def test_login页面_含说明文案(client: Any) -> None:
    """页面含登录后同步个人批改记录的说明文案。"""
    html = _login_html(client)
    assert "登录后可同步个人批改记录与收藏" in html


def test_login页面_继承base含侧边栏导航与topbar(client: Any) -> None:
    """页面继承 base.html：aside.sidebar、nav.top-nav 五链接、topbar 登录入口齐全。"""
    html = _login_html(client)
    assert '<aside class="sidebar">' in html
    assert '<nav class="top-nav">' in html
    assert '<header class="topbar">' in html
    for href, label in _NAV_LINKS.items():
        assert f'<a href="{href}" class="nav-item' in html, f"缺导航链接 {href}"
        assert label in html, f"缺导航文本 {label}"
    # 游客态 topbar 内渲染登录 / 注册入口
    assert '<a class="nav-item" href="/login">登录 / 注册</a>' in html
