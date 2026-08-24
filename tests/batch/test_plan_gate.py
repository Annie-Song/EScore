"""会员门控 + 批量归属路由级单元测试（task/20）。

覆盖 /batch_grade 的 pro 档 402 门控、pro 会话 202 归属 user_id，
以及 /compare_texts 按档位向 grade_answer 传递 allow_online。
mock 目标取调用方命名空间：batch_routes 顶层 `from backend.core.files import
save_upload` 绑定为 backend.batch.routes.save_upload；routes 顶层
`from backend.scoring.engine import grade_answer` 绑定为 backend.grading.routes.grade_answer。
"""
import io

import pytest
from unittest.mock import patch

from backend.app import create_app

import backend.batch.task_store as task_store


class _SyncThread:
    """替代 threading.Thread 同步执行 target，避免异步竞态。"""

    def __init__(self, target, args, kwargs=None, daemon=None):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self):
        self._target(*self._args, **self._kwargs)


@pytest.fixture(autouse=True)
def _reset_tasks():
    """每轮测试前清空任务注册表，保证用例隔离。"""
    task_store._tasks.clear()
    yield
    task_store._tasks.clear()


@pytest.fixture
def client():
    """构造 Flask 测试客户端（游客会话）。"""
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _session_user(client, plan: str):
    """向测试客户端写入指定档位的会话（user_id=demo）。"""
    with client.session_transaction() as sess:
        sess["user_id"] = "demo"
        sess["display_name"] = "演示"
        sess["role"] = "teacher"
        sess["plan"] = plan
    return {"id": "demo", "plan": plan, "display_name": "演示"}


@pytest.fixture
def pro_client(client, monkeypatch):
    """带 pro 档会话的客户端：current_user 返回 pro 档。"""
    _session_user(client, "pro")
    monkeypatch.setattr(
        "backend.auth.session.current_user",
        lambda: {"id": "demo", "plan": "pro", "display_name": "演示"},
    )
    return client


@pytest.fixture
def free_client(client, monkeypatch):
    """带 free 档会话的客户端：current_user 返回 free 档。"""
    _session_user(client, "free")
    monkeypatch.setattr(
        "backend.auth.session.current_user",
        lambda: {"id": "demo", "plan": "free", "display_name": "演示"},
    )
    return client


def _multipart() -> dict:
    """构造 /batch_grade 合法 multipart 表单（2 份作业图）。"""
    return {
        "file2": (io.BytesIO(b"ref"), "reference.jpg"),
        "files": [
            (io.BytesIO(b"w1"), "work1.png"),
            (io.BytesIO(b"w2"), "work2.png"),
        ],
    }


def _compare_payload(**overrides) -> dict:
    """构造 /compare_texts 合法请求体。"""
    payload = {
        "workContent": "小明解方程 2x+3=7 得 x=2",
        "answerContent": "2x+3=7 移项得 2x=4，解得 x=2",
    }
    payload.update(overrides)
    return payload


def _full_result(score: float = 88.5) -> dict:
    """构造 grade_answer 的完整返回结构。"""
    return {"score": score, "method": "offline", "degraded": False, "routed": False}


# ---------- /batch_grade 会员门控 ----------


def test_batch_grade_guest_valid_post_returns_402_plan_required(client):
    """游客合法提交 → 402 + code=PLAN_REQUIRED，任务不创建，run_batch_job 不被调用。"""
    with patch("backend.batch.routes.save_upload",
               side_effect=["/tmp/ref.jpg", "/tmp/w1.png", "/tmp/w2.png"]), \
         patch("threading.Thread", _SyncThread), \
         patch("backend.batch.pipeline.run_batch_job") as mock_run:
        resp = client.post("/batch_grade", data=_multipart(),
                           content_type="multipart/form-data")
    assert resp.status_code == 402
    body = resp.get_json()
    assert body["code"] == "PLAN_REQUIRED"
    assert "升级专业版" in body["message"]
    assert task_store._tasks == {}
    mock_run.assert_not_called()


def test_batch_grade_pro_session_returns_202_with_user_id(pro_client):
    """pro 会话合法提交 → 202，run_batch_job 收到 kwargs user_id='demo'。"""
    with patch("backend.batch.routes.save_upload",
               side_effect=["/tmp/ref.jpg", "/tmp/w1.png", "/tmp/w2.png"]), \
         patch("threading.Thread", _SyncThread), \
         patch("backend.batch.pipeline.run_batch_job") as mock_run:
        resp = pro_client.post("/batch_grade", data=_multipart(),
                               content_type="multipart/form-data")
    assert resp.status_code == 202
    body = resp.get_json()
    assert "task_id" in body
    assert task_store.get_task(body["task_id"]) is not None
    mock_run.assert_called_once()
    assert mock_run.call_args.kwargs == {"user_id": "demo"}


def test_batch_grade_free_session_returns_402(free_client):
    """free 档会话合法提交 → 402，run_batch_job 不被调用。"""
    with patch("backend.batch.routes.save_upload",
               side_effect=["/tmp/ref.jpg", "/tmp/w1.png", "/tmp/w2.png"]), \
         patch("threading.Thread", _SyncThread), \
         patch("backend.batch.pipeline.run_batch_job") as mock_run:
        resp = free_client.post("/batch_grade", data=_multipart(),
                                content_type="multipart/form-data")
    assert resp.status_code == 402
    assert resp.get_json()["code"] == "PLAN_REQUIRED"
    mock_run.assert_not_called()


# ---------- /compare_texts allow_online 透传 ----------


def test_compare_texts_guest_passes_allow_online_false(client):
    """游客 → grade_answer 收到 allow_online=False。"""
    with patch("backend.grading.routes.grade_answer",
               return_value=_full_result()) as mock_grade:
        resp = client.post("/compare_texts", json=_compare_payload())
    assert resp.status_code == 200
    mock_grade.assert_called_once()
    assert mock_grade.call_args.kwargs["allow_online"] is False


def test_compare_texts_free_session_passes_allow_online_false(free_client):
    """free 档会话 → grade_answer 收到 allow_online=False。"""
    with patch("backend.grading.routes.grade_answer",
               return_value=_full_result()) as mock_grade:
        resp = free_client.post("/compare_texts", json=_compare_payload())
    assert resp.status_code == 200
    mock_grade.assert_called_once()
    assert mock_grade.call_args.kwargs["allow_online"] is False


def test_compare_texts_pro_session_passes_allow_online_true(pro_client):
    """pro 档会话 → grade_answer 收到 allow_online=True。"""
    with patch("backend.grading.routes.grade_answer",
               return_value=_full_result()) as mock_grade:
        resp = pro_client.post("/compare_texts", json=_compare_payload())
    assert resp.status_code == 200
    mock_grade.assert_called_once()
    assert mock_grade.call_args.kwargs["allow_online"] is True


def test_compare_texts_free_force_online_returns_200_allow_online_false(free_client):
    """free 档显式 forceOnline=true → 200（优雅降级非 402），allow_online=False。"""
    with patch("backend.grading.routes.grade_answer",
               return_value=_full_result()) as mock_grade:
        resp = free_client.post(
            "/compare_texts", json=_compare_payload(forceOnline=True)
        )
    assert resp.status_code == 200
    mock_grade.assert_called_once()
    assert mock_grade.call_args.kwargs["allow_online"] is False
    assert mock_grade.call_args.kwargs["force_online"] is True
