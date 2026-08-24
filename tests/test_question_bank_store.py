"""分类题库 SQLite 存储（services/question_bank_store.py）单元测试。

全部用例通过 pytest tmp_path 构造临时空库，插入覆盖多维度的小型题库，
离线独立运行，不触碰真实 output/question_bank.db。
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import astuple, fields

import pytest

from backend.bank.model import BankQuestion
from backend.bank.store import QuestionBankStore
from backend.core import config

_GRADE = config.QUESTION_BANK_GRADE


def _q(
    qid: str,
    subject: str,
    qtype: str,
    difficulty: str,
    source_type: str,
    year: str,
    *,
    question: str = "题干",
    answer: str = "答案",
    analysis: str = "解析",
    score: int = 5,
    index: int = 0,
    region: str = "全国",
    school_id: str | None = None,
    created_by: str | None = None,
    created_at: str | None = None,
) -> BankQuestion:
    """构造测试用 BankQuestion，未显式指定的字段使用默认值。"""
    return BankQuestion(
        qid=qid,
        subject=subject,
        qtype=qtype,
        grade=_GRADE,
        year=year,
        region=region,
        difficulty=difficulty,
        source_type=source_type,
        source_file="source.json",
        question=question,
        answer=answer,
        analysis=analysis,
        score=score,
        index=index,
        school_id=school_id,
        created_by=created_by,
        created_at=created_at,
    )


def _base_rows() -> list[BankQuestion]:
    """返回覆盖不同 subject/qtype/difficulty/source_type/year 的基础题库（8 条）。"""
    return [
        _q(
            "bio-1", "生物", "解答题", "进阶", "subjective", "2020",
            question="线粒体是细胞能量工厂 Mitochondria",
            answer="有氧呼吸", analysis="线粒体通过有氧呼吸供能。", score=15,
        ),
        _q(
            "bio-2", "生物", "选择题", "基础", "objective", "2019",
            question="孟德尔遗传定律", answer="A", analysis="分离定律", score=5,
            index=1,
        ),
        _q(
            "math-1", "数学（理）", "解答题", "中等", "subjective", "2021",
            question="求导运算", answer="导数", analysis="求导法则", score=8,
        ),
        _q(
            "math-2", "数学（理）", "选择题", "进阶", "objective", "2022",
            question="解析几何圆锥曲线", answer="B", analysis="联立方程", score=5,
            index=1,
        ),
        _q(
            "phy-1", "物理", "解答题", "基础", "subjective", "2018",
            question="牛顿第二定律", answer="F=ma", analysis="受力分析", score=5,
        ),
        _q(
            "phy-2", "物理", "选择题", "中等", "objective", "2020",
            question="电磁感应", answer="C", analysis="法拉第定律", score=5,
            index=1,
        ),
        _q(
            "chem-1", "化学", "解答题", "进阶", "subjective", "2019",
            question="化学平衡常数", answer="K", analysis="勒夏特列原理", score=15,
        ),
        _q(
            "eng-1", "英语", "选择题", "基础", "objective", "2021",
            question="The mitochondria produce energy", answer="D",
            analysis="grammar clause", score=5,
        ),
    ]


@pytest.fixture()
def store(tmp_path) -> QuestionBankStore:
    """在 tmp_path 下建空库并插入基础题库（8 条）。"""
    s = QuestionBankStore(str(tmp_path / "qb.db"))
    s.insert_many(_base_rows())
    return s


def test_insert_and_count(tmp_path) -> None:
    """插入 N 条后 count()==N；重复插入同 qid 不翻倍（INSERT OR REPLACE）。"""
    s = QuestionBankStore(str(tmp_path / "count.db"))
    rows = _base_rows()
    assert s.insert_many(rows) == len(rows)
    assert s.count() == len(rows)
    s.insert_many(rows)  # 同 qid 重复插入应覆盖不翻倍
    assert s.count() == len(rows)


def test_get_按qid(store) -> None:
    """get 命中返回 dict 且字段齐全（含 index/score）；未命中返回 None。"""
    row = store.get("bio-1")
    assert row is not None
    for key in (
        "qid", "subject", "qtype", "grade", "year", "region", "difficulty",
        "source_type", "source_file", "question", "answer", "analysis",
        "score", "index",
    ):
        assert key in row
    assert row["qid"] == "bio-1"
    assert row["index"] == 0
    assert row["score"] == 15
    assert store.get("no-such-qid") is None


def test_search_按单一字段过滤(store) -> None:
    """subject/qtype/difficulty/source_type/year 各自过滤条数正确。"""
    assert len(store.search(subject="生物")) == 2
    assert len(store.search(qtype="解答题")) == 4
    assert len(store.search(difficulty="进阶")) == 3
    assert len(store.search(source_type="subjective")) == 4
    assert len(store.search(year="2020")) == 2


def test_search_多条件组合过滤(store) -> None:
    """多条件组合过滤结果与 count() 一致，且无命中返回空。"""
    params = dict(subject="生物", difficulty="进阶", source_type="subjective")
    assert len(store.search(**params)) == store.count(**params) == 1
    params = dict(subject="数学（理）", difficulty="基础", source_type="objective")
    assert len(store.search(**params)) == store.count(**params) == 0


def test_search_关键词LIKE(store) -> None:
    """keyword 命中题干/答案/解析三条不同记录；英文大小写不敏感；无命中空列表。"""
    assert [r["qid"] for r in store.search(keyword="牛顿")] == ["phy-1"]  # 题干
    assert [r["qid"] for r in store.search(keyword="有氧呼吸")] == ["bio-1"]  # 答案
    assert [r["qid"] for r in store.search(keyword="法拉第")] == ["phy-2"]  # 解析
    assert {r["qid"] for r in store.search(keyword="mitochondria")} == {
        "bio-1", "eng-1",
    }  # 小写命中大写 Mitochondria
    assert store.search(keyword="不存在的词xyz") == []


def test_search_分页(tmp_path) -> None:
    """limit/offset 分页正确；limit 超 200 被钳到 200；offset 越界返回空。"""
    s = QuestionBankStore(str(tmp_path / "page.db"))
    rows = [
        _q(f"bulk-{i}", "生物", "解答题", "基础", "subjective", "2000", index=i)
        for i in range(205)
    ]
    s.insert_many(rows)
    assert [r["qid"] for r in s.search(limit=2, offset=0)] == ["bulk-0", "bulk-1"]
    assert [r["qid"] for r in s.search(limit=2, offset=4)] == ["bulk-4", "bulk-5"]
    assert len(s.search(limit=300, offset=0)) == 200  # 上限钳制
    assert s.search(limit=10, offset=10000) == []  # offset 越界


def test_facets_维度与降序(store) -> None:
    """facets 各维度含预期 value/count，且按 count 降序排列。"""
    facets = store.facets()
    assert {(i["value"], i["count"]) for i in facets["subjects"]} == {
        ("生物", 2), ("数学（理）", 2), ("物理", 2), ("化学", 1), ("英语", 1),
    }
    assert {(i["value"], i["count"]) for i in facets["qtypes"]} == {
        ("解答题", 4), ("选择题", 4),
    }
    assert {(i["value"], i["count"]) for i in facets["difficulties"]} == {
        ("进阶", 3), ("基础", 3), ("中等", 2),
    }
    assert {(i["value"], i["count"]) for i in facets["source_types"]} == {
        ("subjective", 4), ("objective", 4),
    }
    for key in ("subjects", "qtypes", "difficulties", "source_types"):
        counts = [i["count"] for i in facets[key]]
        assert counts == sorted(counts, reverse=True)


def test_search_无过滤返回全部(store) -> None:
    """search(limit=10) 返回前 10 条（共 8 条全量）、count() 全量。"""
    result = store.search(limit=10)
    assert len(result) == 8
    assert len({r["qid"] for r in result}) == 8
    assert store.count() == 8


def test_wal模式生效(tmp_path) -> None:
    """初始化后连接 PRAGMA journal_mode 应为 wal。"""
    db_path = str(tmp_path / "wal.db")
    QuestionBankStore(db_path)
    conn = sqlite3.connect(db_path)
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        conn.close()
    assert mode == "wal"


def test_旧库迁移_补列建索引_幂等(tmp_path) -> None:
    """14 列旧库初始化后补齐 school_id/created_by/created_at 三列并建 school 索引。

    重复初始化不报错；迁移后库可按 17 列插入并正确按可见范围统计。
    """
    db_path = str(tmp_path / "migrate.db")
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE question_bank (
            qid TEXT PRIMARY KEY,
            subject TEXT NOT NULL,
            qtype TEXT NOT NULL,
            grade TEXT NOT NULL,
            year TEXT NOT NULL,
            region TEXT NOT NULL,
            difficulty TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_file TEXT NOT NULL,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            analysis TEXT NOT NULL,
            score INTEGER NOT NULL,
            "index" INTEGER NOT NULL
        )
        """
    )
    conn.close()

    # 首次初始化触发迁移
    QuestionBankStore(db_path)
    # 重复初始化不报错
    QuestionBankStore(db_path)

    conn = sqlite3.connect(db_path)
    try:
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(question_bank)")
        }
        assert {"school_id", "created_by", "created_at"} <= columns
        index_names = {
            row[1] for row in conn.execute("PRAGMA index_list(question_bank)")
        }
        assert "idx_qbank_school" in index_names
    finally:
        conn.close()

    # 迁移后库支持插入租户维度数据并按可见范围统计
    s = QuestionBankStore(db_path)
    s.insert_many([
        _q("g-1", "生物", "解答题", "基础", "subjective", "2020"),
        _q(
            "s-1", "生物", "解答题", "基础", "subjective", "2020",
            school_id="schA", created_by="u-1", created_at="t",
        ),
    ])
    assert s.count() == 1  # 全局范围仅全局种子题
    assert s.count(visible_school_id="schA") == 2
    assert s.get("s-1")["created_at"] == "t"


def test_insert_many_astuple17字段与SQL一致(tmp_path) -> None:
    """astuple 的 17 字段顺序与 _INSERT_SQL 列一致，插入后按可见范围正确往返。"""
    s = QuestionBankStore(str(tmp_path / "astuple.db"))
    global_q = _q("g-1", "生物", "解答题", "基础", "subjective", "2020")
    school_q = _q(
        "schA-1", "数学（理）", "选择题", "进阶", "objective", "2021",
        school_id="schA", created_by="u-1", created_at="2026-08-25",
    )
    assert len(astuple(global_q)) == 17
    assert len(astuple(school_q)) == 17

    # 列名顺序（去引号后）与 dataclass 字段顺序一致
    cols = re.search(r"\((.*?)\)", QuestionBankStore._INSERT_SQL, re.S).group(1)
    sql_columns = [c.strip().strip('"') for c in cols.split(",")]
    assert sql_columns == [f.name for f in fields(BankQuestion)]
    # 占位符数量与字段数一致
    assert QuestionBankStore._INSERT_SQL.count("?") == 17

    assert s.insert_many([global_q, school_q]) == 2
    row = s.get("schA-1")
    assert row["school_id"] == "schA"
    assert row["created_by"] == "u-1"
    assert row["created_at"] == "2026-08-25"
    assert row["source_type"] == "objective"
    assert row["index"] == 0
    # 全局范围仅全局题；给定校为全局+本校
    assert s.count() == 1
    assert {r["qid"] for r in s.search(limit=50)} == {"g-1"}
    assert s.count(visible_school_id="schA") == 2
    assert {r["qid"] for r in s.search(visible_school_id="schA", limit=50)} == {
        "g-1", "schA-1",
    }


def test_count_search_visible_school_id三态(tmp_path) -> None:
    """count/search 的可见范围：None 仅全局，给定校=全局+本校，他校=全局+他校。"""
    s = QuestionBankStore(str(tmp_path / "scope.db"))
    s.insert_many(_base_rows())  # 8 条全局种子题
    s.insert_many([
        _q(
            "schA-1", "生物", "解答题", "进阶", "subjective", "2021",
            school_id="schA", created_by="u-1", created_at="t",
        ),
        _q(
            "schB-1", "数学（理）", "选择题", "基础", "objective", "2022",
            school_id="schB", created_by="u-2", created_at="t",
        ),
    ])

    assert s.count() == 8  # None：仅全局
    assert s.count(visible_school_id="schA") == 9  # 全局 + A 校
    assert s.count(visible_school_id="schB") == 9  # 全局 + B 校

    assert s.count(subject="生物") == 2  # 全局生物 2 条
    assert s.count(subject="生物", visible_school_id="schA") == 3  # 含 A 校生物

    qids_a = {r["qid"] for r in s.search(visible_school_id="schA", limit=50)}
    assert "schA-1" in qids_a
    assert "schB-1" not in qids_a
    qids_b = {r["qid"] for r in s.search(visible_school_id="schB", limit=50)}
    assert "schB-1" in qids_b
    assert "schA-1" not in qids_b
    # 全局范围不返回任何校题
    assert "schA-1" not in {r["qid"] for r in s.search(limit=50)}


def test_facets_visible_school_id三态(tmp_path) -> None:
    """facets 的可见范围：None 仅全局，给定校含全局+本校计数。"""
    s = QuestionBankStore(str(tmp_path / "facets_scope.db"))
    s.insert_many(_base_rows())  # 8 条全局种子题
    s.insert_many([
        _q(
            "schA-1", "生物", "解答题", "进阶", "subjective", "2021",
            school_id="schA", created_by="u-1", created_at="t",
        ),
    ])

    global_subjects = {i["value"]: i["count"] for i in s.facets()["subjects"]}
    assert global_subjects["生物"] == 2  # 全局不含校题

    scha_subjects = {
        i["value"]: i["count"]
        for i in s.facets(visible_school_id="schA")["subjects"]
    }
    assert scha_subjects["生物"] == 3  # 全局 + 本校
    scha_difficulties = {
        i["value"]: i["count"]
        for i in s.facets(visible_school_id="schA")["difficulties"]
    }
    assert scha_difficulties["进阶"] == 4  # 全局 3 + 本校 1

    # 他校（schB 无本校题）：计数与全局一致
    schb_subjects = {
        i["value"]: i["count"]
        for i in s.facets(visible_school_id="schB")["subjects"]
    }
    assert schb_subjects["生物"] == 2
