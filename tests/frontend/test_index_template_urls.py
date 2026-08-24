"""templates/index.html 前端 fetch URL 相对路径回归测试。

验证实现 agent 将硬编码的 http://127.0.0.1:5000/* 改为相对路径后，
前端不再包含任何本机绝对地址，且三条 fetch 调用均指向相对端点。
"""
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
INDEX_HTML_PATH = PROJECT_ROOT / "frontend" / "templates" / "index.html"


def _read_index_html() -> str:
    """从项目根目录读取 templates/index.html 原始内容。"""
    return INDEX_HTML_PATH.read_text(encoding="utf-8")


def test_index_template_contains_no_hardcoded_localhost():
    """index.html 不再包含 127.0.0.1:5000 硬编码地址。"""
    html = _read_index_html()
    assert "127.0.0.1:5000" not in html


def test_index_template_contains_no_absolute_http_fetch_url():
    """index.html 的 fetch 调用不再使用任何 http(s):// 绝对地址。"""
    html = _read_index_html()
    assert not re.search(r"fetch\(\s*[\"']https?://", html)


def test_index_template_fetch_ocr_uses_relative_path():
    """OCR fetch 调用使用相对路径 /ocr。"""
    html = _read_index_html()
    assert re.search(r'fetch\(\s*"/ocr"', html)


def test_index_template_fetch_compare_texts_uses_relative_path():
    """文本比对 fetch 调用使用相对路径 /compare_texts。"""
    html = _read_index_html()
    assert re.search(r'fetch\(\s*"/compare_texts"', html)


def test_index_template_fetch_download_report_uses_relative_path():
    """下载报告 fetch 调用使用相对路径 /download_report。"""
    html = _read_index_html()
    assert re.search(r'fetch\(\s*"/download_report"', html)
