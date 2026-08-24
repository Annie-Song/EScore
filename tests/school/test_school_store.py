"""学校存储（services/school_store.py）单元测试。

覆盖 create_school/get_school/get_school_by_code/list_schools（含
member_count 联查）与 school_batch_stats 聚合；code 唯一冲突抛
sqlite3.IntegrityError。school_batch_stats 联查 grades.db 的
default_store 按调用方命名空间 patch：backend.school.store.default_store。

全部用例用 tmp_path 构造临时 db（users.db 与 grades.db 均隔离），离线运行。
"""
from __future__ import annotations

import sqlite3

import pytest

import backend.school.store as school_store
from backend.school.store import SchoolStore
from backend.batch.record_store import SqliteGradeStore
from backend.batch.store import BATCH_STATUS_SUCCEEDED, GradeRecord
from backend.batch.user_activity_store import UserActivityStore
from backend.auth.store import UserStore


@pytest.fixture
def store(tmp_path) -> SchoolStore:
    """在 tmp_path 下建空库并返回 SchoolStore 实例。"""
    return SchoolStore(str(tmp_path / "schools.db"))


def _record(
    record_id: str, batch_id: str, question_no: int, score: float
) -> GradeRecord:
    """构造测试用 GradeRecord。"""
    return GradeRecord(
        record_id=record_id,
        batch_id=batch_id,
        question_no=question_no,
        work_text="作答",
        answer_text="答案",
        score=score,
        method="offline",
        degraded=False,
        routed=False,
        created_at="2026-01-01T00:00:00",
    )


def test_create_school_returns_full_record(store: SchoolStore) -> None:
    """create_school 返回 id/name/code/created_at 完整记录。"""
    school = store.create_school("示例中学", "SCH001")
    assert school["id"]
    assert school["name"] == "示例中学"
    assert school["code"] == "SCH001"
    assert school["created_at"]


def test_get_school_hit_and_miss(store: SchoolStore) -> None:
    """get_school 命中返回记录、未命中返回 None。"""
    created = store.create_school("示例中学", "SCH001")
    row = store.get_school(created["id"])
    assert row is not None
    assert row["name"] == "示例中学"
    assert store.get_school("no-such-id") is None


def test_get_school_by_code_hit_and_miss(store: SchoolStore) -> None:
    """get_school_by_code 命中返回记录、未命中返回 None。"""
    store.create_school("示例中学", "SCH001")
    row = store.get_school_by_code("SCH001")
    assert row is not None
    assert row["name"] == "示例中学"
    assert store.get_school_by_code("NO-SUCH") is None


def test_create_school_duplicate_code_raises_integrity_error(
    store: SchoolStore,
) -> None:
    """code 唯一约束：重名 code 插入抛 sqlite3.IntegrityError。"""
    store.create_school("学校甲", "SCH001")
    with pytest.raises(sqlite3.IntegrityError):
        store.create_school("学校乙", "SCH001")


def test_create_school_custom_id_preserved(store: SchoolStore) -> None:
    """显式传入 school_id 时原样保存。"""
    school = store.create_school("演示学校", "DEMO", school_id="school-demo")
    assert school["id"] == "school-demo"
    assert store.get_school("school-demo")["code"] == "DEMO"


def test_list_schools_includes_member_count(tmp_path, monkeypatch) -> None:
    """list_schools 联查 users 得到 member_count，且按创建时间倒序。"""
    users_db = str(tmp_path / "users.db")
    school_store_inst = SchoolStore(users_db)
    user_store = UserStore(users_db)
    now = iter(["2026-01-01T00:00:01", "2026-01-01T00:00:02"])
    monkeypatch.setattr(school_store_inst, "_now", lambda: next(now))
    school_a = school_store_inst.create_school("旧学校", "SCH-A")
    school_b = school_store_inst.create_school("新学校", "SCH-B")
    user_store.create_user("alice", "hash", school_id=school_a["id"])
    user_store.create_user("bob", "hash", school_id=school_a["id"])
    user_store.create_user("carol", "hash", school_id=school_b["id"])
    rows = school_store_inst.list_schools()
    by_id = {row["id"]: row for row in rows}
    assert set(by_id) == {school_a["id"], school_b["id"]}
    assert by_id[school_a["id"]]["member_count"] == 2
    assert by_id[school_b["id"]]["member_count"] == 1
    assert [row["id"] for row in rows] == [school_b["id"], school_a["id"]]


def test_school_batch_stats_aggregates_grades(monkeypatch, tmp_path) -> None:
    """school_batch_stats 聚合 batch_count/record_count/avg_score。

    通过 users→user_batches→grades.db 联查；缺失批次跳过。
    """
    users_db = str(tmp_path / "users.db")
    school_store_inst = SchoolStore(users_db)
    user_store = UserStore(users_db)
    activity = UserActivityStore(users_db)
    grades = SqliteGradeStore(str(tmp_path / "grades.db"))

    school = school_store_inst.create_school("示例中学", "SCH001")
    user = user_store.create_user("alice", "hash", school_id=school["id"])
    user_store.create_user("bob", "hash", school_id=school["id"])  # 无批次用户
    activity.link_batch(user["id"], "task-1", "batch-1")
    activity.link_batch(user["id"], "task-2", "batch-missing")

    grades.save_batch("batch-1", "参考答案", BATCH_STATUS_SUCCEEDED, 2,
                      "2026-01-01T00:00:00")
    grades.save_records([
        _record("r1", "batch-1", 1, 90.0),
        _record("r2", "batch-1", 2, 70.0),
    ])
    monkeypatch.setattr(school_store, "default_store", lambda: grades)

    stats = school_store_inst.school_batch_stats(school["id"])
    assert stats == {"batch_count": 1, "record_count": 2, "avg_score": 80.0}


def test_school_batch_stats_no_batches_returns_zeros(
    monkeypatch, tmp_path,
) -> None:
    """无任何批次关联：聚合全为 0，不除零。"""
    users_db = str(tmp_path / "users.db")
    school_store_inst = SchoolStore(users_db)
    UserStore(users_db)
    UserActivityStore(users_db)  # 建 user_batches 表，供 school_batch_stats 联查
    grades = SqliteGradeStore(str(tmp_path / "grades_empty.db"))
    school = school_store_inst.create_school("空学校", "SCH-EMPTY")
    monkeypatch.setattr(school_store, "default_store", lambda: grades)
    assert school_store_inst.school_batch_stats(school["id"]) == {
        "batch_count": 0, "record_count": 0, "avg_score": 0.0,
    }


def test_table_init_idempotent(tmp_path) -> None:
    """同一路径重复初始化不报错。"""
    db_path = str(tmp_path / "reinit.db")
    SchoolStore(db_path)
    SchoolStore(db_path)
    conn = sqlite3.connect(db_path)
    try:
        tables = {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    finally:
        conn.close()
    assert "schools" in tables
