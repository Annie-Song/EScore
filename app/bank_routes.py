"""Flask 路由：分类题库 REST API（F7）。

提供题库 facet 分布、按过滤条件检索与单题详情三个只读接口。
"""
from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from services.question_bank_store import QuestionBankStore

bp = Blueprint('bank', __name__)

# 列表页精简字段：不返回 answer/analysis，保持响应负载小
_LIST_FIELDS = (
    "qid", "subject", "qtype", "grade", "year", "region",
    "difficulty", "source_type", "source_file", "question", "score",
)

_NOT_BUILT_MSG = "题库未构建，请先运行 scripts/build_question_bank.py"


def _build_ready(store: QuestionBankStore) -> bool:
    """判断题库是否已构建：存在数据才视为就绪。"""
    return store.count() > 0


def _list_item(d: dict) -> dict:
    """从存储字典挑选列表页精简字段，剔除 answer/analysis 减小负载。"""
    return {field: d[field] for field in _LIST_FIELDS}


def _parse_int_arg(raw: str | None, default: int) -> int:
    """解析整型查询参数，缺失或非法时回退默认值。"""
    try:
        return int(raw) if raw is not None else default
    except ValueError:
        return default


@bp.route('/api/bank/facets', methods=['GET'])
def bank_facets():
    """返回题库各维度 facet 分布，题库未构建返回 503 明确提示。"""
    store = QuestionBankStore()
    if not _build_ready(store):
        return jsonify({"message": _NOT_BUILT_MSG}), 503
    return jsonify(store.facets()), 200


@bp.route('/api/bank/search', methods=['GET'])
def bank_search():
    """按过滤条件检索题库，支持分页与关键词，返回精简字段列表。"""
    store = QuestionBankStore()
    if not _build_ready(store):
        return jsonify({"message": _NOT_BUILT_MSG}), 503

    args = request.args
    limit = _parse_int_arg(args.get('limit'), 50)
    offset = _parse_int_arg(args.get('offset'), 0)
    kwargs = {
        "subject": args.get('subject'),
        "qtype": args.get('qtype'),
        "difficulty": args.get('difficulty'),
        "source_type": args.get('source_type'),
        "year": args.get('year'),
        "keyword": args.get('q'),
    }
    items = store.search(limit=limit, offset=offset, **kwargs)
    total = store.count(**kwargs)
    return jsonify({
        "total": total,
        "items": [_list_item(item) for item in items],
        "limit": limit,
        "offset": offset,
    }), 200


@bp.route('/api/bank/questions/<qid>', methods=['GET'])
def bank_question(qid: str):
    """按 qid 返回单题完整详情（含 answer/analysis），不存在返回 404。"""
    store = QuestionBankStore()
    if not _build_ready(store):
        return jsonify({"message": _NOT_BUILT_MSG}), 503
    row = store.get(qid)
    if row is None:
        return jsonify({"message": "题目不存在"}), 404
    return jsonify(row), 200


@bp.route('/bank', methods=['GET'])
def bank_page():
    """题库浏览检索页。"""
    return render_template('bank.html'), 200
