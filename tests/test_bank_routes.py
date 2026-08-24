"""题库 REST API（app/bank_routes.py）Flask 路由单元测试。

不 mock 路由：用真实 QuestionBankStore + tmp_path 临时库走全栈，
monkeypatch 使路由实例化的 QuestionBankStore() 指向临时库；
完全离线运行，不触碰真实 output/question_bank.db、不访问外网。
"""
from __future__ import annotations

import pytest

from app import create_app
from services.question_bank import BankQuestion
from services.question_bank_store import QuestionBankStore
from utils import config

_GRADE = config.QUESTION_BANK_GRADE

# 列表页精简字段（与路由 _LIST_FIELDS 一致，不含 answer/analysis）
_LIST_FIELDS = {
    "qid", "subject", "qtype", "grade", "year", "region",
    "difficulty", "source_type", "source_file", "question", "score",
    "school_id", "created_by",
}
# 详情页完整字段（含 answer/analysis/index/created_at 等全部 17 列）
_FULL_FIELDS = _LIST_FIELDS | {"answer", "analysis", "index", "created_at"}


def _q(
    qid: str,
    subject: str,
    qtype: str,
    difficulty: str,
    source_type: str,
    year: str,
    question: str,
    answer: str,
    analysis: str,
    *,
    score: int = 5,
    index: int = 0,
    region: str = "全国",
    school_id: str | None = None,
    created_by: str | None = None,
    created_at: str | None = None,
) -> BankQuestion:
    """构造测试用 BankQuestion，未显式指定的字段用默认值。"""
    return BankQuestion(
        qid=qid, subject=subject, qtype=qtype, grade=_GRADE, year=year,
        region=region, difficulty=difficulty, source_type=source_type,
        source_file="source.json", question=question, answer=answer,
        analysis=analysis, score=score, index=index,
        school_id=school_id, created_by=created_by, created_at=created_at,
    )


def _seed_rows() -> list[BankQuestion]:
    """返回覆盖多维度（科目/题型/难度/source_type/年份）的题库（6 条）。"""
    return [
        _q("chi-1", "语文", "古诗文阅读", "基础", "subjective", "2020",
           question="床前明月光，疑是地上霜。",
           answer="思乡之情", analysis="借月光表达思乡。"),
        _q("chi-2", "语文", "古诗文阅读", "中等", "subjective", "2019",
           question="长风破浪会有时，直挂云帆济沧海。",
           answer="豪情壮志", analysis="体现乐观豁达。", index=1),
        _q("math-1", "数学（理）", "解答题", "进阶", "subjective", "2021",
           question="求函数 f(x)=x^2 的导数，请写出求导过程。",
           answer="f'(x)=2x，求导结果 derivative",
           analysis="按求导法则逐步计算。", score=8),
        _q("bio-1", "生物", "选择题", "基础", "objective", "2022",
           question="Mitochondria 是细胞的能量工厂，下列叙述正确的是？",
           answer="A", analysis="线粒体通过有氧呼吸供能。"),
        _q("bio-2", "生物", "选择题", "进阶", "objective", "2020",
           question="孟德尔遗传定律适用于下列哪类生物？",
           answer="B", analysis="分离定律与自由组合定律。", index=1),
        _q("eng-1", "英语", "选择题", "中等", "objective", "2018",
           question="The mitochondria produce energy for the cell.",
           answer="D", analysis="mitochondria 供能。"),
    ]


def _patch_db(monkeypatch: pytest.MonkeyPatch, db_path: str) -> None:
    """monkeypatch 使路由的 QuestionBankStore() 打开 db_path 临时库。

    __init__ 的 db_path 默认值在模块 import 时已捕获，仅改
    config.QUESTION_BANK_DB_PATH 不会生效，需同时重绑 __defaults__。
    """
    monkeypatch.setattr(config, "QUESTION_BANK_DB_PATH", db_path)
    monkeypatch.setattr(QuestionBankStore.__init__, "__defaults__", (db_path,))


@pytest.fixture()
def bank_client(monkeypatch, tmp_path):
    """非空库客户端：临时库插入 6 条题后返回 Flask 测试客户端。"""
    db_path = str(tmp_path / "qb.db")
    store = QuestionBankStore(db_path)
    store.insert_many(_seed_rows())
    _patch_db(monkeypatch, db_path)
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture()
def empty_bank_client(monkeypatch, tmp_path):
    """空库客户端：临时库已建表但未插任何题，用于验证 503。"""
    db_path = str(tmp_path / "empty.db")
    QuestionBankStore(db_path)
    _patch_db(monkeypatch, db_path)
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture()
def school_bank_client(monkeypatch, tmp_path):
    """带校题客户端：6 条全局种子题 + schA/schB 各 1 条校题。"""
    db_path = str(tmp_path / "school_qb.db")
    store = QuestionBankStore(db_path)
    store.insert_many(_seed_rows())
    store.insert_many([
        _q(
            "schA-1", "生物", "选择题", "进阶", "objective", "2023",
            question="校题A题干 Mitochondria",
            answer="A", analysis="校题A解析",
            school_id="schA", created_by="u-teacherA", created_at="t",
        ),
        _q(
            "schB-1", "数学（理）", "解答题", "基础", "subjective", "2024",
            question="校题B题干",
            answer="B", analysis="校题B解析",
            school_id="schB", created_by="u-teacherB", created_at="t",
        ),
    ])
    _patch_db(monkeypatch, db_path)
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_facets_结构与计数(bank_client) -> None:
    """facets 200，四维度 key 齐全，subjects 的 value/count 与插入一致且 count 降序。"""
    resp = bank_client.get("/api/bank/facets")
    assert resp.status_code == 200
    body = resp.get_json()
    assert set(body.keys()) == {"subjects", "qtypes", "difficulties", "source_types"}
    assert {(i["value"], i["count"]) for i in body["subjects"]} == {
        ("语文", 2), ("数学（理）", 1), ("生物", 2), ("英语", 1),
    }
    assert {(i["value"], i["count"]) for i in body["qtypes"]} == {
        ("古诗文阅读", 2), ("解答题", 1), ("选择题", 3),
    }
    assert {(i["value"], i["count"]) for i in body["difficulties"]} == {
        ("基础", 2), ("进阶", 2), ("中等", 2),
    }
    assert {(i["value"], i["count"]) for i in body["source_types"]} == {
        ("subjective", 3), ("objective", 3),
    }
    counts = [i["count"] for i in body["subjects"]]
    assert counts == sorted(counts, reverse=True)


def test_search_单字段过滤(bank_client) -> None:
    """subject/qtype/difficulty/source_type/year 各自过滤 total 正确。"""
    for key, value, expected in (
        ("subject", "语文", 2),
        ("qtype", "选择题", 3),
        ("difficulty", "基础", 2),
        ("source_type", "objective", 3),
        ("year", "2020", 2),
    ):
        body = bank_client.get(
            "/api/bank/search", query_string={key: value}
        ).get_json()
        assert body["total"] == expected, f"{key}={value}"
        assert len(body["items"]) == expected


def test_search_多条件组合(bank_client) -> None:
    """subject+difficulty+source_type 组合过滤 total 正确，无命中为 0。"""
    body = bank_client.get(
        "/api/bank/search",
        query_string={
            "subject": "语文", "difficulty": "基础", "source_type": "subjective",
        },
    ).get_json()
    assert body["total"] == 1
    assert body["items"][0]["qid"] == "chi-1"
    body = bank_client.get(
        "/api/bank/search",
        query_string={
            "subject": "数学（理）", "difficulty": "基础", "source_type": "objective",
        },
    ).get_json()
    assert body["total"] == 0
    assert body["items"] == []


def test_search_关键词命中题干或答案(bank_client) -> None:
    """q 命中题干、命中答案各验证；英文大小写不敏感；无命中 total=0 且 items 空。"""
    body = bank_client.get("/api/bank/search", query_string={"q": "床前明月"}).get_json()
    assert [i["qid"] for i in body["items"]] == ["chi-1"]  # 命中题干
    body = bank_client.get("/api/bank/search", query_string={"q": "derivative"}).get_json()
    assert [i["qid"] for i in body["items"]] == ["math-1"]  # 命中答案
    body = bank_client.get("/api/bank/search", query_string={"q": "mitochondria"}).get_json()
    assert {i["qid"] for i in body["items"]} == {"bio-1", "eng-1"}  # 小写命中大写
    body = bank_client.get("/api/bank/search", query_string={"q": "完全不存在xyz"}).get_json()
    assert body["total"] == 0
    assert body["items"] == []


def test_search_分页与limit默认(bank_client) -> None:
    """limit=2 返回 2 条 total 全量；offset 正确；limit=abc 回退默认 50；limit=0 不 500。"""
    page1 = bank_client.get("/api/bank/search", query_string={"limit": 2}).get_json()
    assert page1["total"] == 6
    assert len(page1["items"]) == 2
    page2 = bank_client.get(
        "/api/bank/search", query_string={"limit": 2, "offset": 2}
    ).get_json()
    assert len(page2["items"]) == 2
    assert not {i["qid"] for i in page1["items"]} & {i["qid"] for i in page2["items"]}
    page3 = bank_client.get(
        "/api/bank/search", query_string={"limit": 2, "offset": 4}
    ).get_json()
    got = [i["qid"] for i in page1["items"] + page2["items"] + page3["items"]]
    assert set(got) == {q.qid for q in _seed_rows()}
    body = bank_client.get("/api/bank/search", query_string={"limit": "abc"}).get_json()
    assert body["limit"] == 50  # 非法 int 回退默认
    assert body["total"] == 6
    resp = bank_client.get("/api/bank/search", query_string={"limit": 0})
    assert resp.status_code == 200
    assert resp.get_json()["total"] == 6  # 总条数不受分页钳制影响


def test_search_精简字段_无answer(bank_client) -> None:
    """items[0] 恰含 11 个精简字段，不含 answer/analysis/index。"""
    body = bank_client.get("/api/bank/search").get_json()
    assert set(body["items"][0].keys()) == _LIST_FIELDS
    assert "answer" not in body["items"][0]
    assert "analysis" not in body["items"][0]


def test_详情_完整字段(bank_client) -> None:
    """qid 存在返回含 answer/analysis 的完整字段；不存在返回 404。"""
    resp = bank_client.get("/api/bank/questions/chi-1")
    assert resp.status_code == 200
    detail = resp.get_json()
    assert set(detail.keys()) == _FULL_FIELDS
    assert detail["answer"] == "思乡之情"
    assert "思乡" in detail["analysis"]
    resp = bank_client.get("/api/bank/questions/no-such")
    assert resp.status_code == 404
    assert resp.get_json() == {"message": "题目不存在"}


def test_空库_503(empty_bank_client) -> None:
    """空库下 facets/search/questions 三端点均 503 且提示题库未构建。"""
    for url in ("/api/bank/facets", "/api/bank/search", "/api/bank/questions/x"):
        resp = empty_bank_client.get(url)
        assert resp.status_code == 503, url
        assert "题库未构建" in resp.get_json()["message"]


def test_蓝图已注册(bank_client) -> None:
    """非空库下 /api/bank/facets 返回 200 而非 404，证明 blueprint 已挂载。"""
    assert bank_client.get("/api/bank/facets").status_code == 200


def test_搜索全量默认(bank_client) -> None:
    """无任何参数 search 返回 total==插入总数、limit==50。"""
    body = bank_client.get("/api/bank/search").get_json()
    assert body["total"] == 6
    assert body["limit"] == 50
    assert body["offset"] == 0


def test_无auth仅全局可见(school_bank_client) -> None:
    """未登录（current_user 返回 None）时 search/facets 只返回全局题，校题不可见。"""
    body = school_bank_client.get(
        "/api/bank/search", query_string={"limit": 50}
    ).get_json()
    assert body["total"] == 6
    assert "schA-1" not in {i["qid"] for i in body["items"]}
    assert "schB-1" not in {i["qid"] for i in body["items"]}
    subjects = {i["value"] for i in school_bank_client.get(
        "/api/bank/facets").get_json()["subjects"]}
    assert subjects == {"语文", "数学（理）", "生物", "英语"}


def test_search_本校可见全局加本校(school_bank_client, monkeypatch) -> None:
    """patch current_user 返回 schA 用户后，search 返回全局+本校，排除他校题。"""
    monkeypatch.setattr(
        "services.auth.current_user",
        lambda: {"id": "u-teacherA", "school_id": "schA",
                 "role": "teacher", "plan": "free"},
    )
    body = school_bank_client.get(
        "/api/bank/search", query_string={"limit": 50}
    ).get_json()
    qids = {i["qid"] for i in body["items"]}
    assert "schA-1" in qids
    assert "schB-1" not in qids
    assert body["total"] == 7  # 6 全局 + 本校 1


def test_search_他校不可见(school_bank_client, monkeypatch) -> None:
    """patch current_user 返回 schB 用户后，search 排除 schA 校题。"""
    monkeypatch.setattr(
        "services.auth.current_user",
        lambda: {"id": "u-teacherB", "school_id": "schB",
                 "role": "teacher", "plan": "free"},
    )
    body = school_bank_client.get(
        "/api/bank/search", query_string={"limit": 50}
    ).get_json()
    qids = {i["qid"] for i in body["items"]}
    assert "schB-1" in qids
    assert "schA-1" not in qids
    assert body["total"] == 7


def test_facets_本校包含本校计数(school_bank_client, monkeypatch) -> None:
    """patch current_user 返回 schA 用户后，facets 科目计数含本校校题。"""
    monkeypatch.setattr(
        "services.auth.current_user",
        lambda: {"id": "u-teacherA", "school_id": "schA",
                 "role": "teacher", "plan": "free"},
    )
    subjects = {i["value"]: i["count"] for i in school_bank_client.get(
        "/api/bank/facets").get_json()["subjects"]}
    assert subjects["生物"] == 3  # 全局 2 + 本校 schA-1


def test_详情_本校校题200_跨校404(school_bank_client, monkeypatch) -> None:
    """本校校题详情 200；他校用户访问该题 404；全局题任意用户均 200。"""
    monkeypatch.setattr(
        "services.auth.current_user",
        lambda: {"id": "u-teacherA", "school_id": "schA",
                 "role": "teacher", "plan": "free"},
    )
    assert school_bank_client.get("/api/bank/questions/schA-1").status_code == 200
    # 全局题（school_id NULL）对任意登录用户可见
    assert school_bank_client.get("/api/bank/questions/chi-1").status_code == 200

    # 他校用户访问 schA 校题 → 404
    monkeypatch.setattr(
        "services.auth.current_user",
        lambda: {"id": "u-teacherB", "school_id": "schB",
                 "role": "teacher", "plan": "free"},
    )
    resp = school_bank_client.get("/api/bank/questions/schA-1")
    assert resp.status_code == 404
    assert resp.get_json() == {"message": "题目不存在"}
    # 本校用户访问自己的校题 → 200
    assert school_bank_client.get("/api/bank/questions/schB-1").status_code == 200


def test_详情_游客访问校题404(school_bank_client) -> None:
    """游客（current_user 返回 None）访问校题详情应 404。"""
    resp = school_bank_client.get("/api/bank/questions/schA-1")
    assert resp.status_code == 404
    assert resp.get_json() == {"message": "题目不存在"}
