"""评测作答生成脚本（scripts/generate_eval_answers.py）单元测试。

覆盖 DeepSeek 作答生成（返回/空文本报错）、增量缓存读取（缺失返回空、字段解析）
与规范落盘（meta/answers 结构）。get_client 与 load_gaokao_questions 全部 mock。
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import generate_eval_answers  # noqa: E402

from services.eval_set import Question  # noqa: E402


class _FakeMessage:
    def __init__(self, content: str):
        self.content = content


class _FakeChoice:
    def __init__(self, content: str):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content: str):
        self.choices = [_FakeChoice(content)]


def _make_client(content: str) -> MagicMock:
    client = MagicMock()
    client.chat.completions.create.return_value = _FakeResponse(content)
    return client


def test_generate_answer_返回文本():
    """_generate_answer 返回 strip 后的作答文本，并以 deepseek-chat 模型调用。"""
    client = _make_client("  优秀作答  ")
    with patch.object(generate_eval_answers, "get_client", return_value=client):
        text = generate_eval_answers._generate_answer("题干", "参考答案", "good")
    assert text == "优秀作答"

    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "deepseek-chat"
    assert kwargs["messages"][0]["role"] == "system"
    assert "good" not in kwargs["messages"][0]["content"]


def test_generate_answer_空文本抛错():
    """DeepSeek 返回空白作答时应抛 RuntimeError（fail-fast）。"""
    client = _make_client("   ")
    with patch.object(generate_eval_answers, "get_client", return_value=client):
        with pytest.raises(RuntimeError):
            generate_eval_answers._generate_answer("题干", "参考答案", "good")


def test_load_existing_缺失文件返回空dict(tmp_path):
    """缓存文件不存在时 _load_existing 返回空 dict（增量续跑首跑）。"""
    assert generate_eval_answers._load_existing(tmp_path / "missing.json") == {}


def test_load_existing_解析缓存(tmp_path):
    """_load_existing 把 answers 列表解析为 {(subject, index): tiers}。"""
    path = tmp_path / "answers.json"
    payload = {
        "meta": {"count": 2},
        "answers": [
            {"subject": "语文", "index": 1, "tiers": {"good": "优1", "medium": "中1", "bad": "差1"}},
            {"subject": "数学", "index": 2, "tiers": {"good": "优2"}},
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    result = generate_eval_answers._load_existing(path)
    assert result == {
        ("语文", 1): {"good": "优1", "medium": "中1", "bad": "差1"},
        ("数学", 2): {"good": "优2"},
    }


def test_write_cache_规范落盘(tmp_path, monkeypatch):
    """_write_cache 写出顶层 meta/answers 结构，answers 含题目上下文与三档作答。"""
    questions = [
        Question(subject="a_subject", year="2020", category="诗歌", question="题干一",
                 answer="标准答案一", score=5, index=1),
        Question(subject="b_subject", year="2020", category="立体几何", question="题干二",
                 answer="标准答案二", score=6, index=2),
    ]
    monkeypatch.setattr(generate_eval_answers, "load_gaokao_questions", lambda: questions)
    cache = {
        ("a_subject", 1): {"good": "优1", "medium": "中1", "bad": "差1"},
        ("b_subject", 2): {"good": "优2"},
        ("c_subject", 99): {"good": "无对应题目"},  # 题库无此题，落盘时被过滤
    }
    out = tmp_path / "answers.json"
    generate_eval_answers._write_cache(out, cache)

    data = json.loads(out.read_text(encoding="utf-8"))
    assert "meta" in data and "answers" in data
    assert data["meta"]["count"] == 3  # count 统计缓存键数（含被过滤项）
    assert len(data["answers"]) == 2

    first, second = data["answers"]
    assert first["subject"] == "a_subject"
    assert first["index"] == 1
    assert first["question"] == "题干一"
    assert first["reference"] == "标准答案一"
    assert first["tiers"] == {"good": "优1", "medium": "中1", "bad": "差1"}
    assert second["subject"] == "b_subject"
    assert second["reference"] == "标准答案二"
