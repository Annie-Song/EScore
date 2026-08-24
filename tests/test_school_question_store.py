"""校本题库存储（services/school_question_store.py）单元测试。

全部用例通过 pytest tmp_path 构造临时空库，离线独立运行，不触碰真实
output/question_bank.db。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.question_bank import BankQuestion
from services.question_bank_store import QuestionBankStore
from services.school_question_store import SchoolQuestionStore
from utils import config

_GRADE = config.QUESTION_BANK_GRADE


def _global_q(qid: str, subject: str = "生物") -> BankQuestion:
    """构造一条全局种子题（school_id 默认 None）。"""
    return BankQuestion(
        qid=qid, subject=subject, qtype="解答题", grade=_GRADE, year="2020",
        region="全国", difficulty="基础", source_type="subjective",
        source_file="source.json", question=f"全局题干{qid}", answer="答案",
        analysis="解析", score=5, index=0,
    )


def _fields(**overrides: str | int) -> dict:
    """构造校本题提交字段，默认合法值。"""
    base: dict = {
        "subject": "数学（理）",
        "qtype": "解答题",
        "difficulty": "进阶",
        "question": "求 f(x)=x^2 的导数。",
        "answer": "f'(x)=2x",
        "score": 10,
    }
    base.update(overrides)
    return base


@pytest.fixture()
def ctx(tmp_path) -> SimpleNamespace:
    """在 tmp_path 下建空库，返回 store 与 db_path。"""
    db_path = str(tmp_path / "school.db")
    store = SchoolQuestionStore(db_path)
    return SimpleNamespace(db_path=db_path, store=store)


def test_create_返回dict含校题字段(ctx: SimpleNamespace) -> None:
    """create 返回 dict：qid 带 sch_ 前缀，含 school_id/created_by/created_at/source_type。"""
    result = ctx.store.create(
        _fields(), school_id="schA", created_by="u-1"
    )
    assert result["qid"].startswith("sch_")
    assert result["school_id"] == "schA"
    assert result["created_by"] == "u-1"
    assert result["created_at"]
    assert result["source_type"] == "school"
    assert result["subject"] == "数学（理）"
    assert result["score"] == 10
    assert result["difficulty"] == "进阶"


def test_create_能被QuestionBankStore按校检索(ctx: SimpleNamespace) -> None:
    """create 后 QuestionBankStore.search(visible_school_id=该校) 可查到，全局范围查不到。"""
    result = ctx.store.create(
        _fields(question="校题题干"), school_id="schA", created_by="u-1"
    )
    qs = QuestionBankStore(ctx.db_path)
    assert [r["qid"] for r in qs.search(visible_school_id="schA")] == [result["qid"]]
    assert qs.search() == []  # 全局范围不返回校题
    assert qs.get(result["qid"])["school_id"] == "schA"


def test_delete_返回行数且再查无(ctx: SimpleNamespace) -> None:
    """delete 返回 1，删除后再查为空；删除不存在的 qid 返回 0。"""
    result = ctx.store.create(
        _fields(), school_id="schA", created_by="u-1"
    )
    assert ctx.store.delete(result["qid"]) == 1
    assert ctx.store.get(result["qid"]) is None
    assert ctx.store.delete("sch_no_such") == 0


def test_create多条与全局题互不干扰(ctx: SimpleNamespace) -> None:
    """插入多条校题与全局题：全局范围不返回校题，各校只能看到本校与全局。"""
    ctx.store.insert_many([_global_q("g-1"), _global_q("g-2")])
    a1 = ctx.store.create(_fields(question="A 校题1"), school_id="schA", created_by="u-a")
    a2 = ctx.store.create(_fields(question="A 校题2"), school_id="schA", created_by="u-a")
    b1 = ctx.store.create(_fields(question="B 校题"), school_id="schB", created_by="u-b")

    qs = QuestionBankStore(ctx.db_path)
    # 全局范围：只含 2 条全局种子题
    assert {r["qid"] for r in qs.search(limit=50)} == {"g-1", "g-2"}
    assert qs.count() == 2
    # 学校 A：全局 + 本校 2 条
    qids_a = {r["qid"] for r in qs.search(visible_school_id="schA", limit=50)}
    assert qids_a == {"g-1", "g-2", a1["qid"], a2["qid"]}
    assert qs.count(visible_school_id="schA") == 4
    # 学校 B：全局 + 本校 1 条，看不到 A 的校题
    qids_b = {r["qid"] for r in qs.search(visible_school_id="schB", limit=50)}
    assert qids_b == {"g-1", "g-2", b1["qid"]}
    assert a1["qid"] not in qids_b
