"""用户认证 Flask 路由单元测试。

用 monkeypatch 把 app.auth_routes.default_user_store 替换为指向 tmp_path
临时库的工厂，隔离真实 output/users.db，离线独立运行。mock 目标取调用方
命名空间：app/auth_routes.py 顶层 `from services.user_store import
default_user_store` 绑定在模块级，故替换 auth_routes.default_user_store。
"""
from __future__ import annotations

import pytest

import app.auth_routes as auth_routes
from app import create_app
from services.user_store import UserStore

_SESSION_KEYS = ("user_id", "display_name", "role", "plan")


@pytest.fixture
def client(monkeypatch, tmp_path):
    """构造 Flask 测试客户端，auth 路由的用户库指向 tmp_path 临时库。"""
    db_path = str(tmp_path / "auth_routes.db")
    store = UserStore(db_path)
    monkeypatch.setattr(auth_routes, "default_user_store", lambda: store)
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _register(client, username: str = "alice", password: str = "secret123",
              display_name: str = "Alice"):
    """POST /api/auth/register 快捷封装。"""
    return client.post("/api/auth/register", json={
        "username": username,
        "password": password,
        "display_name": display_name,
    })


def test_register_success_returns_201_with_session(client):
    """注册成功：201，公开字段无 password_hash，session 已写入。"""
    resp = _register(client)
    assert resp.status_code == 201
    user = resp.get_json()["user"]
    assert user["username"] == "alice"
    assert user["display_name"] == "Alice"
    assert user["role"] == "teacher"
    assert user["plan"] == "free"
    assert user["id"]
    assert "password_hash" not in user
    with client.session_transaction() as sess:
        for key in _SESSION_KEYS:
            assert key in sess
        assert sess["role"] == "teacher"
        assert sess["plan"] == "free"


def test_register_duplicate_username_returns_409(client):
    """重名注册：409 用户名已存在。"""
    assert _register(client).status_code == 201
    resp = _register(client)
    assert resp.status_code == 409
    assert resp.get_json()["message"] == "用户名已存在"


def test_register_short_password_returns_400(client):
    """密码不足 6 位：400。"""
    resp = client.post("/api/auth/register",
                       json={"username": "bob", "password": "12345"})
    assert resp.status_code == 400
    assert resp.get_json()["message"] == "密码至少 6 位"


def test_register_empty_username_returns_400(client):
    """空用户名（含纯空白）：400。"""
    resp = client.post("/api/auth/register",
                       json={"username": "   ", "password": "secret123"})
    assert resp.status_code == 400
    assert resp.get_json()["message"] == "用户名不能为空"


def test_login_success_returns_200_with_session(client):
    """登录成功：200，session 键齐全，无 password_hash。"""
    _register(client)
    client.post("/api/auth/logout")
    resp = client.post("/api/auth/login",
                       json={"username": "alice", "password": "secret123"})
    assert resp.status_code == 200
    user = resp.get_json()["user"]
    assert user["username"] == "alice"
    assert "password_hash" not in user
    with client.session_transaction() as sess:
        for key in _SESSION_KEYS:
            assert key in sess


def test_login_wrong_password_returns_401(client):
    """密码错误：401。"""
    _register(client)
    client.post("/api/auth/logout")
    resp = client.post("/api/auth/login",
                       json={"username": "alice", "password": "wrong-pass"})
    assert resp.status_code == 401
    assert resp.get_json()["message"] == "用户名或密码错误"


def test_login_nonexistent_user_returns_401(client):
    """用户不存在：401。"""
    resp = client.post("/api/auth/login",
                       json={"username": "nobody", "password": "secret123"})
    assert resp.status_code == 401
    assert resp.get_json()["message"] == "用户名或密码错误"


def test_logout_clears_session_and_me_returns_none(client):
    """登出：200，session 清空，/api/auth/me 返回 user None。"""
    _register(client)
    resp = client.post("/api/auth/logout")
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}
    with client.session_transaction() as sess:
        assert "user_id" not in sess
    resp = client.get("/api/auth/me")
    assert resp.status_code == 200
    assert resp.get_json() == {"user": None}


def test_me_after_login_returns_public_fields(client):
    """登录后 /api/auth/me 返回公开字段且无 password_hash。"""
    _register(client)
    resp = client.get("/api/auth/me")
    assert resp.status_code == 200
    user = resp.get_json()["user"]
    assert user["username"] == "alice"
    assert user["id"]
    assert user["role"] == "teacher"
    assert user["plan"] == "free"
    assert "password_hash" not in user


def test_me_as_guest_returns_none(client):
    """游客 GET /api/auth/me：200，user 为 None。"""
    resp = client.get("/api/auth/me")
    assert resp.status_code == 200
    assert resp.get_json() == {"user": None}
