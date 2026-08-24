"""用户角色分配 API（app/user_role_routes.py）Flask 路由单元测试（F10）。

覆盖：游客 401；teacher/school_admin 403（全局 admin 专属）；非法角色 400；
目标用户不存在 404；合法设置 teacher/school_admin/admin 各 200 且落库可读回。

存储隔离：monkeypatch user_role_routes.default_user_store 指向 tmp_path 临时库，
login_required 走真实 Flask session（test client session_transaction 写 user_id），
auth.current_user 注入角色用户。离线独立运行。
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import backend.auth.role_routes as user_role_routes
from backend.app import create_app
from backend.auth import session as auth
from backend.auth.store import UserStore


@pytest.fixture
def ctx(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Any:
    """隔离存储的测试上下文：user_store 指向 tmp，session/current_user 可控。"""
    user_store = UserStore(str(tmp_path / "users.db"))
    monkeypatch.setattr(
        user_role_routes, "default_user_store", lambda: user_store
    )
    holder: dict = {"user": None}
    monkeypatch.setattr(auth, "current_user", lambda: holder["user"])
    app = create_app()
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret-key"
    with app.test_client() as client:
        yield SimpleNamespace(
            client=client,
            users=user_store,
            holder=holder,
        )


def _login(ctx: Any, role: str, user_id: str = "u-1") -> None:
    """写入登录会话并注入对应角色的当前用户。"""
    ctx.holder["user"] = {
        "id": user_id,
        "role": role,
        "display_name": "测试",
        "username": "user",
        "school_id": None,
    }
    with ctx.client.session_transaction() as sess:
        sess.clear()
        sess["user_id"] = user_id
        sess["role"] = role


def _post(ctx: Any, user_id: str, role: str) -> Any:
    """向角色接口发起 POST 并返回响应。"""
    return ctx.client.post(
        f"/api/admin/users/{user_id}/role", json={"role": role}
    )


def test_role_update_guest_401(ctx: Any) -> None:
    """游客 POST 角色接口：401 请先登录。"""
    resp = _post(ctx, "u-1", "teacher")
    assert resp.status_code == 401
    assert resp.get_json()["message"] == "请先登录"


def test_role_update_teacher_403(ctx: Any) -> None:
    """teacher POST 角色接口：403 需要管理员权限。"""
    _login(ctx, "teacher")
    resp = _post(ctx, "u-1", "teacher")
    assert resp.status_code == 403
    assert resp.get_json()["message"] == "需要管理员权限"


def test_role_update_school_admin_403(ctx: Any) -> None:
    """school_admin POST 角色接口：403（全局 admin 专属）。"""
    _login(ctx, "school_admin")
    resp = _post(ctx, "u-1", "teacher")
    assert resp.status_code == 403
    assert resp.get_json()["message"] == "需要管理员权限"


def test_role_update_invalid_role_400(ctx: Any) -> None:
    """admin POST 非法角色：400 非法角色。"""
    _login(ctx, "admin")
    resp = ctx.client.post(
        "/api/admin/users/u-1/role", json={"role": "superuser"}
    )
    assert resp.status_code == 400
    assert resp.get_json()["message"] == "非法角色"


def test_role_update_missing_target_404(ctx: Any) -> None:
    """admin POST 不存在用户：404 用户不存在。"""
    _login(ctx, "admin")
    resp = _post(ctx, "no-such-id", "teacher")
    assert resp.status_code == 404
    assert resp.get_json()["message"] == "用户不存在"


def test_role_update_teacher_200_persisted(ctx: Any) -> None:
    """admin 设置目标为 teacher：200 且落库可读回。"""
    _login(ctx, "admin")
    target = ctx.users.create_user("alice", "hash", role="teacher")
    resp = _post(ctx, target["id"], "teacher")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["message"] == "角色已更新"
    assert body["role"] == "teacher"
    assert ctx.users.get_user(target["id"])["role"] == "teacher"


def test_role_update_school_admin_200_persisted(ctx: Any) -> None:
    """admin 设置目标为 school_admin：200 且落库可读回。"""
    _login(ctx, "admin")
    target = ctx.users.create_user("bob", "hash", role="teacher")
    resp = _post(ctx, target["id"], "school_admin")
    assert resp.status_code == 200
    assert resp.get_json()["role"] == "school_admin"
    assert ctx.users.get_user(target["id"])["role"] == "school_admin"


def test_role_update_admin_200_persisted(ctx: Any) -> None:
    """admin 设置目标为 admin：200 且落库可读回。"""
    _login(ctx, "admin")
    target = ctx.users.create_user("carol", "hash", role="teacher")
    resp = _post(ctx, target["id"], "admin")
    assert resp.status_code == 200
    assert resp.get_json()["role"] == "admin"
    assert ctx.users.get_user(target["id"])["role"] == "admin"
