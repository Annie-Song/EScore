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

from backend.scoring.eval_set import Question  # noqa: E402


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


def test_tier_prompt_good_允许参照参考答案措辞():
    """good 档提示词允许参照参考答案措辞组织，且无强制改写表述。"""
    good = generate_eval_answers._TIER_PROMPTS["good"]
    assert "参照参考答案的措辞" in good
    assert "用自己的话表达" not in good
    assert good.endswith("只输出作答文本，不要任何解释或质量标注。")


def test_tier_prompt_medium_禁止照抄参考答案():
    """medium 档提示词禁止照抄参考答案原文措辞，并保留部分要点定位。"""
    medium = generate_eval_answers._TIER_PROMPTS["medium"]
    assert "不要直接照抄参考答案的原文措辞" in medium
    assert "用自己的话概括" in medium
    assert "只覆盖部分要点" in medium


def test_tier_prompt_bad_保持低质量定位():
    """bad 档提示词保持答非所问/要点缺失/明显错误定位。"""
    bad = generate_eval_answers._TIER_PROMPTS["bad"]
    assert "答非所问、要点缺失或包含明显错误" in bad


def test_tier_prompt_三档都保留只输出作答文本尾部():
    """三档提示词都以'只输出作答文本'尾部约束结束。"""
    tail = "只输出作答文本，不要任何解释或质量标注。"
    for tier in generate_eval_answers._TIERS:
        assert generate_eval_answers._TIER_PROMPTS[tier].endswith(tail)


def _seed_cache(path: Path, tiers: dict[str, str]) -> None:
    """写入一条 a_subject #1 的预置缓存，供 main 增量/force 场景复用。"""
    payload = {
        "meta": {"count": 1},
        "answers": [
            {
                "subject": "a_subject",
                "index": 1,
                "question": "题干一",
                "reference": "标准答案一",
                "tiers": tiers,
            }
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_main_默认增量跳过已有档位(tmp_path, monkeypatch):
    """不加 --force：缓存已存在的档位被跳过，仅补缺失档位并返回 0。"""
    questions = [
        Question(subject="a_subject", year="2020", category="诗歌",
                 question="题干一", answer="标准答案一", score=5, index=1)
    ]
    monkeypatch.setattr(generate_eval_answers, "load_gaokao_questions", lambda: questions)
    path = tmp_path / "answers.json"
    _seed_cache(path, {"good": "已有优作答"})

    with patch.object(generate_eval_answers, "_generate_answer", return_value="新作答") as gen:
        rc = generate_eval_answers.main(["--out", str(path), "--tiers", "good", "medium", "bad"])

    assert rc == 0
    assert sorted(call.args[2] for call in gen.call_args_list) == ["bad", "medium"]
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["answers"][0]["tiers"] == {
        "good": "已有优作答", "medium": "新作答", "bad": "新作答",
    }


def test_main_force_重生成指定档位并覆盖缓存(tmp_path, monkeypatch):
    """加 --force：--tiers 指定档位即使缓存已存在也重新生成并覆盖。"""
    questions = [
        Question(subject="a_subject", year="2020", category="诗歌",
                 question="题干一", answer="标准答案一", score=5, index=1)
    ]
    monkeypatch.setattr(generate_eval_answers, "load_gaokao_questions", lambda: questions)
    path = tmp_path / "answers.json"
    _seed_cache(path, {"good": "旧优", "medium": "旧中"})

    with patch.object(generate_eval_answers, "_generate_answer", return_value="新作答") as gen:
        rc = generate_eval_answers.main(
            ["--limit", "1", "--out", str(path), "--tiers", "good", "medium", "--force"]
        )

    assert rc == 0
    assert sorted(call.args[2] for call in gen.call_args_list) == ["good", "medium"]
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["answers"][0]["tiers"] == {"good": "新作答", "medium": "新作答"}


def test_main_force_不重生成未指定档位(tmp_path, monkeypatch):
    """--force 只作用于 --tiers 指定档位，bad 档不被强制重生成。"""
    questions = [
        Question(subject="a_subject", year="2020", category="诗歌",
                 question="题干一", answer="标准答案一", score=5, index=1)
    ]
    monkeypatch.setattr(generate_eval_answers, "load_gaokao_questions", lambda: questions)
    path = tmp_path / "answers.json"
    _seed_cache(path, {"good": "已有优", "bad": "已有差"})

    with patch.object(generate_eval_answers, "_generate_answer", return_value="新作答") as gen:
        rc = generate_eval_answers.main(["--out", str(path), "--tiers", "good", "--force"])

    assert rc == 0
    assert [call.args[2] for call in gen.call_args_list] == ["good"]
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["answers"][0]["tiers"] == {"good": "新作答", "bad": "已有差"}
