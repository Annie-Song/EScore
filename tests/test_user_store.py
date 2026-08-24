"""用户存储（services/user_store.py）单元测试。

全部用例通过 pytest tmp_path 构造临时库并显式传 db_path，
不触碰真实 output/users.db，离线独立运行。
"""
from __future__ import annotations

import sqlite3

import pytest

from services.user_store import UserStore


@pytest.fixture
def store(tmp_path) -> UserStore:
    """在 tmp_path 下建空库并返回 UserStore 实例。"""
    return UserStore(str(tmp_path / "users.db"))


def test_create_user_returns_full_record(store) -> None:
    """create_user 返回完整记录，含 id/username/role/plan/display_name。"""
    user = store.create_user("alice", "hash-alice")
    assert user["id"]
    assert user["username"] == "alice"
    assert user["password_hash"] == "hash-alice"
    assert user["role"] == "teacher"
    assert user["plan"] == "free"
    assert user["display_name"] == ""
    for key in (
        "id", "username", "password_hash", "display_name", "role", "plan",
        "school_id", "avatar", "created_at", "updated_at",
    ):
        assert key in user


def test_create_user_defaults(store) -> None:
    """未显式指定的字段使用默认值（role=teacher/plan=free/display_name=''）。"""
    user = store.create_user("bob", "hash-bob")
    assert user["role"] == "teacher"
    assert user["plan"] == "free"
    assert user["display_name"] == ""
    assert user["school_id"] is None
    assert user["avatar"] is None


def test_create_user_custom_fields(store) -> None:
    """显式传入的 display_name/role/plan 被正确写入。"""
    user = store.create_user(
        "carol", "hash-carol", display_name="Carol", role="student", plan="pro",
    )
    assert user["display_name"] == "Carol"
    assert user["role"] == "student"
    assert user["plan"] == "pro"


def test_get_user_hit_and_miss(store) -> None:
    """get_user 命中返回含 username 的记录；未命中返回 None。"""
    created = store.create_user("dave", "hash-dave")
    row = store.get_user(created["id"])
    assert row is not None
    assert row["id"] == created["id"]
    assert row["username"] == "dave"
    assert row["password_hash"] == "hash-dave"
    assert store.get_user("no-such-id") is None


def test_get_user_by_username_hit_and_miss(store) -> None:
    """get_user_by_username 命中返回记录；未命中返回 None。"""
    store.create_user("eve", "hash-eve")
    row = store.get_user_by_username("eve")
    assert row is not None
    assert row["id"]
    assert row["username"] == "eve"
    assert store.get_user_by_username("no-such-user") is None


def test_duplicate_username_raises_integrity_error(store) -> None:
    """重名插入抛 sqlite3.IntegrityError。"""
    store.create_user("frank", "hash-frank")
    with pytest.raises(sqlite3.IntegrityError):
        store.create_user("frank", "hash-frank-2")


def test_wal_mode_enabled(tmp_path) -> None:
    """初始化后连接 PRAGMA journal_mode 应为 wal。"""
    db_path = str(tmp_path / "wal.db")
    UserStore(db_path)
    conn = sqlite3.connect(db_path)
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        conn.close()
    assert mode == "wal"


def test_update_role_changes_user_role(store) -> None:
    """update_role 后 get_user 返回新 role，可读回。"""
    user = store.create_user("alice", "hash")
    assert store.get_user(user["id"])["role"] == "teacher"
    store.update_role(user["id"], "school_admin")
    assert store.get_user(user["id"])["role"] == "school_admin"
    store.update_role(user["id"], "admin")
    assert store.get_user(user["id"])["role"] == "admin"


def test_update_role_missing_user_raises_value_error(store) -> None:
    """update_role 用户不存在：抛 ValueError（fail-fast）。"""
    with pytest.raises(ValueError):
        store.update_role("no-such-user", "admin")
