"""Flask 路由：校本题库增删接口（F10）。

提供本校教师添加校本题、按权限删除题目的写接口；删除权限覆盖
题主本人、本校 school_admin、全局 admin。
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from services import auth
from services.question_bank_store import QuestionBankStore
from services.school_question_store import SchoolQuestionStore

bp = Blueprint('bank_manage', __name__)

_REQUIRED_FIELDS = ("subject", "qtype", "question", "answer")
_ALLOWED_DIFFICULTY = {"基础", "进阶"}


def _validate_fields(body: dict) -> tuple[dict | None, str | None]:
    """校验校本题提交字段，返回 (fields, error)；error 为空表示通过。"""
    for field in _REQUIRED_FIELDS:
        if not str(body.get(field, "")).strip():
            return None, f"{field} 不能为空"
    try:
        score = int(body.get("score"))
    except (TypeError, ValueError):
        return None, "score 必须为不小于 0 的整数"
    if score < 0:
        return None, "score 必须为不小于 0 的整数"
    difficulty = body.get("difficulty")
    if difficulty not in _ALLOWED_DIFFICULTY:
        return None, "difficulty 必须为基础或进阶"
    fields = {
        "subject": str(body["subject"]).strip(),
        "qtype": str(body["qtype"]).strip(),
        "grade": str(body.get("grade", "")).strip(),
        "year": str(body.get("year", "")).strip(),
        "region": str(body.get("region", "")).strip(),
        "difficulty": difficulty,
        "question": str(body["question"]).strip(),
        "answer": str(body["answer"]).strip(),
        "analysis": str(body.get("analysis", "")).strip(),
        "score": score,
    }
    return fields, None


@bp.route('/api/bank/questions', methods=['POST'])
def bank_manage_create():
    """添加校本题：仅限已入校教师，成功返回 201 与新建题目。"""
    guard = auth.login_required()
    if guard:
        return guard
    user = auth.current_user()
    if user is None or not user.get("school_id"):
        return jsonify({"message": "请先加入学校后才能添加校本题"}), 400
    body = request.get_json(silent=True) or {}
    fields, error = _validate_fields(body)
    if error:
        return jsonify({"message": error}), 400
    question = SchoolQuestionStore().create(
        fields, school_id=user["school_id"], created_by=user["id"]
    )
    return jsonify(question), 201


@bp.route('/api/bank/questions/<qid>', methods=['DELETE'])
def bank_manage_delete(qid: str):
    """删除题目：限题主本人、本校 school_admin、全局 admin。"""
    guard = auth.login_required()
    if guard:
        return guard
    user = auth.current_user()
    row = QuestionBankStore().get(qid)
    if row is None:
        return jsonify({"message": "题目不存在"}), 404
    if row.get("school_id") is None:
        return jsonify({"message": "全局题库不可删除"}), 403
    role = user["role"] if user else ""
    if role == "admin":
        allowed = True
    elif role == "school_admin" and user.get("school_id") == row["school_id"]:
        allowed = True
    elif row.get("created_by") == (user["id"] if user else None):
        allowed = True
    else:
        allowed = False
    if not allowed:
        return jsonify({"message": "无权限删除该题目"}), 403
    SchoolQuestionStore().delete(qid)
    return jsonify({"message": "已删除"}), 200
