"""校本题库增删接口（app/bank_manage_routes.py）单元测试。

用真实 QuestionBankStore/SchoolQuestionStore + tmp_path 临时库走全栈，
monkeypatch 使路由实例化的 QuestionBankStore()/SchoolQuestionStore() 指向
临时库；登录态经 session 写入 user_id（login_required 读会话），当前用户经
backend.auth.session.current_user 模块级函数名 patch（auth.py docstring 约定）。
完全离线运行，不触碰真实 output/question_bank.db、不访问外网。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.app import create_app
from backend.bank.model import BankQuestion
from backend.bank.store import QuestionBankStore
from backend.bank.school_store import SchoolQuestionStore
from backend.core import config

_GRADE = config.QUESTION_BANK_GRADE


def _global_q(qid: str) -> BankQuestion:
    """构造一条全局种子题（school_id NULL）。"""
    return BankQuestion(
        qid=qid, subject="语文", qtype="古诗文阅读", grade=_GRADE, year="2020",
        region="全国", difficulty="基础", source_type="subjective",
        source_file="source.json", question=f"全局题 {qid}", answer="A",
        analysis="解析", score=5, index=0,
    )


def _fields(**overrides: str | int) -> dict:
    """构造校本题提交字段，默认全合法。"""
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


def _patch_db(monkeypatch: pytest.MonkeyPatch, db_path: str) -> None:
    """monkeypatch 使路由的 QuestionBankStore()/SchoolQuestionStore() 打开临时库。"""
    monkeypatch.setattr(config, "QUESTION_BANK_DB_PATH", db_path)
    monkeypatch.setattr(QuestionBankStore.__init__, "__defaults__", (db_path,))


def _login(client, user_id: str) -> None:
    """写入会话 user_id 模拟登录态（login_required 读会话）。"""
    with client.session_transaction() as sess:
        sess["user_id"] = user_id


def _patch_user(
    monkeypatch: pytest.MonkeyPatch, user_id: str, school_id: str | None,
    role: str,
) -> None:
    """patch backend.auth.session.current_user 返回指定用户 dict。"""
    monkeypatch.setattr(
        "backend.auth.session.current_user",
        lambda: {"id": user_id, "school_id": school_id, "role": role},
    )


@pytest.fixture()
def ctx(monkeypatch, tmp_path) -> SimpleNamespace:
    """隔离存储的测试上下文：2 条全局题 + schA/schB 各 1 条校题。"""
    db_path = str(tmp_path / "manage.db")
    store = SchoolQuestionStore(db_path)
    store.insert_many([_global_q("global-1"), _global_q("global-2")])
    sch_a = store.create(
        _fields(question="A 校题题干"), school_id="schA", created_by="u-owner"
    )
    sch_b = store.create(
        _fields(question="B 校题题干", subject="生物", qtype="选择题"),
        school_id="schB", created_by="u-bowner",
    )
    _patch_db(monkeypatch, db_path)
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield SimpleNamespace(
            client=c,
            db_path=db_path,
            q_sch_a=sch_a["qid"],
            q_sch_b=sch_b["qid"],
            q_global="global-1",
        )


# ---------------- POST /api/bank/questions ----------------


def test_post_未登录401(ctx: SimpleNamespace) -> None:
    """游客 POST /api/bank/questions：401。"""
    resp = ctx.client.post("/api/bank/questions", json=_fields())
    assert resp.status_code == 401
    assert resp.get_json() == {"message": "请先登录"}


def test_post_未入校400(ctx: SimpleNamespace, monkeypatch) -> None:
    """登录但 school_id 为空：400 提示先加入学校。"""
    _login(ctx.client, "u-noschool")
    _patch_user(monkeypatch, "u-noschool", None, "teacher")
    resp = ctx.client.post("/api/bank/questions", json=_fields())
    assert resp.status_code == 400
    assert "加入学校" in resp.get_json()["message"]


@pytest.mark.parametrize("missing", ["subject", "qtype", "question", "answer"])
def test_post_缺必填字段400(
    ctx: SimpleNamespace, monkeypatch, missing: str
) -> None:
    """缺 subject/qtype/question/answer 任一：400 且提示字段名。"""
    _login(ctx.client, "u-owner")
    _patch_user(monkeypatch, "u-owner", "schA", "teacher")
    body = _fields()
    body.pop(missing)
    resp = ctx.client.post("/api/bank/questions", json=body)
    assert resp.status_code == 400, missing
    assert resp.get_json()["message"] == f"{missing} 不能为空"


def test_post_score非整数400(ctx: SimpleNamespace, monkeypatch) -> None:
    """score 不是整数：400。"""
    _login(ctx.client, "u-owner")
    _patch_user(monkeypatch, "u-owner", "schA", "teacher")
    resp = ctx.client.post(
        "/api/bank/questions", json=_fields(score="abc")
    )
    assert resp.status_code == 400
    assert resp.get_json()["message"] == "score 必须为不小于 0 的整数"


def test_post_score负数400(ctx: SimpleNamespace, monkeypatch) -> None:
    """score 为负数：400。"""
    _login(ctx.client, "u-owner")
    _patch_user(monkeypatch, "u-owner", "schA", "teacher")
    resp = ctx.client.post("/api/bank/questions", json=_fields(score=-1))
    assert resp.status_code == 400
    assert resp.get_json()["message"] == "score 必须为不小于 0 的整数"


def test_post_score缺失400(ctx: SimpleNamespace, monkeypatch) -> None:
    """缺 score：400。"""
    _login(ctx.client, "u-owner")
    _patch_user(monkeypatch, "u-owner", "schA", "teacher")
    body = _fields()
    body.pop("score")
    resp = ctx.client.post("/api/bank/questions", json=body)
    assert resp.status_code == 400
    assert resp.get_json()["message"] == "score 必须为不小于 0 的整数"


def test_post_difficulty非法400(ctx: SimpleNamespace, monkeypatch) -> None:
    """difficulty 不在 {基础, 进阶}：400。"""
    _login(ctx.client, "u-owner")
    _patch_user(monkeypatch, "u-owner", "schA", "teacher")
    resp = ctx.client.post(
        "/api/bank/questions", json=_fields(difficulty="地狱")
    )
    assert resp.status_code == 400
    assert resp.get_json()["message"] == "difficulty 必须为基础或进阶"


def test_post_合法201且落库(ctx: SimpleNamespace, monkeypatch) -> None:
    """合法提交：201 返回含 school_id/created_by 的 dict，且可被该校检索到。"""
    _login(ctx.client, "u-owner")
    _patch_user(monkeypatch, "u-owner", "schA", "teacher")
    resp = ctx.client.post("/api/bank/questions", json=_fields(question="新校题题干"))
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["qid"].startswith("sch_")
    assert body["school_id"] == "schA"
    assert body["created_by"] == "u-owner"
    assert body["source_type"] == "school"
    assert body["created_at"]
    assert body["question"] == "新校题题干"
    assert body["score"] == 10

    store = QuestionBankStore(ctx.db_path)
    qids_sch_a = {r["qid"] for r in store.search(visible_school_id="schA")}
    assert {ctx.q_sch_a, body["qid"]} <= qids_sch_a
    assert "global-1" in qids_sch_a  # 全局题仍可见
    assert body["qid"] not in {r["qid"] for r in store.search()}  # 全局范围不含校题


# ---------------- DELETE /api/bank/questions/<qid> ----------------


def test_delete_未登录401(ctx: SimpleNamespace) -> None:
    """游客 DELETE：401。"""
    resp = ctx.client.delete(f"/api/bank/questions/{ctx.q_sch_a}")
    assert resp.status_code == 401
    assert resp.get_json() == {"message": "请先登录"}


def test_delete_不存在404(ctx: SimpleNamespace, monkeypatch) -> None:
    """qid 不存在：404。"""
    _login(ctx.client, "u-owner")
    _patch_user(monkeypatch, "u-owner", "schA", "teacher")
    resp = ctx.client.delete("/api/bank/questions/no_such_qid")
    assert resp.status_code == 404
    assert resp.get_json() == {"message": "题目不存在"}


def test_delete_全局题403(ctx: SimpleNamespace, monkeypatch) -> None:
    """删除全局题（school_id NULL）：403。"""
    _login(ctx.client, "u-owner")
    _patch_user(monkeypatch, "u-owner", "schA", "teacher")
    resp = ctx.client.delete(f"/api/bank/questions/{ctx.q_global}")
    assert resp.status_code == 403
    assert resp.get_json() == {"message": "全局题库不可删除"}


def test_delete_外校题普通教师403(ctx: SimpleNamespace, monkeypatch) -> None:
    """普通教师删他校题（非题主非本校 school_admin）：403。"""
    _login(ctx.client, "u-teacher")
    _patch_user(monkeypatch, "u-teacher", "schB", "teacher")
    resp = ctx.client.delete(f"/api/bank/questions/{ctx.q_sch_a}")
    assert resp.status_code == 403
    assert resp.get_json() == {"message": "无权限删除该题目"}


def test_delete_题主本人200(ctx: SimpleNamespace, monkeypatch) -> None:
    """题主本人删自己的题：200 且库中已无。"""
    _login(ctx.client, "u-owner")
    _patch_user(monkeypatch, "u-owner", "schA", "teacher")
    resp = ctx.client.delete(f"/api/bank/questions/{ctx.q_sch_a}")
    assert resp.status_code == 200
    assert resp.get_json() == {"message": "已删除"}
    assert QuestionBankStore(ctx.db_path).get(ctx.q_sch_a) is None


def test_delete_本校school_admin200(ctx: SimpleNamespace, monkeypatch) -> None:
    """本校 school_admin 删他人建的题：200。"""
    _login(ctx.client, "u-adminA")
    _patch_user(monkeypatch, "u-adminA", "schA", "school_admin")
    resp = ctx.client.delete(f"/api/bank/questions/{ctx.q_sch_a}")
    assert resp.status_code == 200
    assert QuestionBankStore(ctx.db_path).get(ctx.q_sch_a) is None


def test_delete_全局admin200(ctx: SimpleNamespace, monkeypatch) -> None:
    """全局 admin 删任意校题：200。"""
    _login(ctx.client, "u-root")
    _patch_user(monkeypatch, "u-root", None, "admin")
    resp = ctx.client.delete(f"/api/bank/questions/{ctx.q_sch_b}")
    assert resp.status_code == 200
    assert QuestionBankStore(ctx.db_path).get(ctx.q_sch_b) is None


def test_delete_跨校school_admin403(ctx: SimpleNamespace, monkeypatch) -> None:
    """B 校 school_admin 删 A 校题：403。"""
    _login(ctx.client, "u-adminB")
    _patch_user(monkeypatch, "u-adminB", "schB", "school_admin")
    resp = ctx.client.delete(f"/api/bank/questions/{ctx.q_sch_a}")
    assert resp.status_code == 403
    assert resp.get_json() == {"message": "无权限删除该题目"}
