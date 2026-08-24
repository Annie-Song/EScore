"""templates/batch.html 识别参数卡片说明文字与选项完整性测试。

验证实现 agent 为评分质量、智能分区、AI 错因归类三个选项补充的
说明文字存在，原有选项（fast/quality、enableSegment、errorAiMode）
未被破坏，且 GET /batch 仍可正常渲染。
"""
from pathlib import Path

from backend.app import create_app

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BATCH_HTML_PATH = PROJECT_ROOT / "frontend" / "templates" / "batch.html"


def _read_batch_html() -> str:
    """从项目根目录读取 templates/batch.html 原始内容。"""
    return BATCH_HTML_PATH.read_text(encoding="utf-8")


def test_batch_template_quality_mode_description_present():
    """评分质量说明文字：含两档区别关键句。"""
    html = _read_batch_html()
    assert "快速版：低分才转精排，更快更省；高质版：更多作答转精排，更准但更慢。" in html


def test_batch_template_enable_segment_description_present():
    """智能分区说明文字：含按题号自动切分为独立区域关键句。"""
    html = _read_batch_html()
    assert "勾选后，一张含多道题的作业图会按题号自动切分为独立区域" in html


def test_batch_template_error_ai_mode_description_present():
    """AI 错因归类说明文字：含自动归类常见错因与需调用在线模型关键句。"""
    html = _read_batch_html()
    assert "勾选后，系统会对低分作答自动归类常见错因" in html
    assert "需调用在线模型" in html


def test_batch_template_quality_mode_options_intact():
    """评分质量 select（id=qualityMode）仍保留 fast/quality 两个选项。"""
    html = _read_batch_html()
    assert 'id="qualityMode"' in html
    assert '<option value="fast">' in html
    assert '<option value="quality">' in html


def test_batch_template_enable_segment_option_intact():
    """智能分区复选框（id=enableSegment）仍存在。"""
    html = _read_batch_html()
    assert 'id="enableSegment"' in html


def test_batch_template_error_ai_mode_option_intact():
    """AI 错因归类复选框（id=errorAiMode）仍存在。"""
    html = _read_batch_html()
    assert 'id="errorAiMode"' in html


def test_batch_route_renders_template():
    """GET /batch 返回 200，模板可正常渲染。"""
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        resp = client.get("/batch")
    assert resp.status_code == 200
    assert b"<!DOCTYPE html>" in resp.data
