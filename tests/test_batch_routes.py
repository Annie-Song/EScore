"""批量批改 Flask 路由单元测试。"""
import io

import pytest
from unittest.mock import patch

from app import create_app

import services.task_store as task_store


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
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def pro_client(client, monkeypatch):
    """带 pro 档会话的客户端：session 写 user_id，current_user 返回 pro 档。"""
    with client.session_transaction() as sess:
        sess["user_id"] = "demo"
        sess["display_name"] = "演示"
        sess["role"] = "teacher"
        sess["plan"] = "pro"
    monkeypatch.setattr(
        "services.auth.current_user",
        lambda: {"id": "demo", "plan": "pro", "display_name": "演示"},
    )
    return client


def _multipart(file2_name: str, work_names) -> dict:
    data = {"file2": (io.BytesIO(b"ref-image"), file2_name)}
    if work_names:
        data["files"] = [(io.BytesIO(b"work-image"), name) for name in work_names]
    return data


def test_batch_grade_missing_file2_returns_400(client):
    """缺参考答案图 → 400。"""
    resp = client.post("/batch_grade", data=_multipart(None, ["w.png"]),
                       content_type="multipart/form-data")
    assert resp.status_code == 400
    assert resp.get_json()["message"] == "缺少参考答案图片"


def test_batch_grade_missing_file2_with_no_work_files_returns_400(client):
    """完全空表单 → 400（缺 file2 优先）。"""
    resp = client.post("/batch_grade", data={}, content_type="multipart/form-data")
    assert resp.status_code == 400
    assert resp.get_json()["message"] == "缺少参考答案图片"


def test_batch_grade_empty_files_returns_400(client):
    """作业图列表为空 → 400。"""
    resp = client.post("/batch_grade", data=_multipart("ref.jpg", []),
                       content_type="multipart/form-data")
    assert resp.status_code == 400
    assert resp.get_json()["message"] == "缺少作业图片"


def test_batch_grade_invalid_file2_suffix_returns_400(client):
    """参考答案图后缀非法 → 400。"""
    resp = client.post("/batch_grade", data=_multipart("ref.exe", ["w.png"]),
                       content_type="multipart/form-data")
    assert resp.status_code == 400
    assert resp.get_json()["message"] == "不支持的文件类型"


def test_batch_grade_invalid_work_suffix_returns_400(client):
    """作业图后缀非法 → 400。"""
    resp = client.post("/batch_grade", data=_multipart("ref.jpg", ["w.exe", "w2.png"]),
                       content_type="multipart/form-data")
    assert resp.status_code == 400
    assert resp.get_json()["message"] == "不支持的文件类型"


def test_batch_grade_success_returns_202_and_creates_task(pro_client):
    """成功提交：202 + task_id，任务已创建，后台线程被调用且归属 user_id 传入。"""
    data = {
        "file2": (io.BytesIO(b"ref"), "reference.jpg"),
        "files": [
            (io.BytesIO(b"w1"), "work1.png"),
            (io.BytesIO(b"w2"), "work2.png"),
        ],
    }
    with patch("app.batch_routes.save_upload",
               side_effect=["/tmp/ref.jpg", "/tmp/w1.png", "/tmp/w2.png"]), \
         patch("threading.Thread", _SyncThread), \
         patch("services.batch.run_batch_job") as mock_run:
        resp = pro_client.post("/batch_grade", data=data, content_type="multipart/form-data")

    assert resp.status_code == 202
    body = resp.get_json()
    assert "task_id" in body
    task = task_store.get_task(body["task_id"])
    assert task is not None
    assert task["status"] == "running"
    assert task["total_items"] == 2
    mock_run.assert_called_once()
    assert mock_run.call_args.args == (
        body["task_id"], "/tmp/ref.jpg", ["/tmp/w1.png", "/tmp/w2.png"], "en", False, False, "fast"
    )
    assert mock_run.call_args.kwargs == {"user_id": "demo"}


def test_batch_task_existing_id_returns_200_with_status(client):
    """查询已存在任务 → 200 且含 status。"""
    task_id = task_store.create_task(3)
    resp = client.get(f"/batch_task/{task_id}")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["task_id"] == task_id
    assert body["status"] == "running"
    assert body["total_items"] == 3


def test_batch_task_missing_id_returns_404(client):
    """查询不存在任务 → 404。"""
    resp = client.get("/batch_task/no-such-task")
    assert resp.status_code == 404


def test_home_route_still_available(client):
    """现有首页路由回归：GET / 仍可用。"""
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"<!DOCTYPE html>" in resp.data
