"""个人主页与题库收藏按钮模板渲染单元测试（task/22）。

离线独立运行：通过 Flask test_client 渲染 /me 与 /bank，断言页面标题、
四卡片区文案、游客提示、JS 数据端点与收藏按钮标记存在，不访问外网、
不依赖真实用户库与题库库文件。
"""
from __future__ import annotations

from typing import Any

import pytest

from app import create_app

# 四个卡片区关键文案
_CARD_KEYWORDS = ("会员状态", "我的资料", "我的批改记录", "我的卷库")
_GUEST_NOTICE = "登录后可查看个人数据与收藏"


@pytest.fixture
def client() -> Any:
    """函数级 Flask 测试客户端，避免会话状态在用例间串扰。"""
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_me_page_含标题与四卡片(client: Any) -> None:
    """/me 渲染含「个人主页」标题与四个卡片区关键文案。"""
    resp = client.get("/me")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "个人主页" in html
    for keyword in _CARD_KEYWORDS:
        assert keyword in html, keyword


def test_me_page_游客提示(client: Any) -> None:
    """游客访问 /me 显示登录提示文案。"""
    html = client.get("/me").get_data(as_text=True)
    assert _GUEST_NOTICE in html


def test_me_page_登录态无游客提示(client: Any) -> None:
    """登录态访问 /me 不显示游客提示。"""
    with client.session_transaction() as sess:
        sess["user_id"] = "u-1"
    html = client.get("/me").get_data(as_text=True)
    assert _GUEST_NOTICE not in html


def test_me_page_含api端点与渲染占位(client: Any) -> None:
    """/me 页面 JS 拉取 /api/me，四个渲染占位容器齐全。"""
    html = client.get("/me").get_data(as_text=True)
    for element_id in ("planBadge", "profileList", "batchList", "favoriteList"):
        assert f'id="{element_id}"' in html, element_id
    assert "fetch(\"/api/me\")" in html


def test_me_page_卷库入口链接(client: Any) -> None:
    """卷库卡片含「去分类题库收藏题目」入口链接。"""
    html = client.get("/me").get_data(as_text=True)
    assert 'href="/bank"' in html
    assert "去分类题库收藏题目" in html


def test_bank_收藏按钮标记存在(client: Any) -> None:
    """题库页渲染含 .fav-btn 收藏按钮标记与「收藏」文案。"""
    html = client.get("/bank").get_data(as_text=True)
    assert 'class="fav-btn"' in html
    assert "收藏" in html
    assert ".fav-btn.favorited" in html
