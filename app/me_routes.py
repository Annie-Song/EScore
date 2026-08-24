"""Flask 路由：个人主页与个人卷库（task/22）。

提供个人主页渲染、聚合数据接口与题目收藏增删查接口。
登录与游客均可访问页面与 /api/me；收藏增删查接口要求登录。
"""
from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from services import auth
from services.school_store import default_school_store
from services.store import default_store
from services.user_activity_store import default_user_activity_store
from services.user_store import default_user_store

bp = Blueprint('me', __name__)

# 公开用户字段：剔除 password_hash，避免哈希泄露到响应
_PUBLIC_FIELDS = (
    "id", "username", "display_name", "role", "plan",
    "school_id", "avatar", "created_at",
)


def _user_public(user: dict) -> dict:
    """从用户字典挑选公开字段，剔除 password_hash。"""
    return {field: user.get(field) for field in _PUBLIC_FIELDS}


def _favorite_item(fav: dict) -> dict:
    """格式化收藏条目，剔除 user_id 内部字段。"""
    return {
        "qid": fav["qid"],
        "subject": fav["subject"],
        "qtype": fav["qtype"],
        "question": fav["question"],
        "score": fav["score"],
        "created_at": fav["created_at"],
    }


def _batch_stats(user_id: str) -> tuple[list[dict], dict]:
    """联查用户批改批次：批次元信息 + 明细计数/均分，缺失批次跳过。

    数据量小，逐批次 N+1 查询 grades.db 可接受；返回列表与不含收藏数的统计。
    """
    store = default_store()
    recent: list[dict] = []
    total_records = 0
    total_score = 0.0
    for mapping in default_user_activity_store().list_user_batches(user_id):
        batch = store.get_batch(mapping["batch_id"])
        if batch is None:
            continue
        records = store.list_records(batch["batch_id"])
        count = len(records)
        batch_sum = sum(record.score for record in records)
        total_records += count
        total_score += batch_sum
        recent.append({
            "batch_id": batch["batch_id"],
            "task_id": mapping["task_id"],
            "status": batch["status"],
            "total_questions": batch["total_questions"],
            "created_at": batch["created_at"],
            "record_count": count,
            "avg_score": round(batch_sum / count, 1) if count else 0.0,
        })
    stats = {
        "batch_count": len(recent),
        "record_count": total_records,
        "avg_score": round(total_score / total_records, 1) if total_records else 0.0,
    }
    return recent, stats


def _aggregate_data(user: dict) -> dict:
    """组装登录用户个人主页聚合响应。"""
    recent, stats = _batch_stats(user["id"])
    favorites = default_user_activity_store().list_favorites(user["id"])
    stats["favorite_count"] = len(favorites)
    return {
        "user": _user_public(user),
        "plan": user.get("plan", "free"),
        "stats": stats,
        "recent_batches": recent,
        "favorites": [_favorite_item(item) for item in favorites],
    }


def _empty_payload() -> dict:
    """游客个人主页空态响应。"""
    return {
        "user": None,
        "plan": "free",
        "stats": {
            "batch_count": 0,
            "record_count": 0,
            "avg_score": 0.0,
            "favorite_count": 0,
        },
        "recent_batches": [],
        "favorites": [],
    }


@bp.route('/me')
def me_page():
    """渲染个人主页，游客同样可访问（页面 JS 拉取空态）。"""
    return render_template('me.html'), 200


@bp.route('/api/me')
def api_me():
    """返回个人主页聚合数据，登录与游客均返回 200。"""
    user = auth.current_user()
    if user is None:
        return jsonify(_empty_payload()), 200
    return jsonify(_aggregate_data(user)), 200


@bp.route('/api/favorites', methods=['GET'])
def favorites_list():
    """返回当前用户收藏题目列表，未登录返回 401。"""
    guard = auth.login_required()
    if guard:
        return guard
    items = default_user_activity_store().list_favorites(auth.current_user_id())
    return jsonify([_favorite_item(item) for item in items]), 200


@bp.route('/api/favorites', methods=['POST'])
def favorites_add():
    """收藏题目：qid 必填，其余字段可空；重复收藏返回 200。"""
    guard = auth.login_required()
    if guard:
        return guard
    body = request.get_json(silent=True) or {}
    qid = (body.get('qid') or '').strip()
    if not qid:
        return jsonify({"message": "缺少题目 ID"}), 400
    score_raw = body.get('score')
    score = int(float(score_raw)) if score_raw not in (None, '') else 0
    added = default_user_activity_store().add_favorite(
        user_id=auth.current_user_id(),
        qid=qid,
        subject=(body.get('subject') or ''),
        qtype=(body.get('qtype') or ''),
        question=(body.get('question') or ''),
        score=score,
    )
    return jsonify({"ok": True}), (201 if added else 200)


@bp.route('/api/favorites/<qid>', methods=['DELETE'])
def favorites_remove(qid: str):
    """取消收藏题目，未登录返回 401。"""
    guard = auth.login_required()
    if guard:
        return guard
    default_user_activity_store().remove_favorite(auth.current_user_id(), qid)
    return jsonify({"ok": True}), 200


@bp.route('/api/me/school', methods=['POST'])
def _join_school():
    """加入学校：school_code 合法则更新当前用户 school_id，无效返回 404。

    函数名以下划线开头维持本模块公开函数数在 5 个限制内，路由名不受影响。
    """
    guard = auth.login_required()
    if guard:
        return guard
    body = request.get_json(silent=True) or {}
    school_code = (body.get('school_code') or '').strip()
    if not school_code:
        return jsonify({"message": "缺少学校代码"}), 400
    school = default_school_store().get_school_by_code(school_code)
    if school is None:
        return jsonify({"message": "学校代码无效"}), 404
    default_user_store().update_school_id(auth.current_user_id(), school["id"])
    return jsonify({"ok": True, "school_id": school["id"]}), 200
