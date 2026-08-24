"""批量批改统计聚合：基于 GradeRecord 计算题目与错因分布。"""
from __future__ import annotations

from typing import Optional

from backend.batch.store import GradeRecord, GradeStore

_PASS_SCORE = 60.0  # 及格线：百分制得分不低于该值记为通过


def _pass_of(score: float) -> bool:
    """判断得分是否及格。"""
    return score >= _PASS_SCORE


def _unanswered_of(record: GradeRecord) -> bool:
    """判断记录是否为未作答：零分或作答文本为空。"""
    return record.score <= 0 or not (record.work_text or "").strip()


def _round_or(value: Optional[float]) -> Optional[float]:
    """数值保留 1 位小数，None 原样返回。"""
    return round(value, 1) if value is not None else None


def analyze_batch(store: GradeStore, batch_id: str) -> dict:
    """基于批改记录聚合统计，返回 {summary, questions, categories}。

    questions 按题号分组并升序排列，categories 按数量倒序；
    批次无记录时返回空结构，summary 数值归 0。不吞异常。
    """
    records = store.list_records(batch_id)

    questions: dict[int, dict] = {}
    categories: dict[str, dict] = {}
    for record in records:
        _accumulate_question(questions, record)
        if record.error_category:
            _accumulate_category(categories, record)

    question_list = [
        _format_question(item)
        for item in sorted(questions.values(), key=lambda item: item["question_no"])
    ]
    category_list = [
        _format_category(item)
        for item in sorted(categories.values(), key=lambda item: item["count"], reverse=True)
    ]

    return {
        "summary": _build_summary(records, len(question_list)),
        "questions": question_list,
        "categories": category_list,
    }


def _accumulate_question(questions: dict, record: GradeRecord) -> None:
    """按题号累加单条记录的分值、及格数与未作答数。"""
    item = questions.setdefault(
        record.question_no,
        {
            "question_no": record.question_no,
            "count": 0,
            "total": 0.0,
            "max_score": None,
            "min_score": None,
            "pass_count": 0,
            "unanswered_count": 0,
        },
    )
    item["count"] += 1
    item["total"] += record.score
    item["max_score"] = record.score if item["max_score"] is None else max(item["max_score"], record.score)
    item["min_score"] = record.score if item["min_score"] is None else min(item["min_score"], record.score)
    if _pass_of(record.score):
        item["pass_count"] += 1
    if _unanswered_of(record):
        item["unanswered_count"] += 1


def _accumulate_category(categories: dict, record: GradeRecord) -> None:
    """按错因累加记录数与总分。"""
    item = categories.setdefault(
        record.error_category,
        {"error_category": record.error_category, "count": 0, "total": 0.0},
    )
    item["count"] += 1
    item["total"] += record.score


def _format_question(item: dict) -> dict:
    """将题内累加结果格式化为对外统计字段。"""
    return {
        "question_no": item["question_no"],
        "count": item["count"],
        "avg_score": round(item["total"] / item["count"], 1),
        "max_score": _round_or(item["max_score"]),
        "min_score": _round_or(item["min_score"]),
        "pass_count": item["pass_count"],
        "pass_rate": round(item["pass_count"] / item["count"] * 100, 1),
        "unanswered_count": item["unanswered_count"],
    }


def _format_category(item: dict) -> dict:
    """将错因累加结果格式化为对外统计字段。"""
    return {
        "error_category": item["error_category"],
        "count": item["count"],
        "avg_score": round(item["total"] / item["count"], 1),
    }


def _build_summary(records: list[GradeRecord], question_count: int) -> dict:
    """汇总全批次概览数值，无记录时各项归 0。"""
    if not records:
        return {
            "total_records": 0,
            "question_count": 0,
            "avg_score": 0,
            "max_score": 0,
            "min_score": 0,
        }
    scores = [record.score for record in records]
    return {
        "total_records": len(records),
        "question_count": question_count,
        "avg_score": round(sum(scores) / len(records), 1),
        "max_score": round(max(scores), 1),
        "min_score": round(min(scores), 1),
    }
