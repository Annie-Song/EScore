"""/batch_grade 路由 quality 双档贯通单元测试（run_batch_job 全 mock，同步线程执行）。"""
import io

import pytest
from unittest.mock import patch

from backend.app import create_app


class _SyncThread:
    """替代 threading.Thread 同步执行 target，避免异步竞态。"""

    def __init__(self, target, args, kwargs=None, daemon=None):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self):
        self._target(*self._args, **self._kwargs)


@pytest.fixture
def client():
    """构造 Flask 测试客户端。"""
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
        "backend.auth.session.current_user",
        lambda: {"id": "demo", "plan": "pro", "display_name": "演示"},
    )
    return client


def _multipart(**form_fields):
    """构造 multipart 表单，quality 等纯字段经 form_fields 注入。"""
    data = {
        "file2": (io.BytesIO(b"ref"), "reference.jpg"),
        "files": [
            (io.BytesIO(b"w1"), "work1.png"),
            (io.BytesIO(b"w2"), "work2.png"),
        ],
    }
    data.update(form_fields)
    return data


def _run_post(client, **form_fields):
    """发起 /batch_grade 请求，patch 外部依赖后返回 (resp, mock_run)。"""
    with patch("backend.batch.routes.save_upload",
               side_effect=["/tmp/ref.jpg", "/tmp/w1.png", "/tmp/w2.png"]), \
         patch("threading.Thread", _SyncThread), \
         patch("backend.batch.pipeline.run_batch_job") as mock_run:
        resp = client.post(
            "/batch_grade", data=_multipart(**form_fields),
            content_type="multipart/form-data",
        )
    return resp, mock_run


def test_batch_grade_default_no_quality_passes_fast(pro_client):
    """缺省无 quality 表单字段 → run_batch_job 收到 quality='fast'。"""
    resp, mock_run = _run_post(pro_client)
    assert resp.status_code == 202
    assert "task_id" in resp.get_json()
    mock_run.assert_called_once()
    assert mock_run.call_args.args[-1] == "fast"


def test_batch_grade_quality_quality_passes_quality(pro_client):
    """quality='quality' → run_batch_job 收到 quality='quality'。"""
    resp, mock_run = _run_post(pro_client, quality="quality")
    assert resp.status_code == 202
    mock_run.assert_called_once()
    assert mock_run.call_args.args[-1] == "quality"


def test_batch_grade_invalid_quality_returns_400(client):
    """quality='garbage' → 400 且 message 含未知评分质量，run_batch_job 不被调用。"""
    resp, mock_run = _run_post(client, quality="garbage")
    assert resp.status_code == 400
    message = resp.get_json()["message"]
    assert "未知评分质量" in message
    assert "garbage" in message
    mock_run.assert_not_called()
