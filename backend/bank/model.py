"""题库构建模块（F7）：把 GAOKAO-Bench 全量主客观题归一化为可检索的 BankQuestion。

主观题难度用分值分档；客观题难度以 gpt-4 作答对错为准（结果文件缺失即 fail-fast）。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from backend.bank import tags
from backend.core import config


@dataclass
class BankQuestion:
    """题库单题：含来源、标签、题干/答案/解析与分值，供检索与评分复用。

    school_id 为 NULL 表示全局种子题，非空表示归属该校的校本题。
    """
    qid: str
    subject: str
    qtype: str
    grade: str
    year: str
    region: str
    difficulty: str
    source_type: str
    source_file: str
    question: str
    answer: str
    analysis: str
    score: int
    index: int
    school_id: str | None = None
    created_by: str | None = None
    created_at: str | None = None


_BRACKET_RE = re.compile(r"[()（）]")


def _strip_brackets(text: str) -> str:
    """去掉全角/半角括号（"（新课标）"→"新课标"）。"""
    return _BRACKET_RE.sub("", text).strip()


def _normalize_to_set(value: str | list[str] | None) -> set[str]:
    """把答案（str 或 list）规范化为小写词元集合，用于客观题对错判定。"""
    if value is None:
        return set()
    parts = value if isinstance(value, list) else [value]
    tokens: set[str] = set()
    for part in parts:
        for token in str(part).strip().lower().split():
            tokens.add(token)
    return tokens


def build_gpt4_difficulty_map(gpt4_path: Path) -> dict[int, str]:
    """读取 gpt-4 客观题结果，返回 {index: "基础"/"进阶"}。

    standard_answer 与 model_answer 规范化后集合有交集即判定为正确（"基础"），
    否则为"进阶"。结果文件缺失时抛 FileNotFoundError。
    """
    gpt4_path = Path(gpt4_path)
    if not gpt4_path.exists():
        raise FileNotFoundError(f"gpt-4 客观题结果缺失: {gpt4_path}")
    with gpt4_path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    result: dict[int, str] = {}
    for item in data.get("example", []):
        if "index" not in item:
            continue
        standard = _normalize_to_set(item.get("standard_answer"))
        model = _normalize_to_set(item.get("model_answer"))
        correct = bool(standard & model)
        result[int(item["index"])] = tags.difficulty_from_correctness(correct)
    return result


def parse_questions_from_file(
    path: Path,
    source_type: str,
    gpt4_difficulty: dict[int, str] | None = None,
) -> list[BankQuestion]:
    """解析单个题目 JSON 文件，返回归一化的 BankQuestion 列表。

    科目/题型从文件名派生；题干为空串的条目跳过。客观题难度从 gpt4_difficulty
    按 index 取（缺失则回退分值分档），主观题一律用分值分档。
    """
    path = Path(path)
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    subject = tags.subject_from_filename(path.name)
    qtype = tags.qtype_from_filename(path.name)
    questions: list[BankQuestion] = []
    for item in data.get("example", []):
        question_text = str(item.get("question", "")).strip()
        if not question_text:
            continue
        index = int(item["index"])
        score = int(item["score"])
        if source_type == "objective":
            difficulty = (gpt4_difficulty or {}).get(index)
            if difficulty is None:
                difficulty = tags.difficulty_from_score(score)
        else:
            difficulty = tags.difficulty_from_score(score)
        questions.append(
            BankQuestion(
                qid=f"{subject}-{path.name}-{index}",
                subject=subject,
                qtype=qtype,
                grade=config.QUESTION_BANK_GRADE,
                year=str(item.get("year", "")),
                region=_strip_brackets(str(item.get("category", ""))),
                difficulty=difficulty,
                source_type=source_type,
                source_file=path.name,
                question=question_text,
                answer=str(item.get("answer", "")),
                analysis=str(item.get("analysis", "")),
                score=score,
                index=index,
            )
        )
    return questions


def iter_gaokao_bank() -> list[BankQuestion]:
    """遍历 GAOKAO-Bench 全量主客观题，构建题库。

    主观题难度用分值分档；客观题从 Results/gpt_4_0314_obj 下
    `gpt-4-0314_<文件名>` 结果构建对错难度（缺失即抛 FileNotFoundError）。
    文件按文件名排序保证结果确定性。
    """
    base = Path(config.QUESTION_BANK_GAOKAO_DIR)
    questions: list[BankQuestion] = []

    subjective_dir = base / config.QUESTION_BANK_SUBJECTIVE_DIR
    for path in sorted(subjective_dir.glob("*.json")):
        questions.extend(parse_questions_from_file(path, "subjective"))

    objective_dir = base / config.QUESTION_BANK_OBJECTIVE_DIR
    gpt4_dir = base / config.QUESTION_BANK_GPT4_OBJ_DIR
    for path in sorted(objective_dir.glob("*.json")):
        gpt4_path = gpt4_dir / f"gpt-4-0314_{path.name}"
        gpt4_difficulty = build_gpt4_difficulty_map(gpt4_path)
        questions.extend(
            parse_questions_from_file(path, "objective", gpt4_difficulty)
        )
    return questions
