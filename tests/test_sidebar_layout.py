"""task/21 侧边导航栏改造（templates/base.html 顶部导航 → aside.sidebar 纵向导航）单元测试。

独立验证实现 agent 的侧边栏改造：
1. 五个导航入口（首页/批量批改/分类题库/使用教程/个人主页）齐全，href 正确、class 含 nav-item。
2. 四个存在的页面路由（/、/batch、/bank、/guide）各自当前页高亮 active，其余不带 active。
   （/me 页面路由由 task/22 交付，此处不直接请求 /me。）
3. aside.sidebar 内含 #themeToggle 主题开关；#notification/#notificationMessage 通知容器存在；
   main.main-content 内容区存在。
4. 游客态：GET / 无 session 时渲染「登录 / 注册」链接；登录态：session 写入
   user_id/display_name/role/plan 后渲染昵称、个人主页链接与退出按钮。
   （/api/auth/logout 端点由 task/22 交付，此处只断言按钮存在，不发起真实 POST。）
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app import create_app

_BASE_DIR = Path(__file__).resolve().parent.parent
_TEMPLATE_DIR = _BASE_DIR / "templates"

# 五个导航链接：href → 链接文本
_NAV_LINKS: dict[str, str] = {
    "/": "首页",
    "/batch": "批量批改",
    "/bank": "分类题库",
    "/guide": "使用教程",
    "/me": "个人主页",
}

# 当前存在页面的路由（/me 路由尚未交付，不纳入 active 断言）
_EXISTING_ROUTES: tuple[str, ...] = ("/", "/batch", "/bank", "/guide")

_LOGIN_SESSION: dict[str, Any] = {
    "user_id": 1,
    "display_name": "测试用户",
    "role": "user",
    "plan": "free",
}


@pytest.fixture(scope="module")
def client() -> Any:
    """模块级共享的 Flask 测试客户端（TESTING 模式）。

    session_transaction 依赖签名会话，需配置 SECRET_KEY（仅测试用）。
    """
    app = create_app()
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret-key"
    return app.test_client()


def _get_html(client: Any, path: str) -> str:
    """请求 path 并返回渲染后的 HTML，同时断言 200。"""
    resp = client.get(path)
    assert resp.status_code == 200, f"{path} 渲染失败"
    return resp.get_data(as_text=True)


def _clear_session(client: Any) -> None:
    """清空客户端 session，保证游客态测试不受前序登录态污染。"""
    with client.session_transaction() as sess:
        sess.clear()


def test_导航_五个链接href正确class含navitem(client: Any) -> None:
    """GET / 渲染结果含五个导航链接，href 正确、class 含 nav-item。"""
    html = _get_html(client, "/")
    for href, label in _NAV_LINKS.items():
        assert f'<a href="{href}" class="nav-item' in html, f"缺导航链接 {href}"
        assert label in html, f"缺导航文本 {label}"


@pytest.mark.parametrize("path", _EXISTING_ROUTES)
def test_导航_当前页高亮且其余不活跃(client: Any, path: str) -> None:
    """当前页对应 nav-item 带 active，其余五个链接不带 active。"""
    html = _get_html(client, path)
    for href, label in _NAV_LINKS.items():
        active_link = f'<a href="{href}" class="nav-item active">{label}</a>'
        plain_link = f'<a href="{href}" class="nav-item">{label}</a>'
        if href == path:
            assert active_link in html, f"{path} 当前导航 {href} 应高亮"
            assert plain_link not in html, f"{path} 当前导航 {href} 不应是普通态"
        else:
            assert plain_link in html, f"{path} 导航 {href} 应为普通态"
            assert active_link not in html, f"{path} 导航 {href} 不应高亮"


def test_结构_侧边栏含主题开关内容区通知容器(client: Any) -> None:
    """aside.sidebar 内含 #themeToggle；main.main-content 存在；通知容器两 id 齐全。"""
    html = _get_html(client, "/")
    assert '<aside class="sidebar">' in html
    sidebar_inner = html.split('<aside class="sidebar">', 1)[1].split("</aside>", 1)[0]
    assert 'id="themeToggle"' in sidebar_inner, "#themeToggle 应在 aside.sidebar 内"
    assert '<main class="main-content">' in html
    assert 'id="notification"' in html
    assert 'id="notificationMessage"' in html


def test_游客态_显示登录注册链接(client: Any) -> None:
    """无 session 时 GET / 渲染 topbar 内「登录 / 注册」链接（指向 /login），不渲染退出按钮。"""
    _clear_session(client)
    html = _get_html(client, "/")
    # 登录 / 注册入口位于 main.main-content 的 topbar 内，而非 aside.sidebar 内
    main_part = html.split('<main class="main-content">', 1)[1]
    topbar_part = main_part.split('<header class="topbar">', 1)[1].split("</header>", 1)[0]
    assert '<a class="nav-item" href="/login">登录 / 注册</a>' in topbar_part
    sidebar_part = html.split('<aside class="sidebar">', 1)[1].split("</aside>", 1)[0]
    assert '<a class="nav-item" href="/login">登录 / 注册</a>' not in sidebar_part
    assert "退出" not in html


def test_登录态_显示用户信息与退出按钮(client: Any) -> None:
    """session 写入 user_id/display_name/role/plan 后，渲染昵称、个人主页链接与退出按钮。"""
    with client.session_transaction() as sess:
        for key, value in _LOGIN_SESSION.items():
            sess[key] = value
    html = _get_html(client, "/")
    assert '<span class="user-name">测试用户</span>' in html
    assert '<span class="user-avatar">测</span>' in html
    assert '<a class="user-link" href="/me">个人主页</a>' in html
    assert '<form method="post" action="/api/auth/logout"' in html
    assert '<button type="submit" class="btn-secondary user-logout">退出</button>' in html
    assert "登录 / 注册" not in html


def test_base模板_含侧边栏与五入口() -> None:
    """base.html 直接内容：aside.sidebar、五个导航入口、主题开关、通知消息容器。"""
    html = (_TEMPLATE_DIR / "base.html").read_text(encoding="utf-8")
    assert '<aside class="sidebar">' in html
    assert '<nav class="top-nav">' in html
    assert '<div class="sidebar-footer">' in html
    assert '<main class="main-content">' in html
    for href, label in _NAV_LINKS.items():
        assert f'href="{href}"' in html, f"缺导航链接 {href}"
        assert label in html, f"缺导航文本 {label}"
    assert 'class="nav-item' in html
    assert 'id="themeToggle"' in html
    assert 'id="notificationMessage"' in html
