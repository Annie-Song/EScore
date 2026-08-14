"""存储层单元测试：GradeStore 抽象接口 + SqliteGradeStore 实现。

全部用例通过 pytest tmp_path 构造临时数据库，不触碰真实 DB_PATH，可离线独立运行。
"""
import os
import sqlite3

import pytest

from services.sqlite_store import SqliteGradeStore
from services.store import (
    BATCH_STATUS_RUNNING,
    BATCH_STATUS_SUCCEEDED,
    GradeRecord,
    GradeStore,
)


def _record(record_id: str, batch_id: str, question_no: int, score: float,
            *, degraded: bool = False, routed: bool = False,
            work_text: str = "work", answer_text: str = "answer",
            method: str = "offline", created_at: str = "2026-01-01T00:00:00",
            error_category: str = "", error_reason: str = "") -> GradeRecord:
    """构造测试用 GradeRecord，未显式指定的字段使用默认值。"""
    return GradeRecord(
        record_id=record_id,
        batch_id=batch_id,
        question_no=question_no,
        work_text=work_text,
        answer_text=answer_text,
        score=score,
        method=method,
        degraded=degraded,
        routed=routed,
        created_at=created_at,
        error_category=error_category,
        error_reason=error_reason,
    )


def _save_batch(store: SqliteGradeStore, batch_id: str,
                created_at: str = "2026-01-01T00:00:00") -> None:
    """先建批次元信息，使记录满足外键约束的引用完整性。"""
    store.save_batch(batch_id, "reference", BATCH_STATUS_RUNNING, 0, created_at)


def test_grade_store_abstract_instantiation_raises():
    with pytest.raises(TypeError):
        GradeStore()


def test_sqlite_store_init_idempotent_same_path_twice(tmp_path):
    db_path = str(tmp_path / "idem.db")
    SqliteGradeStore(db_path)
    SqliteGradeStore(db_path)


def test_save_record_get_record_round_trip_fields_complete(tmp_path):
    db_path = str(tmp_path / "roundtrip.db")
    store = SqliteGradeStore(db_path)
    _save_batch(store, "batch-1")
    record = _record(
        record_id="rec-1",
        batch_id="batch-1",
        question_no=1,
        score=92.5,
        work_text="学生作答",
        answer_text="标准答案",
        degraded=True,
        routed=True,
        created_at="2026-02-03T10:00:00",
    )
    store.save_record(record)
    fetched = store.get_record("rec-1")
    assert fetched == record
    assert fetched.degraded is True
    assert fetched.routed is True
    assert fetched.error_category == ""
    assert fetched.error_reason == ""


def test_get_record_missing_returns_none(tmp_path):
    store = SqliteGradeStore(str(tmp_path / "missing.db"))
    assert store.get_record("no-such-id") is None


def test_save_records_list_records_question_no_ascending(tmp_path):
    db_path = str(tmp_path / "list.db")
    store = SqliteGradeStore(db_path)
    _save_batch(store, "batch-1")
    records = [
        _record("rec-2", "batch-1", 2, 80.0),
        _record("rec-1", "batch-1", 1, 90.0),
        _record("rec-3", "batch-1", 3, 70.0),
    ]
    store.save_records(records)
    fetched = store.list_records("batch-1")
    assert [r.question_no for r in fetched] == [1, 2, 3]
    assert fetched == [records[1], records[0], records[2]]


def test_save_batch_get_batch_round_trip_and_status_update(tmp_path):
    db_path = str(tmp_path / "batch.db")
    store = SqliteGradeStore(db_path)
    store.save_batch("b1", "参考文本", BATCH_STATUS_RUNNING, 5,
                     "2026-03-01T08:00:00")
    batch = store.get_batch("b1")
    assert batch == {
        "batch_id": "b1",
        "reference_text": "参考文本",
        "status": BATCH_STATUS_RUNNING,
        "total_questions": 5,
        "created_at": "2026-03-01T08:00:00",
    }
    store.update_batch_status("b1", BATCH_STATUS_SUCCEEDED, 10)
    updated = store.get_batch("b1")
    assert updated["status"] == BATCH_STATUS_SUCCEEDED
    assert updated["total_questions"] == 10
    assert updated["batch_id"] == "b1"


def test_get_batch_missing_returns_none(tmp_path):
    store = SqliteGradeStore(str(tmp_path / "batch_missing.db"))
    assert store.get_batch("no-such-batch") is None


def test_list_batches_created_at_descending(tmp_path):
    db_path = str(tmp_path / "batches.db")
    store = SqliteGradeStore(db_path)
    store.save_batch("b1", "r1", BATCH_STATUS_RUNNING, 1, "2026-01-01T00:00:00")
    store.save_batch("b2", "r2", BATCH_STATUS_RUNNING, 1, "2026-03-01T00:00:00")
    store.save_batch("b3", "r3", BATCH_STATUS_RUNNING, 1, "2026-02-01T00:00:00")
    fetched = store.list_batches()
    assert [b["batch_id"] for b in fetched] == ["b2", "b3", "b1"]


def test_stats_by_question_aggregation_precision_rounding_and_order(tmp_path):
    db_path = str(tmp_path / "stats_q.db")
    store = SqliteGradeStore(db_path)
    _save_batch(store, "b1")
    store.save_records([
        _record("q1-a", "b1", 1, 90.0),
        _record("q1-b", "b1", 1, 91.5),
        _record("q1-c", "b1", 1, 92.5),
        _record("q2-a", "b1", 2, 80.0),
    ])
    stats = store.stats_by_question("b1")
    assert stats == [
        {"question_no": 1, "count": 3, "avg_score": 91.3,
         "max_score": 92.5, "min_score": 90.0},
        {"question_no": 2, "count": 1, "avg_score": 80.0,
         "max_score": 80.0, "min_score": 80.0},
    ]


def test_stats_by_category_count_descending_and_avg(tmp_path):
    db_path = str(tmp_path / "stats_c.db")
    store = SqliteGradeStore(db_path)
    _save_batch(store, "b1")
    store.save_records([
        _record("c1", "b1", 1, 60.0, error_category="grammar"),
        _record("c2", "b1", 2, 70.0, error_category="grammar"),
        _record("c3", "b1", 3, 80.0, error_category="grammar"),
        _record("c4", "b1", 4, 80.0, error_category="math"),
        _record("c5", "b1", 5, 90.0, error_category="math"),
        _record("c6", "b1", 6, 95.0),
    ])
    stats = store.stats_by_category("b1")
    assert stats == [
        {"error_category": "grammar", "count": 3, "avg_score": 70.0},
        {"error_category": "math", "count": 2, "avg_score": 85.0},
        {"error_category": "", "count": 1, "avg_score": 95.0},
    ]


def test_default_store_returns_same_singleton_sqlite_store(monkeypatch, tmp_path):
    from services import sqlite_store as sqlite_module
    from services import store as store_module

    db_path = str(tmp_path / "singleton.db")
    monkeypatch.setattr(store_module, "_store", None)
    # 将 SqliteGradeStore 默认 db_path 重定向到临时库，避免触碰真实 DB_PATH
    monkeypatch.setattr(sqlite_module.SqliteGradeStore.__init__, "__defaults__",
                        (db_path,))
    first = store_module.default_store()
    second = store_module.default_store()
    assert first is second
    assert isinstance(first, sqlite_module.SqliteGradeStore)


def test_db_file_exists_and_wal_journal_mode(tmp_path):
    db_path = str(tmp_path / "wal.db")
    store = SqliteGradeStore(db_path)
    _save_batch(store, "b1")
    store.save_record(_record("r1", "b1", 1, 88.0))
    assert os.path.exists(db_path)
    conn = sqlite3.connect(db_path)
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        conn.close()
    assert mode == "wal"
