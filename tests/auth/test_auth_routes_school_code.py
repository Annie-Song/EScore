"""注册带学校代码路由单元测试（F5 学校数据隔离）。

覆盖 POST /api/auth/register 的 school_code 字段：合法 code 写入
school_id、非法 code 返回 400、缺省 school_id 为 None。
mock 目标取调用方命名空间：backend.auth.routes.default_school_store /
default_user_store 均为模块级绑定，替换 auth_routes 上的同名引用。
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import backend.auth.routes as auth_routes
from backend.app import create_app
from backend.school.store import SchoolStore
from backend.auth.store import UserStore


@pytest.fixture
def ctx(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Any:
    """隔离存储的测试上下文：用户库与学校库均指向 tmp。"""
    users_db = str(tmp_path / "users.db")
    user_store = UserStore(users_db)
    school_store = SchoolStore(users_db)
    monkeypatch.setattr(auth_routes, "default_user_store", lambda: user_store)
    monkeypatch.setattr(
        auth_routes, "default_school_store", lambda: school_store
    )
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield SimpleNamespace(
            client=client, users=user_store, schools=school_store
        )


def _register(ctx: Any, school_code: str | None = None, **extra: str) -> Any:
    """POST /api/auth/register 快捷封装。"""
    payload: dict[str, str] = {
        "username": "alice",
        "password": "secret123",
        "display_name": "Alice",
    }
    if school_code is not None:
        payload["school_code"] = school_code
    payload.update(extra)
    return ctx.client.post("/api/auth/register", json=payload)


def test_register_with_valid_school_code_sets_school_id(ctx: Any) -> None:
    """合法 school_code：201，用户 school_id 指向对应学校。"""
    school = ctx.schools.create_school("示例中学", "SCH001")
    resp = _register(ctx, school_code="SCH001")
    assert resp.status_code == 201
    user = resp.get_json()["user"]
    assert user["school_id"] == school["id"]
    stored = ctx.users.get_user_by_username("alice")
    assert stored["school_id"] == school["id"]


def test_register_with_invalid_school_code_400(ctx: Any) -> None:
    """非法 school_code：400 学校代码无效，不创建用户。"""
    ctx.schools.create_school("示例中学", "SCH001")
    resp = _register(ctx, school_code="WRONG")
    assert resp.status_code == 400
    assert resp.get_json()["message"] == "学校代码无效"
    assert ctx.users.get_user_by_username("alice") is None


def test_register_without_school_code_leaves_none(ctx: Any) -> None:
    """缺省 school_code：201，school_id 为 None。"""
    resp = _register(ctx)
    assert resp.status_code == 201
    assert resp.get_json()["user"]["school_id"] is None
