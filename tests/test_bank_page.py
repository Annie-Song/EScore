"""题库页（templates/bank.html + app/bank_routes.py bank_page 路由）单元测试。

离线独立运行：模板断言直接读 templates 下 html 文本（utf-8），路由渲染断言用
Flask test_client。不访问外网、不依赖真实题库库文件。注意 /bank 页面路由仅
render_template，不实例化 QuestionBankStore，因此即使 output/question_bank.db
缺失也不影响 /bank 返回 200（test_bank路由_不触库 证明）。
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from app import create_app

# 项目根目录 = 本文件（tests/test_bank_page.py）上上级
_BASE_DIR = Path(__file__).resolve().parent.parent
_TEMPLATE_DIR = _BASE_DIR / "templates"


def _read_template(name: str) -> str:
    """读取 templates 下指定模板的全文（utf-8）。"""
    return (_TEMPLATE_DIR / name).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def client() -> Any:
    """模块级共享的 Flask 测试客户端（TESTING 模式）。"""
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_bank路由渲染200(client: Any) -> None:
    """GET /bank 返回 200，HTML 含页面标题与入口文案“分类题库”。"""
    resp = client.get("/bank")
    assert resp.status_code == 200
    assert "分类题库" in resp.get_data(as_text=True)


def test_bank路由_不触库(monkeypatch: pytest.MonkeyPatch) -> None:
    """/bank 仅渲染模板、不实例化题库存储，题库库文件缺失也不影响 200。"""
    from services import question_bank_store

    def _block_init(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("bank_page 不应实例化 QuestionBankStore")

    monkeypatch.setattr(
        question_bank_store.QuestionBankStore, "__init__", _block_init
    )
    app = create_app()
    app.config["TESTING"] = True
    resp = app.test_client().get("/bank")
    assert resp.status_code == 200


def test_bank模板_筛选控件齐全() -> None:
    """筛选栏控件齐全：科目/题型/难度/题目类型下拉、年份/关键词输入、搜索/重置按钮。"""
    html = _read_template("bank.html")
    for control_id, label in (
        ("subject", "科目"),
        ("qtype", "题型"),
        ("difficulty", "难度"),
        ("sourceType", "题目类型"),
        ("year", "年份"),
        ("keyword", "关键词"),
    ):
        assert f'id="{control_id}"' in html, control_id
        assert label in html, label
    assert 'id="searchBtn"' in html
    assert 'id="resetBtn"' in html


def test_bank模板_结果与分页容器() -> None:
    """结果统计区/结果列表/分页容器三个 id 均存在。"""
    html = _read_template("bank.html")
    for element_id in ("resultInfo", "resultList", "pagination"):
        assert f'id="{element_id}"' in html, element_id


def test_bank模板_fetch相对路径无硬编码() -> None:
    """JS fetch 均用相对路径，全文不含 127.0.0.1/localhost:5000。"""
    html = _read_template("bank.html")
    assert "fetch('/api/bank/facets')" in html
    assert "/api/bank/search" in html
    assert "/api/bank/questions/" in html
    assert "127.0.0.1" not in html
    assert "localhost:5000" not in html


def test_bank模板_503与错误提示文案() -> None:
    """包含 503 未构建、非 200 检索失败、空结果未找到三类文案。"""
    html = _read_template("bank.html")
    assert "题库未构建" in html
    assert "检索失败，请重试" in html
    assert "未找到匹配题目" in html


def test_bank模板_主题开关存在() -> None:
    """主题切换控件与 data-theme/localStorage 逻辑存在。"""
    html = _read_template("bank.html")
    assert 'id="themeToggle"' in html
    assert "data-theme" in html
    assert "localStorage" in html
    assert '"theme"' in html


def test_index入口链接() -> None:
    """首页含 href=/bank 分类题库入口。"""
    html = _read_template("index.html")
    assert 'href="/bank"' in html
    assert "分类题库" in html


def test_batch入口链接() -> None:
    """批量批改页含 href=/bank 分类题库入口。"""
    html = _read_template("batch.html")
    assert 'href="/bank"' in html
    assert "分类题库" in html


def test_其他路由未破坏(client: Any) -> None:
    """首页/批量批改/使用教程三个既有页面均 200。"""
    for path in ("/", "/batch", "/guide"):
        assert client.get(path).status_code == 200, path


def test_公开路由数约束() -> None:
    """bank_routes.py 模块级公开函数数 ≤5，当前应为 4。"""
    source = (_BASE_DIR / "app" / "bank_routes.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    public = [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not node.name.startswith("_")
    ]
    assert len(public) <= 5
    assert public == ["bank_facets", "bank_search", "bank_question", "bank_page"]
