"""统计查询与统计报告 Flask 路由单元测试。"""
import pytest

import backend.stats.routes as stats_routes
from backend.app import create_app
from backend.batch.record_store import SqliteGradeStore
from backend.batch.store import BATCH_STATUS_SUCCEEDED, GradeRecord


def _record(record_id: str, batch_id: str, question_no: int, score: float,
            *, error_category: str = "") -> GradeRecord:
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
        error_category=error_category,
        error_reason="",
    )


def _seed(store: SqliteGradeStore) -> None:
    """预置一个批次与三条记录。"""
    store.save_batch("batch-1", "参考答案", BATCH_STATUS_SUCCEEDED, 2,
                     "2026-01-01T00:00:00")
    store.save_records([
        _record("r1", "batch-1", 1, 90.0, error_category="grammar"),
        _record("r2", "batch-1", 1, 85.0, error_category="grammar"),
        _record("r3", "batch-1", 2, 60.0, error_category="math"),
    ])


@pytest.fixture
def client(monkeypatch, tmp_path):
    """monkeypatch 统计路由的 default_store 指向临时 SQLite 库。"""
    db_path = str(tmp_path / "stats_routes.db")
    store = SqliteGradeStore(db_path)
    _seed(store)
    monkeypatch.setattr(stats_routes, "default_store", lambda: store)
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_list_batches_returns_200_with_batch(client):
    """GET /batches → 200 且含批次。"""
    resp = client.get("/batches")
    assert resp.status_code == 200
    batches = resp.get_json()
    assert [b["batch_id"] for b in batches] == ["batch-1"]


def test_batch_stats_existing_returns_200_structure(client):
    """GET /stats/<存在的 batch_id> → 200，questions/categories/summary 结构正确。"""
    resp = client.get("/stats/batch-1")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["summary"]["total_records"] == 3
    assert body["summary"]["question_count"] == 2
    assert [q["question_no"] for q in body["questions"]] == [1, 2]
    assert body["questions"][0] == {
        "question_no": 1, "count": 2, "avg_score": 87.5,
        "max_score": 90.0, "min_score": 85.0,
        "pass_count": 2, "pass_rate": 100.0, "unanswered_count": 0,
    }
    assert [c["error_category"] for c in body["categories"]] == ["grammar", "math"]


def test_batch_stats_missing_returns_404(client):
    """GET /stats/<不存在的 batch_id> → 404。"""
    resp = client.get("/stats/no-such-batch")
    assert resp.status_code == 404


def test_batch_records_existing_returns_200_with_records(client):
    """GET /batch_records/<存在的 id> → 200 且记录数正确。"""
    resp = client.get("/batch_records/batch-1")
    assert resp.status_code == 200
    records = resp.get_json()
    assert len(records) == 3
    assert {r["record_id"] for r in records} == {"r1", "r2", "r3"}


def test_stats_report_html_returns_200_attachment(client):
    """POST /stats_report format=html → 200，text/html 下载响应。"""
    resp = client.post("/stats_report",
                       json={"batch_id": "batch-1", "format": "html"})
    assert resp.status_code == 200
    assert "text/html" in resp.content_type
    assert "attachment" in resp.headers.get("Content-Disposition", "")
    assert "批改统计报告" in resp.data.decode("utf-8")


def test_stats_report_docx_returns_200_docx_download(client, monkeypatch, tmp_path):
    """POST /stats_report format=docx → 200，docx mimetype 且文件可下载。"""
    monkeypatch.setattr(stats_routes, "REPORT_FOLDER", str(tmp_path / "reports"))
    resp = client.post("/stats_report",
                       json={"batch_id": "batch-1", "format": "docx"})
    assert resp.status_code == 200
    assert ("wordprocessingml" in resp.content_type)
    assert resp.data[:2] == b"PK"
    resp.close()


def test_stats_report_illegal_format_returns_400(client):
    """POST /stats_report 非法 format → 400。"""
    resp = client.post("/stats_report",
                       json={"batch_id": "batch-1", "format": "pdf"})
    assert resp.status_code == 400
    assert resp.get_json() == {"message": "不支持的下载格式"}


def test_stats_report_missing_batch_id_returns_400(client):
    """POST /stats_report 缺 batch_id → 400。"""
    resp = client.post("/stats_report", json={"format": "html"})
    assert resp.status_code == 400
    assert resp.get_json() == {"message": "缺少批次 ID"}


def test_batch_page_returns_200(client):
    """GET /batch → 200，批量页可访问。"""
    resp = client.get("/batch")
    assert resp.status_code == 200
    assert "批量作业批改" in resp.data.decode("utf-8")
