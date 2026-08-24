"""个人主页加入学校接口单元测试（F5 学校数据隔离）。

覆盖 POST /api/me/school（路由函数为私有名 _join_school，用 HTTP
test_client 打接口，不按公开函数名导入）：游客 401、合法 code 更新
school_id 200、非法 code 404、缺 code 400。

mock 目标取调用方命名空间：app.me_routes.default_user_store /
default_school_store 均为模块级绑定，替换 me_routes 上的同名引用；
登录态经 session 写入 user_id（login_required/current_user_id 均读会话）。
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import app.me_routes as me_routes
from app import create_app
from services.school_store import SchoolStore
from services.user_store import UserStore

USER_ID = "u-me-1"


@pytest.fixture
def ctx(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Any:
    """隔离存储的测试上下文：用户库与学校库均指向 tmp。"""
    users_db = str(tmp_path / "users.db")
    user_store = UserStore(users_db)
    school_store = SchoolStore(users_db)
    monkeypatch.setattr(me_routes, "default_user_store", lambda: user_store)
    monkeypatch.setattr(
        me_routes, "default_school_store", lambda: school_store
    )
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield SimpleNamespace(
            client=client, users=user_store, schools=school_store
        )


def _login(ctx: Any, user_id: str = USER_ID) -> None:
    """写入会话 user_id 模拟登录态。"""
    with ctx.client.session_transaction() as sess:
        sess["user_id"] = user_id


def test_join_school_guest_401(ctx: Any) -> None:
    """游客 POST /api/me/school：401。"""
    resp = ctx.client.post("/api/me/school", json={"school_code": "SCH001"})
    assert resp.status_code == 401


def test_join_school_valid_code_updates_school_id(ctx: Any) -> None:
    """合法 code：200，用户 school_id 更新为对应学校。"""
    user = ctx.users.create_user("alice", "hash")
    school = ctx.schools.create_school("示例中学", "SCH001")
    _login(ctx, user["id"])
    resp = ctx.client.post("/api/me/school", json={"school_code": "SCH001"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body == {"ok": True, "school_id": school["id"]}
    assert ctx.users.get_user(user["id"])["school_id"] == school["id"]


def test_join_school_invalid_code_404(ctx: Any) -> None:
    """非法 code：404 学校代码无效，school_id 不变。"""
    user = ctx.users.create_user("alice", "hash")
    ctx.schools.create_school("示例中学", "SCH001")
    _login(ctx, user["id"])
    resp = ctx.client.post("/api/me/school", json={"school_code": "WRONG"})
    assert resp.status_code == 404
    assert resp.get_json()["message"] == "学校代码无效"
    assert ctx.users.get_user(user["id"])["school_id"] is None


def test_join_school_missing_code_400(ctx: Any) -> None:
    """缺 school_code：400 缺少学校代码。"""
    user = ctx.users.create_user("alice", "hash")
    _login(ctx, user["id"])
    resp = ctx.client.post("/api/me/school", json={})
    assert resp.status_code == 400
    assert resp.get_json()["message"] == "缺少学校代码"
