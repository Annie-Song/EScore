"""task/16 前端重构（templates/base.html 统一布局 + static/ 外置公共资源）单元测试。

独立验证实现 agent 的公共布局重构：
1. 四个页面（/、/batch、/bank、/guide）均 extends base.html，全部 200 渲染无 Jinja 报错。
2. 每页渲染结果都包含统一顶部导航 4 个链接（首页/批量批改/分类题库/使用教程），
   且当前页高亮 active 类唯一落在当前链接上（base 继承生效）。
3. 标题：batch 页为「批量作业批改 - 智能作业批改系统」，其余页含「智能作业批改系统」。
4. 静态资源 /static/app.css、/static/app.js 返回 200。
5. 每页渲染结果含主题开关（#themeToggle）与通知容器（#notification），均来自 base。
6. 首页含比对评分步骤编号（4/5）与结果区「重新批改」「去批量批改」按钮。
7. base.html / static/app.js / static/app.css 三个公共文件直接内容抽查。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app import create_app

_BASE_DIR = Path(__file__).resolve().parent.parent
_TEMPLATE_DIR = _BASE_DIR / "templates"
_STATIC_DIR = _BASE_DIR / "static"

# 页面路径 → (标题精确片段，页面内 h1 标题)
_PAGES: dict[str, tuple[str, str]] = {
    "/": ("智能作业批改系统", "智能作业批改系统"),
    "/batch": ("批量作业批改 - 智能作业批改系统", "批量作业批改"),
    "/bank": ("分类题库 - 智能作业批改系统", "分类题库"),
    "/guide": ("使用教程 - 智能作业批改系统", "使用教程"),
}

# 统一导航 4 个链接：href → 链接文本
_NAV_LINKS: list[tuple[str, str]] = [
    ("/", "首页"),
    ("/batch", "批量批改"),
    ("/bank", "分类题库"),
    ("/guide", "使用教程"),
]


@pytest.fixture(scope="module")
def client() -> Any:
    """模块级共享的 Flask 测试客户端（TESTING 模式）。"""
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _get_html(client: Any, path: str) -> str:
    """请求 path 并返回渲染后的 HTML，同时断言 200 + text/html。"""
    resp = client.get(path)
    assert resp.status_code == 200, f"{path} 渲染失败"
    assert resp.mimetype == "text/html", f"{path} 不是 text/html"
    return resp.get_data(as_text=True)


def test_四页面渲染200无jinja报错(client: Any) -> None:
    """四个页面全部 200 且渲染出完整 HTML 文档。"""
    for path in _PAGES:
        html = _get_html(client, path)
        assert "<!DOCTYPE html>" in html, path


def test_每页统一导航四链接齐全(client: Any) -> None:
    """每页渲染结果都含统一导航 4 个链接（base 继承生效）。"""
    for path in _PAGES:
        html = _get_html(client, path)
        for href, label in _NAV_LINKS:
            assert f'href="{href}"' in html, f"{path} 缺导航链接 {href}"
            assert label in html, f"{path} 缺导航文本 {label}"


def test_每页导航当前页高亮唯一(client: Any) -> None:
    """当前页链接带 active 类，其余三个链接不带 active。"""
    for path in _PAGES:
        html = _get_html(client, path)
        for href, label in _NAV_LINKS:
            active_link = f'<a href="{href}" class="nav-item active">{label}</a>'
            plain_link = f'<a href="{href}" class="nav-item">{label}</a>'
            if href == path:
                assert active_link in html, f"{path} 当前导航 {href} 应高亮"
                assert plain_link not in html, f"{path} 当前导航 {href} 不应是普通态"
            else:
                assert plain_link in html, f"{path} 导航 {href} 应为普通态"
                assert active_link not in html, f"{path} 导航 {href} 不应高亮"


def test_guide含分类题库链接(client: Any) -> None:
    """/guide 渲染结果含分类题库入口链接（P1 修复点，经统一导航提供）。"""
    html = _get_html(client, "/guide")
    assert 'href="/bank"' in html
    assert "分类题库" in html


def test_batch页标题为批量作业批改(client: Any) -> None:
    """/batch 的 <title> 为「批量作业批改 - 智能作业批改系统」。"""
    html = _get_html(client, "/batch")
    assert "<title>批量作业批改 - 智能作业批改系统</title>" in html


def test_其余页标题含智能作业批改系统(client: Any) -> None:
    """首页/题库/教程三页 <title> 均含「智能作业批改系统」。"""
    for path in ("/", "/bank", "/guide"):
        html = _get_html(client, path)
        assert "<title>" in html and "智能作业批改系统" in html.split("</title>")[0], path


def test_静态资源app_css与app_js可访问(client: Any) -> None:
    """GET /static/app.css 与 /static/app.js 返回 200，MIME 正确。"""
    resp_css = client.get("/static/app.css")
    assert resp_css.status_code == 200
    assert resp_css.mimetype in ("text/css", "text/css; charset=utf-8")
    resp_js = client.get("/static/app.js")
    assert resp_js.status_code == 200
    assert "javascript" in resp_js.mimetype


def test_每页含主题开关与通知容器(client: Any) -> None:
    """每页渲染结果都含 #themeToggle 与 #notification（base 渲染生效）。"""
    for path in _PAGES:
        html = _get_html(client, path)
        assert 'id="themeToggle"' in html, path
        assert 'id="notification"' in html, path


def test_首页比对评分与下载步骤编号(client: Any) -> None:
    """首页卡片步骤编号 4（比对评分）与 5（下载批改结果）齐全。"""
    html = _get_html(client, "/")
    assert '<span>4</span>比对评分' in html
    assert '<span>5</span>下载批改结果' in html


def test_首页结果区重新批改与去批量批改按钮(client: Any) -> None:
    """首页结果区含「重新批改」「去批量批改」按钮元素。"""
    html = _get_html(client, "/")
    assert 'id="resetResultBtn"' in html
    assert "重新批改" in html
    assert 'id="goBatchBtn"' in html
    assert "去批量批改" in html


def test_base含统一导航主题开关与通知容器() -> None:
    """base.html 直接内容：统一导航 4 链接、主题开关、通知容器、引用 static 公共资源。"""
    html = (_TEMPLATE_DIR / "base.html").read_text(encoding="utf-8")
    for href, label in _NAV_LINKS:
        assert f'href="{href}"' in html
        assert label in html
    assert 'id="themeToggle"' in html
    assert 'id="notification"' in html
    assert 'href="/static/app.css"' in html
    assert 'src="/static/app.js"' in html
    assert "{% block styles %}" in html
    assert "{% block scripts %}" in html


def test_app_js含共享函数() -> None:
    """static/app.js 直接内容：escapeHtml/showNotification/initTheme 三个共享函数齐全。"""
    js = (_STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "function escapeHtml(" in js
    assert "function showNotification(" in js
    assert "function initTheme(" in js


def test_app_css含主题与导航样式() -> None:
    """static/app.css 直接内容：设计 token、主题开关、统一导航样式齐全。"""
    css = (_STATIC_DIR / "app.css").read_text(encoding="utf-8")
    assert "--primary-color" in css
    assert '[data-theme="dark"]' in css
    assert ".top-nav" in css
    assert ".nav-item" in css
    assert ".theme-switch" in css
    assert ".notification" in css
