"""统计聚合 backend.stats.stats 单元测试。

全部用例通过假 store 返回固定 GradeRecord 列表驱动 analyze_batch，
不触数据库，可离线独立运行。
"""
from backend.stats.stats import analyze_batch
from backend.batch.store import GradeRecord


def _record(record_id: str, batch_id: str, question_no: int, score: float,
            *, work_text: str = "作答文本", error_category: str = "") -> GradeRecord:
    """构造测试用 GradeRecord，未显式指定的字段使用默认值。"""
    return GradeRecord(
        record_id=record_id,
        batch_id=batch_id,
        question_no=question_no,
        work_text=work_text,
        answer_text="标准答案",
        score=score,
        method="offline",
        degraded=False,
        routed=False,
        created_at="2026-01-01T00:00:00",
        error_category=error_category,
        error_reason="",
    )


class _FakeStore:
    """最小 GradeStore 桩：仅实现 analyze_batch 依赖的 list_records。"""

    def __init__(self, records) -> None:
        self._records = list(records)

    def list_records(self, batch_id: str) -> list:
        return self._records


def test_analyze_batch_multi_question_precision_and_order():
    """多题多记录：每题 count/avg/max/min 精确值，且按题号升序。"""
    records = [
        _record("r5", "b1", 2, 59.0, work_text="x=2", error_category="grammar"),
        _record("r1", "b1", 1, 90.0, work_text="x=2"),
        _record("r6", "b1", 2, 0.0, work_text="  ", error_category="math"),
        _record("r3", "b1", 1, 92.5, work_text=""),
        _record("r2", "b1", 1, 91.5, work_text="x=2", error_category="math"),
        _record("r7", "b1", 3, 100.0, work_text="ok", error_category="grammar"),
        _record("r4", "b1", 2, 60.0, work_text="x=2", error_category="grammar"),
    ]
    result = analyze_batch(_FakeStore(records), "b1")

    assert result["questions"] == [
        {
            "question_no": 1, "count": 3, "avg_score": 91.3,
            "max_score": 92.5, "min_score": 90.0,
            "pass_count": 3, "pass_rate": 100.0, "unanswered_count": 1,
        },
        {
            "question_no": 2, "count": 3, "avg_score": 39.7,
            "max_score": 60.0, "min_score": 0.0,
            "pass_count": 1, "pass_rate": 33.3, "unanswered_count": 1,
        },
        {
            "question_no": 3, "count": 1, "avg_score": 100.0,
            "max_score": 100.0, "min_score": 100.0,
            "pass_count": 1, "pass_rate": 100.0, "unanswered_count": 0,
        },
    ]


def test_analyze_batch_pass_rate_boundary_60_pass_59_fail():
    """及格边界：60 恰好及格，59 不及格，pass_rate 保留 1 位小数。"""
    records = [
        _record("p1", "b1", 1, 60.0),
        _record("p2", "b1", 1, 59.0),
        _record("p3", "b1", 1, 59.0),
        _record("p4", "b1", 1, 100.0),
    ]
    result = analyze_batch(_FakeStore(records), "b1")
    q = result["questions"][0]
    assert q["count"] == 4
    assert q["pass_count"] == 2
    assert q["pass_rate"] == 50.0
    assert q["avg_score"] == 69.5


def test_analyze_batch_unanswered_zero_score_or_empty_work():
    """未作答判定：score<=0 或 work_text 空白均计入 unanswered_count。"""
    records = [
        _record("u1", "b1", 1, 0.0, work_text="已提交"),
        _record("u2", "b1", 1, -5.0, work_text="已提交"),
        _record("u3", "b1", 1, 50.0, work_text=""),
        _record("u4", "b1", 1, 50.0, work_text="   "),
        _record("u5", "b1", 1, 80.0, work_text="done"),
    ]
    result = analyze_batch(_FakeStore(records), "b1")
    q = result["questions"][0]
    assert q["unanswered_count"] == 4
    assert q["pass_count"] == 1
    assert q["avg_score"] == 35.0


def test_analyze_batch_categories_count_desc_and_empty_excluded():
    """错因分布：count/avg_score 精确，按 count 倒序，空错因排除。"""
    records = [
        _record("c1", "b1", 1, 90.0, error_category="A"),
        _record("c2", "b1", 2, 80.0, error_category="A"),
        _record("c3", "b1", 3, 70.0, error_category="A"),
        _record("c4", "b1", 4, 60.0, error_category="B"),
        _record("c5", "b1", 5, 50.0),
        _record("c6", "b1", 6, 40.0, error_category="B"),
        _record("c7", "b1", 7, 100.0, error_category="A"),
    ]
    result = analyze_batch(_FakeStore(records), "b1")

    assert result["categories"] == [
        {"error_category": "A", "count": 4, "avg_score": 85.0},
        {"error_category": "B", "count": 2, "avg_score": 50.0},
    ]
    # 空错因记录仍在题目与摘要中计数，但排除在错因分布外
    assert result["summary"]["total_records"] == 7
    assert result["summary"]["question_count"] == 7


def test_analyze_batch_summary_precision():
    """summary 概览：total_records/question_count/avg/max/min 精确值。"""
    records = [
        _record("s1", "b1", 1, 90.0),
        _record("s2", "b1", 2, 80.0),
        _record("s3", "b1", 1, 70.0),
        _record("s4", "b1", 2, 60.0),
    ]
    result = analyze_batch(_FakeStore(records), "b1")
    assert result["summary"] == {
        "total_records": 4,
        "question_count": 2,
        "avg_score": 75.0,
        "max_score": 90.0,
        "min_score": 60.0,
    }


def test_analyze_batch_empty_batch_returns_empty_structure():
    """空批次：questions/categories 为空列表，summary 数值归 0，不抛异常。"""
    result = analyze_batch(_FakeStore([]), "b1")
    assert result == {
        "summary": {
            "total_records": 0,
            "question_count": 0,
            "avg_score": 0,
            "max_score": 0,
            "min_score": 0,
        },
        "questions": [],
        "categories": [],
    }
