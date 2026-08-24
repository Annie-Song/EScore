"""用户行为存储（services/user_activity_store.py）单元测试。

全部用例通过 pytest tmp_path 构造临时库并显式传 db_path，
不触碰真实 output/users.db，离线独立运行。排序用例通过
monkeypatch 实例 _now 固定 created_at，避免微秒级竞态。
"""
from __future__ import annotations

import pytest

from backend.batch.user_activity_store import UserActivityStore


@pytest.fixture
def store(tmp_path) -> UserActivityStore:
    """在 tmp_path 下建空库并返回 UserActivityStore 实例。"""
    return UserActivityStore(str(tmp_path / "activity.db"))


def test_link_batch_idempotent(store) -> None:
    """重复 link 同一 (user_id, task_id) 不报错且不产生重复行。"""
    store.link_batch("u1", "task-1", "batch-1")
    store.link_batch("u1", "task-1", "batch-1")  # 重复 link 应幂等
    rows = store.list_user_batches("u1")
    assert len(rows) == 1
    assert rows[0]["task_id"] == "task-1"
    assert rows[0]["batch_id"] == "batch-1"


def test_link_batch_same_task_relink_updates(store) -> None:
    """同一 task_id 重新 link 覆盖 batch_id（INSERT OR REPLACE）。"""
    store.link_batch("u1", "task-1", "batch-old")
    store.link_batch("u1", "task-1", "batch-new")
    rows = store.list_user_batches("u1")
    assert len(rows) == 1
    assert rows[0]["batch_id"] == "batch-new"


def test_list_user_batches_desc_by_created_at(tmp_path, monkeypatch) -> None:
    """list_user_batches 按 created_at 倒序，且只返回指定用户。"""
    store = UserActivityStore(str(tmp_path / "order.db"))
    now = iter(["2026-01-01T00:00:01", "2026-01-01T00:00:02",
                "2026-01-01T00:00:03"])
    monkeypatch.setattr(store, "_now", lambda: next(now))
    store.link_batch("u1", "task-1", "batch-1")  # created_at 00:00:01
    store.link_batch("u1", "task-2", "batch-2")  # created_at 00:00:02
    store.link_batch("u2", "task-3", "batch-3")  # 其他用户，不应出现
    rows = store.list_user_batches("u1")
    assert [r["task_id"] for r in rows] == ["task-2", "task-1"]


def test_add_favorite_first_true_repeat_false(store) -> None:
    """首次 add_favorite 返回 True，重复收藏同 qid 返回 False（OR IGNORE）。"""
    assert store.add_favorite("u1", "q1", subject="数学", qtype="解答题",
                             question="题干", score=10) is True
    assert store.add_favorite("u1", "q1", subject="数学") is False
    assert len(store.list_favorites("u1")) == 1
    row = store.list_favorites("u1")[0]
    assert row["subject"] == "数学"
    assert row["score"] == 10


def test_add_favorite_default_fields(store) -> None:
    """add_favorite 未显式字段使用默认值（subject/qtype/question='', score=0）。"""
    store.add_favorite("u1", "q9")
    row = store.list_favorites("u1")[0]
    assert row["subject"] == ""
    assert row["qtype"] == ""
    assert row["question"] == ""
    assert row["score"] == 0


def test_remove_favorite_deleted_true_absent_false(store) -> None:
    """remove_favorite 删除到记录返回 True，未删除返回 False。"""
    store.add_favorite("u1", "q1")
    assert store.remove_favorite("u1", "q1") is True
    assert store.remove_favorite("u1", "q1") is False
    assert store.list_favorites("u1") == []


def test_list_favorites_desc_by_created_at(tmp_path, monkeypatch) -> None:
    """list_favorites 按 created_at 倒序，且只返回指定用户。"""
    store = UserActivityStore(str(tmp_path / "fav_order.db"))
    now = iter(["2026-01-01T00:00:01", "2026-01-01T00:00:02",
                "2026-01-01T00:00:03"])
    monkeypatch.setattr(store, "_now", lambda: next(now))
    store.add_favorite("u1", "q1")  # created_at 00:00:01
    store.add_favorite("u1", "q2")  # created_at 00:00:02
    store.add_favorite("u2", "q3")  # 其他用户，不应出现
    rows = store.list_favorites("u1")
    assert [r["qid"] for r in rows] == ["q2", "q1"]
