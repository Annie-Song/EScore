"""用户行为存储新增接口单元测试（F5 跨校批次列表）。

覆盖 services/user_activity_store.py 新增的 list_all_batches：返回全部
用户-批次关联映射（不限用户），按 created_at 倒序。
全部用例用 tmp_path 隔离，离线独立运行。
"""
from __future__ import annotations

from backend.batch.user_activity_store import UserActivityStore


def test_list_all_batches_returns_all_users_desc(
    monkeypatch, tmp_path,
) -> None:
    """list_all_batches 返回跨用户全部映射，按创建时间倒序。"""
    store = UserActivityStore(str(tmp_path / "activity.db"))
    now = iter(["2026-01-01T00:00:01", "2026-01-01T00:00:02",
                "2026-01-01T00:00:03"])
    monkeypatch.setattr(store, "_now", lambda: next(now))
    store.link_batch("u1", "task-1", "batch-1")  # 00:00:01
    store.link_batch("u2", "task-2", "batch-2")  # 00:00:02
    store.link_batch("u1", "task-3", "batch-3")  # 00:00:03
    rows = store.list_all_batches()
    assert [r["batch_id"] for r in rows] == ["batch-3", "batch-2", "batch-1"]
    assert {r["user_id"] for r in rows} == {"u1", "u2"}


def test_list_all_batches_empty_when_no_mappings(tmp_path) -> None:
    """无任何关联映射：返回空列表。"""
    store = UserActivityStore(str(tmp_path / "empty.db"))
    assert store.list_all_batches() == []
