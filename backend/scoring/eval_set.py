"""评分评测集（A9）加载：GAOKAO-Bench 题库与 DeepSeek 三档生成作答的读取与组织。

GAOKAO-Bench 主观题 JSON 顶层为 {keywords, example}，example 为题目列表，每条含
year/category/question/answer(标准答案)/analysis(解析)/index/score(分值)。本模块把
中文主观题文件归一化为 Question 数据结构，并读取三档生成作答缓存（GeneratedCase），
供 scripts/generate_eval_answers.py 与 scripts/benchmark_eval.py 复用。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from random import Random

from backend.core import config


@dataclass
class Question:
    """评测题目：题干 + 标准答案 + 分值与来源信息。

    subject 为所属中文主观题类别（取文件名），tier_answers 为 DeepSeek 三档
    生成作答（优/中/差），生成后填充。
    """
    subject: str
    year: str
    category: str
    question: str
    answer: str
    score: int
    index: int
    tier_answers: dict[str, str] = field(default_factory=dict)


@dataclass
class GeneratedCase:
    """一条已生成的三档作答样本（对应 data/eval/answers.json 的单个元素）。"""
    subject: str
    index: int
    question: str
    reference: str
    tiers: dict[str, str]


def load_gaokao_questions(
    sample_per_file: int = config.EVAL_SAMPLE_PER_FILE,
    seed: int = 42,
) -> list[Question]:
    """加载 GAOKAO-Bench 中文主观题，每类采样 sample_per_file 道。

    仅保留题干与标准答案均非空的题目；每类文件内部按固定种子采样，保证结果可复现。
    默认覆盖 config.EVAL_SUBJECT_FILES 列出的 6 类中文主观题。
    """
    questions: list[Question] = []
    base = Path(config.EVAL_GAOKAO_DIR) / config.EVAL_GAOKAO_SUBJECTIVE_DIR
    for filename in config.EVAL_SUBJECT_FILES:
        path = base / filename
        if not path.exists():
            raise FileNotFoundError(
                f"评测题库缺失: {path}，请先下载 GAOKAO-Bench 到 data/gaokao/"
            )
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        valid = [
            q for q in data.get("example", [])
            if q.get("question", "").strip() and q.get("answer", "").strip()
        ]
        if sample_per_file:
            valid = Random(seed).sample(valid, min(sample_per_file, len(valid)))
        for q in valid:
            questions.append(
                Question(
                    subject=filename,
                    year=q["year"],
                    category=q["category"],
                    question=q["question"],
                    answer=q["answer"],
                    score=q["score"],
                    index=q["index"],
                )
            )
    return questions


def load_generated_cases(path: str | Path = config.EVAL_ANSWERS_PATH) -> list[GeneratedCase]:
    """读取三档生成作答缓存文件，返回 GeneratedCase 列表。

    文件不存在时抛 FileNotFoundError（fail-fast，需先运行生成脚本）。
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"评测作答缓存缺失: {path}，请先运行 scripts/generate_eval_answers.py"
        )
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    return [
        GeneratedCase(
            subject=item["subject"],
            index=item["index"],
            question=item["question"],
            reference=item["reference"],
            tiers=item["tiers"],
        )
        for item in data["answers"]
    ]
