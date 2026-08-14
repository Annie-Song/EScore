"""templates/index.html 首次访问引导横幅（guide banner）单元测试。

独立验证实现 agent 的 F6 前端体验优化：
1. 页面包含引导横幅容器 div.guide-banner#guideBanner（默认 display:none）。
2. 横幅含指向 /guide 与 /batch 的两个入口链接。
3. 横幅含关闭按钮（#guideBannerClose）。
4. JS 含 localStorage 显示/关闭逻辑（guide_banner_dismissed）。
5. 既有 fetch 相对路径端点（/ocr、/compare_texts、/download_report）未回归。
6. GET / 仍可正常渲染，返回 200。
"""
import re
from pathlib import Path

from app import create_app

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML_PATH = PROJECT_ROOT / "templates" / "index.html"


def _read_index_html() -> str:
    """从项目根目录读取 templates/index.html 原始内容。"""
    return INDEX_HTML_PATH.read_text(encoding="utf-8")


def test_index_template_contains_guide_banner_container():
    """index.html 包含引导横幅容器 div.guide-banner#guideBanner。"""
    html = _read_index_html()
    assert 'class="guide-banner"' in html
    assert 'id="guideBanner"' in html


def test_index_template_guide_banner_hidden_by_default():
    """引导横幅默认不可见：CSS 与内联样式均为 display:none。"""
    html = _read_index_html()
    assert re.search(r"\.guide-banner\s*\{\s*display:\s*none", html)
    assert '<div class="guide-banner" id="guideBanner" style="display: none">' in html


def test_index_template_guide_banner_has_guide_link():
    """引导横幅内包含指向 /guide 的入口链接。"""
    html = _read_index_html()
    assert '<a href="/guide" class="guide-banner-link">查看使用教程</a>' in html


def test_index_template_guide_banner_has_batch_link():
    """引导横幅内包含指向 /batch 的入口链接。"""
    html = _read_index_html()
    assert (
        '<a href="/batch" class="guide-banner-link guide-banner-primary">去批量批改</a>'
        in html
    )


def test_index_template_guide_banner_has_close_button():
    """引导横幅内包含关闭按钮（id 与 class 均存在）。"""
    html = _read_index_html()
    assert 'class="guide-banner-close" id="guideBannerClose"' in html


def test_index_template_guide_banner_has_css_subclasses():
    """引导横幅 CSS 子类样式齐全。"""
    html = _read_index_html()
    for subclass in (
        "guide-banner-content",
        "guide-banner-title",
        "guide-banner-desc",
        "guide-banner-actions",
        "guide-banner-link",
        "guide-banner-primary",
        "guide-banner-close",
    ):
        assert f".{subclass}" in html


def test_index_template_guide_banner_js_reads_dismiss_flag():
    """JS 显示逻辑读取 localStorage 的 guide_banner_dismissed 标记。"""
    html = _read_index_html()
    assert 'localStorage.getItem("guide_banner_dismissed")' in html
    assert "banner.style.display = \"block\"" in html


def test_index_template_guide_banner_js_sets_dismiss_flag_on_close():
    """JS 关闭逻辑写入 localStorage 的 guide_banner_dismissed=1。"""
    html = _read_index_html()
    assert 'localStorage.setItem("guide_banner_dismissed", "1")' in html
    assert "banner.style.display = \"none\"" in html


def test_index_template_fetch_ocr_uses_relative_path():
    """OCR fetch 调用仍使用相对路径 /ocr，未回归硬编码绝对地址。"""
    html = _read_index_html()
    assert re.search(r'fetch\(\s*"/ocr"', html)


def test_index_template_fetch_compare_texts_uses_relative_path():
    """文本比对 fetch 调用仍使用相对路径 /compare_texts。"""
    html = _read_index_html()
    assert re.search(r'fetch\(\s*"/compare_texts"', html)


def test_index_template_fetch_download_report_uses_relative_path():
    """下载报告 fetch 调用仍使用相对路径 /download_report。"""
    html = _read_index_html()
    assert re.search(r'fetch\(\s*"/download_report"', html)


def test_index_template_contains_no_hardcoded_localhost():
    """index.html 仍不包含 127.0.0.1:5000 硬编码地址。"""
    html = _read_index_html()
    assert "127.0.0.1:5000" not in html


def test_index_template_renders_successfully():
    """GET / 正常渲染首页，返回 200。"""
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.mimetype == "text/html"
        html = resp.get_data(as_text=True)
        assert 'id="guideBanner"' in html
