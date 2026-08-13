"""POST /download_report 路由单元测试。"""
import gc
import glob
import os

import pytest

from app import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def _payload(**overrides):
    payload = {
        "workContent": "小明通过移项和合并同类项解出了 2x+3=7。",
        "answerContent": "2x+3=7 移项得 2x=4，解得 x=2。",
        "score": 85,
        "method": "online",
        "degraded": False,
        "routed": True,
    }
    payload.update(overrides)
    return payload


def test_download_report_html_returns_200_with_attachment(client):
    resp = client.post("/download_report", json=_payload())
    assert resp.status_code == 200
    assert "text/html" in resp.content_type
    assert "attachment" in resp.headers.get("Content-Disposition", "")
    body = resp.data.decode("utf-8")
    assert "作业批改报告" in body
    assert "85" in body
    assert "在线 DeepSeek 精排" in body


def test_download_report_docx_returns_200_with_docx_content(client, monkeypatch, tmp_path):
    monkeypatch.setattr("app.routes.REPORT_FOLDER", str(tmp_path / "reports"))
    resp = client.post("/download_report", json=_payload(format="docx"))
    assert resp.status_code == 200
    assert "wordprocessingml" in resp.content_type
    assert resp.data[:2] == b"PK"


def test_download_report_illegal_format_returns_400(client):
    resp = client.post("/download_report", json=_payload(format="pdf"))
    assert resp.status_code == 400
    assert resp.get_json() == {"message": "不支持的下载格式"}


def test_download_report_missing_work_content_returns_400(client):
    resp = client.post("/download_report", json=_payload(workContent=""))
    assert resp.status_code == 400
    assert resp.get_json() == {"message": "缺少作业内容或参考答案内容"}


def test_download_report_missing_answer_content_returns_400(client):
    resp = client.post("/download_report", json=_payload(answerContent=None))
    assert resp.status_code == 400
    assert resp.get_json() == {"message": "缺少作业内容或参考答案内容"}


def test_download_report_empty_body_returns_400(client):
    resp = client.post("/download_report", json={})
    assert resp.status_code == 400
    assert resp.get_json() == {"message": "请求体不能为空"}


def test_download_report_non_json_body_returns_400(client):
    resp = client.post(
        "/download_report", data="{broken json", content_type="application/json"
    )
    assert resp.status_code == 400


def test_download_report_docx_default_config_returns_200_docx(client):
    """回归：不 monkeypatch REPORT_FOLDER，走默认相对路径配置。

    验证 send_file 对相对路径绝对化（os.path.abspath）后写读一致，
    默认配置下 docx 下载不再 500。用例会真实落盘 output/reports/，
    finally 中清理本用例产生的文件与目录，避免污染仓库。
    """
    reports_dir = os.path.abspath(os.path.join("output", "reports"))
    existed_before = os.path.isdir(reports_dir)
    files_before = set(glob.glob(os.path.join(reports_dir, "*")))
    resp = None
    try:
        resp = client.post("/download_report", json=_payload(format="docx"))
        assert resp.status_code == 200
        assert "wordprocessingml" in resp.content_type
        assert resp.data[:2] == b"PK"
    finally:
        # send_file 的响应在 Windows 上会持有 docx 文件句柄，先关闭响应并触发 GC
        # 释放句柄，否则 os.remove 会因文件被占用而失败，残留文件污染仓库。
        if resp is not None:
            try:
                resp.close()
            except OSError:
                pass
        del resp
        gc.collect()
        files_after = set(glob.glob(os.path.join(reports_dir, "*")))
        for path in files_after - files_before:
            try:
                os.remove(path)
            except OSError:
                pass
        if not existed_before and os.path.isdir(reports_dir):
            try:
                os.rmdir(reports_dir)
            except OSError:
                pass
