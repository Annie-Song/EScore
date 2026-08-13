"""报告生成模块单元测试（HTML 与 Word 两种报告）。"""
from docx import Document

from services.report import build_report_docx, build_report_html


def _sample_data(**overrides):
    data = {
        "work_content": "小明通过移项和合并同类项解出了 2x+3=7。",
        "answer_content": "2x+3=7 移项得 2x=4，解得 x=2。",
        "score": 85,
        "method": "online",
        "degraded": False,
        "routed": True,
        "generated_at": "2026-08-14T08:00:00",
    }
    data.update(overrides)
    return data


def test_build_report_html_contains_title_score_and_online_label():
    html = build_report_html(_sample_data())
    assert "作业批改报告" in html
    assert "85" in html
    assert "在线 DeepSeek 精排" in html
    assert "小明通过移项和合并同类项解出了 2x+3=7。" in html
    assert "2x+3=7 移项得 2x=4，解得 x=2。" in html
    assert "是否降级：否" in html
    assert "是否路由精排：是" in html


def test_build_report_html_offline_method_shows_offline_label():
    html = build_report_html(_sample_data(method="offline"))
    assert "离线向量相似度" in html
    assert "在线 DeepSeek 精排" not in html


def test_build_report_html_escapes_work_content_special_chars():
    html = build_report_html(
        _sample_data(work_content="<script>alert(1)</script> & <b>粗体</b>")
    )
    assert "<script" not in html
    assert "&lt;script" in html
    assert "&amp;" in html
    assert "&lt;b&gt;" in html


def test_build_report_html_unknown_method_shown_as_is():
    html = build_report_html(_sample_data(method="hybrid"))
    assert "hybrid" in html


def test_build_report_html_missing_method_shows_unknown():
    html = build_report_html(_sample_data(method=None))
    assert "未知" in html


def test_build_report_html_missing_score_shows_default_dash():
    data = _sample_data()
    del data["score"]
    html = build_report_html(data)
    assert "--" in html


def test_build_report_docx_writes_openable_file_with_content(tmp_path):
    out_path = tmp_path / "report.docx"
    returned = build_report_docx(
        _sample_data(score=92, method="offline"), str(out_path)
    )
    assert returned == str(out_path)
    assert out_path.exists()

    doc = Document(str(out_path))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "作业批改报告" in text
    assert "92" in text
    assert "离线向量相似度" in text
    assert "是否降级：否" in text
    assert "是否路由精排：是" in text
    assert "小明通过移项和合并同类项解出了 2x+3=7。" in text
    assert "2x+3=7 移项得 2x=4，解得 x=2。" in text
