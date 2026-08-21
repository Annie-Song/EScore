"""个人主页与个人卷库 Flask 路由单元测试（task/22）。

覆盖 /me 页面渲染、/api/me 聚合、/api/favorites 收藏增删查三类接口：
游客空态、登录态聚合联查、401 门控、400 参数校验、重复收藏幂等。
存储隔离：monkeypatch me_routes.default_store / default_user_activity_store
指向 tmp_path 临时库，auth.current_user 注入构造用户，离线独立运行，不触碰
真实 output/users.db 与 output/grades.db。
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import app.me_routes as me_routes
from app import create_app
from services import auth
from services.sqlite_store import SqliteGradeStore
from services.store import BATCH_STATUS_RUNNING, BATCH_STATUS_SUCCEEDED, GradeRecord
from services.user_activity_store import UserActivityStore

USER_ID = "u-1"


def _make_user(**overrides: Any) -> dict:
    """构造测试用户字典（含 password_hash，验证响应剔除）。"""
    user = {
        "id": USER_ID,
        "username": "alice",
        "password_hash": "hashed",
        "display_name": "Alice",
        "role": "teacher",
        "plan": "pro",
        "school_id": None,
        "avatar": None,
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
    }
    user.update(overrides)
    return user


def _record(record_id: str, batch_id: str, question_no: int, score: float) -> GradeRecord:
    """构造测试用 GradeRecord。"""
    return GradeRecord(
        record_id=record_id,
        batch_id=batch_id,
        question_no=question_no,
        work_text="作答文本",
        answer_text="标准答案",
        score=score,
        method="offline",
        degraded=False,
        routed=False,
        created_at="2026-01-01T00:00:00",
    )


@pytest.fixture
def client() -> Any:
    """基础 Flask 测试客户端（无存储 mock，用于游客与页面用例）。"""
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def me_client(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Any:
    """隔离存储的测试上下文：活动库/成绩库指向 tmp，current_user 可注入。"""
    activity = UserActivityStore(str(tmp_path / "activity.db"))
    grades = SqliteGradeStore(str(tmp_path / "grades.db"))
    monkeypatch.setattr(me_routes, "default_user_activity_store", lambda: activity)
    monkeypatch.setattr(me_routes, "default_store", lambda: grades)
    holder: dict = {"user": None}
    monkeypatch.setattr(auth, "current_user", lambda: holder["user"])
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield SimpleNamespace(
            client=c, activity=activity, grades=grades, holder=holder
        )


def _login(c: Any) -> None:
    """写入会话 user_id，模拟登录态。"""
    with c.session_transaction() as sess:
        sess["user_id"] = USER_ID


def test_me_page_guest_200(client: Any) -> None:
    """游客 GET /me：200 且渲染出个人主页。"""
    resp = client.get("/me")
    assert resp.status_code == 200
    assert "个人主页" in resp.get_data(as_text=True)


def test_me_page_logged_in_200(client: Any) -> None:
    """登录态 GET /me：200。"""
    _login(client)
    assert client.get("/me").status_code == 200


def test_api_me_guest_empty(client: Any) -> None:
    """游客 GET /api/me：200，user=None，统计/最近批次/收藏全空态。"""
    resp = client.get("/api/me")
    assert resp.status_code == 200
    assert resp.get_json() == {
        "user": None,
        "plan": "free",
        "stats": {
            "batch_count": 0,
            "record_count": 0,
            "avg_score": 0.0,
            "favorite_count": 0,
        },
        "recent_batches": [],
        "favorites": [],
    }


def test_api_me_logged_in_user_fields(me_client: Any) -> None:
    """登录用户 GET /api/me：user 公开字段正确且无 password_hash。"""
    me_client.holder["user"] = _make_user(plan="free")
    resp = me_client.client.get("/api/me")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["user"] == {
        "id": USER_ID,
        "username": "alice",
        "display_name": "Alice",
        "role": "teacher",
        "plan": "free",
        "school_id": None,
        "avatar": None,
        "created_at": "2026-01-01T00:00:00",
    }
    assert "password_hash" not in body["user"]
    assert body["plan"] == "free"
    assert body["stats"]["favorite_count"] == 0
    assert body["recent_batches"] == []
    assert body["favorites"] == []


def test_api_me_aggregate_stats_and_recent(me_client: Any) -> None:
    """登录用户聚合联查：批次统计/最近批次正确，缺失批次跳过。"""
    me_client.holder["user"] = _make_user(plan="pro")
    grades = me_client.grades
    activity = me_client.activity

    grades.save_batch(
        "batch-1", "参考答案", BATCH_STATUS_SUCCEEDED, 2, "2026-01-01T00:00:00"
    )
    grades.save_records([
        _record("r1", "batch-1", 1, 90.0),
        _record("r2", "batch-1", 2, 70.0),
    ])
    grades.save_batch(
        "batch-2", "参考答案2", BATCH_STATUS_RUNNING, 1, "2026-01-01T00:00:01"
    )
    grades.save_record(_record("r3", "batch-2", 1, 60.0))
    # 关联三个批次，其中 batch-missing 在 grades.db 不存在 → 应跳过
    activity.link_batch(USER_ID, "task-1", "batch-1")
    activity.link_batch(USER_ID, "task-2", "batch-2")
    activity.link_batch(USER_ID, "task-3", "batch-missing")
    activity.add_favorite(
        USER_ID, "q1", subject="数学", qtype="解答题", question="题干1", score=10
    )

    resp = me_client.client.get("/api/me")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["plan"] == "pro"
    assert body["stats"] == {
        "batch_count": 2,      # batch-missing 被跳过
        "record_count": 3,
        "avg_score": 73.3,     # (90+70+60)/3
        "favorite_count": 1,
    }
    by_id = {item["batch_id"]: item for item in body["recent_batches"]}
    assert set(by_id) == {"batch-1", "batch-2"}
    assert by_id["batch-1"]["task_id"] == "task-1"
    assert by_id["batch-1"]["status"] == BATCH_STATUS_SUCCEEDED
    assert by_id["batch-1"]["total_questions"] == 2
    assert by_id["batch-1"]["record_count"] == 2
    assert by_id["batch-1"]["avg_score"] == 80.0
    assert by_id["batch-2"]["task_id"] == "task-2"
    assert by_id["batch-2"]["status"] == BATCH_STATUS_RUNNING
    assert by_id["batch-2"]["record_count"] == 1
    assert by_id["batch-2"]["avg_score"] == 60.0
    assert body["favorites"][0]["qid"] == "q1"


def test_favorites_guest_all_401(client: Any) -> None:
    """游客 GET/POST/DELETE /api/favorites 均返回 401。"""
    assert client.get("/api/favorites").status_code == 401
    assert client.post("/api/favorites", json={"qid": "q1"}).status_code == 401
    assert client.delete("/api/favorites/q1").status_code == 401


def test_favorites_post_missing_qid_400(me_client: Any) -> None:
    """登录用户 POST /api/favorites 缺 qid：400。"""
    _login(me_client.client)
    resp = me_client.client.post("/api/favorites", json={"subject": "数学"})
    assert resp.status_code == 400
    assert resp.get_json()["message"] == "缺少题目 ID"


def test_favorites_post_add_201_repeat_200(me_client: Any) -> None:
    """登录用户 POST 收藏：首次 201，重复 200，score 转整数入库。"""
    _login(me_client.client)
    resp = me_client.client.post("/api/favorites", json={
        "qid": "q1",
        "subject": "数学",
        "qtype": "解答题",
        "question": "题干",
        "score": "85.6",
    })
    assert resp.status_code == 201
    assert resp.get_json() == {"ok": True}
    rows = me_client.activity.list_favorites(USER_ID)
    assert len(rows) == 1
    assert rows[0]["qid"] == "q1"
    assert rows[0]["score"] == 85
    # 重复收藏 → 200，不产生重复行
    resp2 = me_client.client.post("/api/favorites", json={"qid": "q1"})
    assert resp2.status_code == 200
    assert len(me_client.activity.list_favorites(USER_ID)) == 1


def test_favorites_get_list(me_client: Any) -> None:
    """登录用户 GET /api/favorites：返回收藏列表，无 user_id 内部字段。"""
    me_client.activity.add_favorite(
        USER_ID, "q1", subject="数学", qtype="解答题", question="题干1", score=10
    )
    me_client.activity.add_favorite(
        USER_ID, "q2", subject="语文", qtype="选择题", question="题干2", score=5
    )
    _login(me_client.client)
    resp = me_client.client.get("/api/favorites")
    assert resp.status_code == 200
    items = resp.get_json()
    by_qid = {item["qid"]: item for item in items}
    assert set(by_qid) == {"q1", "q2"}
    assert by_qid["q1"]["subject"] == "数学"
    assert by_qid["q2"]["question"] == "题干2"
    assert "user_id" not in items[0]


def test_favorites_delete_removes_200(me_client: Any) -> None:
    """登录用户 DELETE /api/favorites/<qid>：200 并删除收藏。"""
    me_client.activity.add_favorite(USER_ID, "q1", subject="数学")
    _login(me_client.client)
    resp = me_client.client.delete("/api/favorites/q1")
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}
    assert me_client.activity.list_favorites(USER_ID) == []
