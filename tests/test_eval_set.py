"""服务层 A9 评测集加载模块（services/eval_set.py）单元测试。

覆盖 GAOKAO-Bench 题库加载（空题过滤、可复现采样、缺失文件报错）与
三档作答缓存读取（字段解析、缺失文件报错），全部用 tmp_path fixture 构造
JSON，monkeypatch 覆盖 config 路径，不触碰真实 data/ 目录。
"""
import json

import pytest

from services import eval_set
from services.eval_set import GeneratedCase, load_gaokao_questions, load_generated_cases


def _make_question(index: int, question: str, answer: str) -> dict:
    """构造一条 GAOKAO 题目条目（与真实文件顶层 example 元素结构一致）。"""
    return {
        "year": "2020",
        "category": "诗歌阅读",
        "question": question,
        "answer": answer,
        "analysis": "解析文本",
        "index": index,
        "score": 5,
    }


def _write_gaokao_file(path, examples: list[dict]) -> None:
    """把题目列表写入 GAOKAO 风格的 JSON 文件（顶层 keywords + example）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"keywords": [], "example": examples}, ensure_ascii=False),
        encoding="utf-8",
    )


def _patch_gaokao_config(monkeypatch, tmp_path, filename: str) -> None:
    """把 eval_set 读取的 config 路径全部指向 tmp_path 下的构造目录。"""
    base = tmp_path / "gaokao"
    base.mkdir(exist_ok=True)
    monkeypatch.setattr(eval_set.config, "EVAL_GAOKAO_DIR", str(tmp_path))
    monkeypatch.setattr(eval_set.config, "EVAL_GAOKAO_SUBJECTIVE_DIR", "gaokao")
    monkeypatch.setattr(eval_set.config, "EVAL_SUBJECT_FILES", [filename])


def test_load_gaokao_questions_过滤空题(tmp_path, monkeypatch):
    """题干或标准答案为空的条目应被剔除，只保留非空题。"""
    filename = "test_poetry.json"
    _write_gaokao_file(
        tmp_path / "gaokao" / filename,
        [
            _make_question(1, "题干一", "答案一"),
            _make_question(2, "", "有答案无题干"),
            _make_question(3, "有题干无答案", ""),
            _make_question(4, "   ", "空白题干"),
            _make_question(5, "空白答案", "  "),
            _make_question(6, "题干六", "答案六"),
        ],
    )
    _patch_gaokao_config(monkeypatch, tmp_path, filename)

    result = load_gaokao_questions()
    assert {q.index for q in result} == {1, 6}
    assert all(q.question and q.answer for q in result)
    assert all(q.subject == filename for q in result)


def test_load_gaokao_questions_采样可复现(tmp_path, monkeypatch):
    """同 seed 两次采样结果完全一致，且 sample_per_file 限制生效。"""
    filename = "test_15.json"
    examples = [_make_question(i, f"题干{i}", f"答案{i}") for i in range(1, 16)]
    _write_gaokao_file(tmp_path / "gaokao" / filename, examples)
    _patch_gaokao_config(monkeypatch, tmp_path, filename)

    first = load_gaokao_questions(sample_per_file=10, seed=42)
    second = load_gaokao_questions(sample_per_file=10, seed=42)
    assert [q.index for q in first] == [q.index for q in second]
    assert len(first) == 10
    assert len({q.index for q in first}) == 10


def test_load_gaokao_questions_缺失文件抛错(tmp_path, monkeypatch):
    """题目文件不存在时应抛 FileNotFoundError（fail-fast）。"""
    _patch_gaokao_config(monkeypatch, tmp_path, "missing.json")
    with pytest.raises(FileNotFoundError):
        load_gaokao_questions()


def test_load_generated_cases_解析字段正确(tmp_path):
    """GeneratedCase 的 subject/index/question/reference/tiers 与缓存一一对应。"""
    path = tmp_path / "answers.json"
    payload = {
        "meta": {"count": 2},
        "answers": [
            {
                "subject": "语文",
                "index": 1,
                "question": "题干一",
                "reference": "标准答案一",
                "tiers": {"good": "优1", "medium": "中1", "bad": "差1"},
            },
            {
                "subject": "数学",
                "index": 2,
                "question": "题干二",
                "reference": "标准答案二",
                "tiers": {"good": "优2"},
            },
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    result = load_generated_cases(path)
    assert result == [
        GeneratedCase(
            subject="语文", index=1, question="题干一", reference="标准答案一",
            tiers={"good": "优1", "medium": "中1", "bad": "差1"},
        ),
        GeneratedCase(
            subject="数学", index=2, question="题干二", reference="标准答案二",
            tiers={"good": "优2"},
        ),
    ]


def test_load_generated_cases_缺失文件抛错(tmp_path):
    """作答缓存文件不存在时应抛 FileNotFoundError（fail-fast）。"""
    with pytest.raises(FileNotFoundError):
        load_generated_cases(tmp_path / "no_such.json")
