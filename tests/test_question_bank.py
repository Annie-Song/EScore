"""题库构建模块（services/question_bank.py）单元测试。

用 tmp_path 构造小型题目 JSON 与 gpt-4 结果 JSON，monkeypatch 覆盖 config
路径，不触碰真实 data/gaokao 目录，离线可独立运行。
"""
import json

import pytest

from services import question_bank
from services.question_bank import (
    BankQuestion,
    build_gpt4_difficulty_map,
    iter_gaokao_bank,
    parse_questions_from_file,
)
from utils import config


def _write_json(path, payload: dict) -> None:
    """把 payload 以 UTF-8 写入 path（自动创建父目录）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _make_gpt4_item(
    index: int, standard_answer, model_answer, with_index: bool = True
) -> dict:
    """构造一条 gpt-4 客观题结果（str 或 list 作答，缺 index 可选）。"""
    item: dict = {"standard_answer": standard_answer, "model_answer": model_answer}
    if with_index:
        item["index"] = index
    return item


def test_build_gpt4_difficulty_map_对错判定(tmp_path) -> None:
    """正确/错误/空作答分别映射基础/进阶/进阶，且忽略大小写与多余空格。"""
    gpt4_path = tmp_path / "gpt4_obj.json"
    _write_json(
        gpt4_path,
        {
            "example": [
                _make_gpt4_item(1, "A B", "a  c"),  # 大小写+多余空格仍判正确
                _make_gpt4_item(2, "A", "B"),  # 错误
                _make_gpt4_item(3, "A", ""),  # 空作答
                _make_gpt4_item(4, ["A", "B"], ["A"]),  # list 作答，交集非空
                _make_gpt4_item(5, "A", "A", with_index=False),  # 缺 index 跳过
            ]
        },
    )

    result = build_gpt4_difficulty_map(gpt4_path)
    assert result == {1: "基础", 2: "进阶", 3: "进阶", 4: "基础"}


def test_build_gpt4_difficulty_map_文件缺失抛异常(tmp_path) -> None:
    """gpt-4 结果文件不存在应抛 FileNotFoundError。"""
    with pytest.raises(FileNotFoundError):
        build_gpt4_difficulty_map(tmp_path / "no_such.json")


def _write_question_file(path, examples: list[dict]) -> None:
    """把题目列表写入 GAOKAO 风格 JSON（顶层 keywords + example）。"""
    _write_json(path, {"keywords": [], "example": examples})


def _make_question(
    index: int,
    question: str,
    *,
    year: int = 2020,
    category: str = "（新课标）",
    answer: str = "标准答案",
    analysis: str = "解析文本",
    score: int = 15,
) -> dict:
    """构造一条题目条目，默认带括号 region 与高学分值。"""
    return {
        "year": year,
        "category": category,
        "question": question,
        "answer": answer,
        "analysis": analysis,
        "index": index,
        "score": score,
    }


def test_parse_主观题_字段归一(tmp_path) -> None:
    """主观题各字段归一：region 去括号、year/score/index 类型、qid 拼接等。"""
    filename = "2010-2022_Math_I_Open-ended_Questions.json"
    path = tmp_path / filename
    _write_question_file(
        path,
        [
            _make_question(
                0,
                "求 f(x)=x^2 的导数。",
                year=2020,
                category="（新课标）",
                answer="2x",
                analysis="幂函数求导法则。",
                score=15,
            )
        ],
    )

    result = parse_questions_from_file(path, "subjective")
    assert len(result) == 1
    q = result[0]
    assert isinstance(q, BankQuestion)
    assert q.qid == f"数学（理）-{filename}-0"
    assert q.subject == "数学（理）"
    assert q.qtype == "解答题"
    assert q.grade == config.QUESTION_BANK_GRADE
    assert q.year == "2020"
    assert isinstance(q.year, str)
    assert q.region == "新课标"
    assert q.source_type == "subjective"
    assert q.source_file == filename
    assert q.question == "求 f(x)=x^2 的导数。"
    assert q.answer == "2x"
    assert q.analysis == "幂函数求导法则。"
    assert q.score == 15
    assert isinstance(q.score, int)
    assert q.index == 0
    assert isinstance(q.index, int)
    assert q.difficulty == "进阶"  # 15 >= 12 分值分档


def test_parse_主观题_region全半角括号_均去除(tmp_path) -> None:
    """region 全角与半角括号都应去除（"（新课标）" 与 "(全国)" 归一）。"""
    filename = "2010-2022_Physics_Open-ended_Questions.json"
    path = tmp_path / filename
    _write_question_file(
        path,
        [
            _make_question(0, "题干全角括号", category="（新课标）"),
            _make_question(1, "题干半角括号", category="(全国)"),
            _make_question(2, "题干无括号", category="自主命题"),
        ],
    )

    regions = [q.region for q in parse_questions_from_file(path, "subjective")]
    assert regions == ["新课标", "全国", "自主命题"]


def test_parse_题干空串跳过(tmp_path) -> None:
    """题干为空串/纯空白的条目应被跳过，非空条目保留。"""
    filename = "2010-2022_Chemistry_Open-ended_Questions.json"
    path = tmp_path / filename
    _write_question_file(
        path,
        [
            _make_question(0, ""),  # 空串题干
            _make_question(1, "   "),  # 纯空白题干
            _make_question(2, "非空题干"),
        ],
    )

    result = parse_questions_from_file(path, "subjective")
    assert [q.index for q in result] == [2]
    assert result[0].question == "非空题干"


def test_parse_客观题难度取gpt4(tmp_path) -> None:
    """客观题难度优先取 gpt4 映射，未命中 index 回退分值分档。"""
    filename = "2010-2022_Physics_MCQs.json"
    path = tmp_path / filename
    _write_question_file(
        path,
        [
            _make_question(0, "题干一", score=5),
            _make_question(1, "题干二", score=5),
        ],
    )

    result = parse_questions_from_file(path, "objective", {0: "进阶"})
    assert len(result) == 2
    assert result[0].difficulty == "进阶"  # 命中 gpt4 映射
    assert result[1].difficulty == "基础"  # 未命中，5 < 6 回退基础
    assert all(q.source_type == "objective" for q in result)


def test_parse_文件缺失抛异常(tmp_path) -> None:
    """题目文件不存在应抛 FileNotFoundError。"""
    with pytest.raises(FileNotFoundError):
        parse_questions_from_file(tmp_path / "missing.json", "subjective")


def test_iter_gaokao_bank_全量(tmp_path, monkeypatch) -> None:
    """遍历题库：主观+客观各一文件，客观题难度来自 gpt4 结果。"""
    base = tmp_path / "gaokao"
    monkeypatch.setattr(config, "QUESTION_BANK_GAOKAO_DIR", str(base))
    monkeypatch.setattr(config, "QUESTION_BANK_SUBJECTIVE_DIR", "Data/Subjective_Questions")
    monkeypatch.setattr(config, "QUESTION_BANK_OBJECTIVE_DIR", "Data/Objective_Questions")
    monkeypatch.setattr(config, "QUESTION_BANK_GPT4_OBJ_DIR", "Results/gpt_4_0314_obj")

    subj_path = (
        base / "Data" / "Subjective_Questions" / "2014-2022_English_Language_Cloze_Passage.json"
    )
    _write_question_file(subj_path, [_make_question(0, "完形题干", score=15)])

    obj_path = base / "Data" / "Objective_Questions" / "2010-2022_Physics_MCQs.json"
    _write_question_file(
        obj_path,
        [_make_question(0, "物理选择一", score=5), _make_question(1, "物理选择二", score=5)],
    )

    gpt4_path = (
        base
        / "Results"
        / "gpt_4_0314_obj"
        / "gpt-4-0314_2010-2022_Physics_MCQs.json"
    )
    _write_json(
        gpt4_path,
        {
            "example": [
                _make_gpt4_item(0, "A", "A"),  # 正确 → 基础
                _make_gpt4_item(1, "A", "B"),  # 错误 → 进阶
            ]
        },
    )

    result = iter_gaokao_bank()
    assert len(result) == 3  # 1 主观 + 2 客观

    subj = [q for q in result if q.source_type == "subjective"]
    obj = [q for q in result if q.source_type == "objective"]
    assert len(subj) == 1
    assert len(obj) == 2

    assert subj[0].subject == "英语"
    assert subj[0].qtype == "完形填空"
    assert subj[0].difficulty == "进阶"  # 15 >= 12

    by_index = {q.index: q for q in obj}
    assert by_index[0].difficulty == "基础"  # gpt4 正确
    assert by_index[1].difficulty == "进阶"  # gpt4 错误


def test_bankquestion_租户字段默认None() -> None:
    """BankQuestion 新增 school_id/created_by/created_at 默认 None。"""
    q = BankQuestion(
        qid="x", subject="生物", qtype="解答题", grade="高中", year="2020",
        region="全国", difficulty="基础", source_type="subjective",
        source_file="s.json", question="题干", answer="答案", analysis="解析",
        score=5, index=0,
    )
    assert q.school_id is None
    assert q.created_by is None
    assert q.created_at is None


def test_bankquestion_租户字段传入保留() -> None:
    """传入 school_id/created_by/created_at 后按值保留。"""
    q = BankQuestion(
        qid="x", subject="生物", qtype="解答题", grade="高中", year="2020",
        region="全国", difficulty="基础", source_type="subjective",
        source_file="s.json", question="题干", answer="答案", analysis="解析",
        score=5, index=0,
        school_id="schA", created_by="u-1", created_at="2026-08-25T00:00:00",
    )
    assert q.school_id == "schA"
    assert q.created_by == "u-1"
    assert q.created_at == "2026-08-25T00:00:00"
