"""用户存储新增接口单元测试（F5 学校数据隔离）。

覆盖 services/user_store.py 新增的 update_plan / update_school_id /
list_users_by_school：用户不存在时 update_* 抛 ValueError（fail-fast），
list_users_by_school 按学校过滤且倒序。
全部用例用 tmp_path 隔离，不触碰真实 output/users.db。
"""
from __future__ import annotations

import pytest

from backend.auth.store import UserStore


@pytest.fixture
def store(tmp_path) -> UserStore:
    """在 tmp_path 下建空库并返回 UserStore 实例。"""
    return UserStore(str(tmp_path / "users.db"))


def test_update_plan_changes_user_plan(store: UserStore) -> None:
    """update_plan 后 get_user 返回新 plan。"""
    user = store.create_user("alice", "hash", plan="free")
    store.update_plan(user["id"], "pro")
    assert store.get_user(user["id"])["plan"] == "pro"


def test_update_plan_missing_user_raises_value_error(store: UserStore) -> None:
    """update_plan 用户不存在：抛 ValueError（fail-fast）。"""
    with pytest.raises(ValueError):
        store.update_plan("no-such-user", "pro")


def test_update_school_id_sets_and_overwrites(store: UserStore) -> None:
    """update_school_id 设置 school_id，再次调用覆盖旧值。"""
    user = store.create_user("alice", "hash")
    assert store.get_user(user["id"])["school_id"] is None
    store.update_school_id(user["id"], "school-1")
    assert store.get_user(user["id"])["school_id"] == "school-1"
    store.update_school_id(user["id"], "school-2")
    assert store.get_user(user["id"])["school_id"] == "school-2"


def test_update_school_id_missing_user_raises_value_error(
    store: UserStore,
) -> None:
    """update_school_id 用户不存在：抛 ValueError（fail-fast）。"""
    with pytest.raises(ValueError):
        store.update_school_id("no-such-user", "school-1")


def test_list_users_by_school_filters_and_desc(
    store: UserStore, monkeypatch,
) -> None:
    """list_users_by_school 只返回该校成员，按创建时间倒序。"""
    now = iter(["2026-01-01T00:00:01", "2026-01-01T00:00:02",
                "2026-01-01T00:00:03", "2026-01-01T00:00:04"])
    monkeypatch.setattr(store, "_now", lambda: next(now))
    user_a = store.create_user("alice", "hash", school_id="school-1")
    user_b = store.create_user("bob", "hash", school_id="school-1")
    store.create_user("carol", "hash", school_id="school-2")  # 其他学校
    store.create_user("dave", "hash")  # 无学校
    rows = store.list_users_by_school("school-1")
    assert [r["id"] for r in rows] == [user_b["id"], user_a["id"]]
    assert all(r["school_id"] == "school-1" for r in rows)


def test_list_users_by_school_empty_when_no_members(store: UserStore) -> None:
    """学校无成员：返回空列表。"""
    store.create_user("alice", "hash")
    assert store.list_users_by_school("school-ghost") == []
