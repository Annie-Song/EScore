"""管理端学校与跨校批次 Flask 路由单元测试（F5 学校数据隔离）。

覆盖：/admin 页面渲染（无 admin 门控）；/api/admin/schools GET 聚合 /
POST 建校与 409/400；/api/admin/schools/<id>/members 成员列表与 404；
/api/admin/batches 跨校批次列表与 school_id 过滤。游客/非 admin 一律 403。

存储隔离：monkeypatch school_routes.default_school_store /
default_user_store / default_user_activity_store / default_store 指向
tmp_path 临时库；school_store 模块的 default_store 单独 patch（供
SchoolStore.school_batch_stats 联查）；auth.current_user 注入角色用户。
离线独立运行。
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import app.school_routes as school_routes
import services.school_store as school_store_mod
from app import create_app
from services import auth
from services.school_store import SchoolStore
from services.sqlite_store import SqliteGradeStore
from services.store import BATCH_STATUS_SUCCEEDED, GradeRecord
from services.user_activity_store import UserActivityStore
from services.user_store import UserStore


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


@pytest.fixture
def ctx(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Any:
    """隔离存储的测试上下文：四类存储均指向 tmp，auth.current_user 可注入。"""
    users_db = str(tmp_path / "users.db")
    user_store = UserStore(users_db)
    school_store = SchoolStore(users_db)
    activity = UserActivityStore(users_db)
    grades = SqliteGradeStore(str(tmp_path / "grades.db"))
    monkeypatch.setattr(
        school_routes, "default_school_store", lambda: school_store
    )
    monkeypatch.setattr(
        school_routes, "default_user_store", lambda: user_store
    )
    monkeypatch.setattr(
        school_routes, "default_user_activity_store", lambda: activity
    )
    monkeypatch.setattr(school_routes, "default_store", lambda: grades)
    monkeypatch.setattr(school_store_mod, "default_store", lambda: grades)
    holder: dict = {"user": None}
    monkeypatch.setattr(auth, "current_user", lambda: holder["user"])
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield SimpleNamespace(
            client=client,
            users=user_store,
            schools=school_store,
            activity=activity,
            grades=grades,
            holder=holder,
        )


def _as(
    ctx: Any, role: str, user_id: str = "u-1", display_name: str = "测试"
) -> None:
    """注入指定角色的当前用户到 auth.current_user。"""
    ctx.holder["user"] = {
        "id": user_id,
        "role": role,
        "display_name": display_name,
        "username": "user",
        "school_id": None,
    }


def test_admin_page_renders_200_guest(ctx: Any) -> None:
    """/admin 页面 200 且渲染出学校管理文案（页面本身不做 admin 门控）。"""
    resp = ctx.client.get("/admin")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "学校管理" in html
    assert 'id="schoolTable"' in html


def test_admin_schools_list_guest_403(ctx: Any) -> None:
    """游客 GET /api/admin/schools：403。"""
    assert ctx.client.get("/api/admin/schools").status_code == 403


def test_admin_schools_list_non_admin_403(ctx: Any) -> None:
    """非 admin 用户 GET /api/admin/schools：403。"""
    _as(ctx, "teacher")
    resp = ctx.client.get("/api/admin/schools")
    assert resp.status_code == 403
    assert resp.get_json()["message"] == "需要管理员权限"


def test_admin_schools_create_201(ctx: Any) -> None:
    """admin POST 建校：201，学校落库且返回 id/name/code。"""
    _as(ctx, "admin")
    resp = ctx.client.post("/api/admin/schools", json={
        "name": "示例中学", "code": "SCH001",
    })
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["id"]
    assert body["name"] == "示例中学"
    assert body["code"] == "SCH001"
    assert ctx.schools.get_school_by_code("SCH001") is not None


def test_admin_schools_create_duplicate_code_409(ctx: Any) -> None:
    """admin 建校 code 重名：409 学校代码已存在。"""
    _as(ctx, "admin")
    ctx.schools.create_school("既有中学", "SCH001")
    resp = ctx.client.post("/api/admin/schools", json={
        "name": "新中学", "code": "SCH001",
    })
    assert resp.status_code == 409
    assert resp.get_json()["message"] == "学校代码已存在"


def test_admin_schools_create_empty_fields_400(ctx: Any) -> None:
    """admin 建校缺 name 或 code：400。"""
    _as(ctx, "admin")
    resp_blank = ctx.client.post(
        "/api/admin/schools", json={"name": "   ", "code": "SCH001"}
    )
    assert resp_blank.status_code == 400
    resp_no_code = ctx.client.post(
        "/api/admin/schools", json={"name": "学校", "code": ""}
    )
    assert resp_no_code.status_code == 400


def test_admin_schools_list_aggregates_stats(ctx: Any) -> None:
    """admin GET /api/admin/schools：聚合 member_count/batch_count/record/avg。"""
    _as(ctx, "admin")
    s1 = ctx.schools.create_school("示例中学", "SCH001")
    s2 = ctx.schools.create_school("第二中学", "SCH002")
    alice = ctx.users.create_user("alice", "hash", display_name="Alice",
                                  school_id=s1["id"])
    bob = ctx.users.create_user("bob", "hash", display_name="Bob",
                                school_id=s2["id"])
    ctx.activity.link_batch(alice["id"], "task-1", "batch-1")
    ctx.activity.link_batch(bob["id"], "task-2", "batch-2")
    ctx.grades.save_batch("batch-1", "参考答案", BATCH_STATUS_SUCCEEDED, 2,
                          "2026-01-01T00:00:00")
    ctx.grades.save_records([
        _record("r1", "batch-1", 1, 90.0),
        _record("r2", "batch-1", 2, 70.0),
    ])
    ctx.grades.save_batch("batch-2", "参考答案2", BATCH_STATUS_SUCCEEDED, 1,
                          "2026-01-01T00:00:01")
    ctx.grades.save_record(_record("r3", "batch-2", 1, 60.0))

    resp = ctx.client.get("/api/admin/schools")
    assert resp.status_code == 200
    by_id = {item["id"]: item for item in resp.get_json()}
    assert set(by_id) == {s1["id"], s2["id"]}
    assert by_id[s1["id"]]["member_count"] == 1
    assert by_id[s1["id"]]["batch_count"] == 1
    assert by_id[s1["id"]]["record_count"] == 2
    assert by_id[s1["id"]]["avg_score"] == 80.0
    assert by_id[s2["id"]]["member_count"] == 1
    assert by_id[s2["id"]]["batch_count"] == 1
    assert by_id[s2["id"]]["record_count"] == 1
    assert by_id[s2["id"]]["avg_score"] == 60.0


def test_admin_schools_members_200_strips_password_hash(ctx: Any) -> None:
    """admin GET 成员：200，返回成员且无 password_hash。"""
    _as(ctx, "admin")
    s = ctx.schools.create_school("示例中学", "SCH001")
    ctx.users.create_user("alice", "hash-alice", display_name="Alice",
                          school_id=s["id"])
    ctx.users.create_user("bob", "hash-bob", display_name="Bob",
                          school_id=s["id"])
    resp = ctx.client.get(f"/api/admin/schools/{s['id']}/members")
    assert resp.status_code == 200
    members = resp.get_json()
    assert len(members) == 2
    assert all("password_hash" not in member for member in members)
    by_name = {member["display_name"]: member for member in members}
    assert by_name["Alice"]["username"] == "alice"


def test_admin_schools_members_missing_404(ctx: Any) -> None:
    """admin GET 不存在学校成员：404 学校不存在。"""
    _as(ctx, "admin")
    resp = ctx.client.get("/api/admin/schools/no-such-id/members")
    assert resp.status_code == 404


def test_admin_batches_guest_403(ctx: Any) -> None:
    """游客 GET /api/admin/batches：403。"""
    assert ctx.client.get("/api/admin/batches").status_code == 403


def test_admin_batches_filter_by_school(ctx: Any) -> None:
    """GET /api/admin/batches?school_id=：只返回该校批次的聚合。"""
    _as(ctx, "admin")
    s1 = ctx.schools.create_school("示例中学", "SCH001")
    s2 = ctx.schools.create_school("第二中学", "SCH002")
    alice = ctx.users.create_user("alice", "hash", display_name="Alice",
                                  school_id=s1["id"])
    bob = ctx.users.create_user("bob", "hash", display_name="Bob",
                                school_id=s2["id"])
    ctx.activity.link_batch(alice["id"], "task-1", "batch-1")
    ctx.activity.link_batch(bob["id"], "task-2", "batch-2")
    ctx.grades.save_batch("batch-1", "参考答案", BATCH_STATUS_SUCCEEDED, 2,
                          "2026-01-01T00:00:00")
    ctx.grades.save_records([
        _record("r1", "batch-1", 1, 90.0),
        _record("r2", "batch-1", 2, 70.0),
    ])
    ctx.grades.save_batch("batch-2", "参考答案2", BATCH_STATUS_SUCCEEDED, 1,
                          "2026-01-01T00:00:01")
    ctx.grades.save_record(_record("r3", "batch-2", 1, 60.0))

    resp = ctx.client.get(f"/api/admin/batches?school_id={s1['id']}")
    assert resp.status_code == 200
    items = resp.get_json()
    assert [item["batch_id"] for item in items] == ["batch-1"]
    item = items[0]
    assert item["school_id"] == s1["id"]
    assert item["teacher_name"] == "Alice"
    assert item["status"] == BATCH_STATUS_SUCCEEDED
    assert item["record_count"] == 2
    assert item["avg_score"] == 80.0


def test_admin_batches_all_no_filter(ctx: Any) -> None:
    """GET /api/admin/batches 缺省返回全部批次，按创建时间倒序。"""
    _as(ctx, "admin")
    s1 = ctx.schools.create_school("示例中学", "SCH001")
    s2 = ctx.schools.create_school("第二中学", "SCH002")
    alice = ctx.users.create_user("alice", "hash", display_name="Alice",
                                  school_id=s1["id"])
    bob = ctx.users.create_user("bob", "hash", display_name="Bob",
                                school_id=s2["id"])
    ctx.activity.link_batch(alice["id"], "task-1", "batch-old")
    ctx.activity.link_batch(bob["id"], "task-2", "batch-new")
    ctx.grades.save_batch("batch-old", "参考答案", BATCH_STATUS_SUCCEEDED, 1,
                          "2026-01-01T00:00:00")
    ctx.grades.save_record(_record("r1", "batch-old", 1, 70.0))
    ctx.grades.save_batch("batch-new", "参考答案2", BATCH_STATUS_SUCCEEDED, 1,
                          "2026-01-01T00:00:01")
    ctx.grades.save_record(_record("r2", "batch-new", 1, 90.0))

    resp = ctx.client.get("/api/admin/batches")
    assert resp.status_code == 200
    items = resp.get_json()
    assert [item["batch_id"] for item in items] == ["batch-new", "batch-old"]
