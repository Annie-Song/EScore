"""Flask 路由：单图合并评分（一次请求内 OCR + 评分）。

与 routes.py 拆分的独立 Blueprint（bp_image），避免单文件超过 200 行约束门禁。
"""
import logging

from flask import Blueprint, jsonify, request

from backend.core.config import (
    DEFAULT_ROUTING_PRESET,
    OCR_LANG_MAP,
    ROUTING_PRESETS,
)
from backend.core.files import allowed_file, save_upload
from backend.ocr.client import recognize_texts
from backend.scoring.engine import grade_answer

logger = logging.getLogger(__name__)

bp_image = Blueprint('image', __name__)


@bp_image.route('/api/grade_image', methods=['POST'])
def grade_image():
    """单图合并评分：上传单题作业图+参考答案文本，一次请求内 OCR+评分返回。

    为"一道题一张图"优化：把 /ocr + /compare_texts 两次 HTTP 往返合并为一次，
    减少 4-8ms HTTP 开销与文件重复落盘。返回 score/method/degraded/routed 之外
    附带 workContent（识别出的作业文本），供前端展示识别结果。
    """
    if 'file' not in request.files:
        return jsonify({"message": "没有找到文件！"}), 400
    file = request.files['file']
    if not file or not file.filename or not allowed_file(file.filename):
        return jsonify({"message": "不支持的文件类型"}), 400

    reference = request.form.get('reference')
    if not reference:
        return jsonify({"message": "缺少参考答案文本"}), 400

    quality = request.form.get('quality') or DEFAULT_ROUTING_PRESET
    if quality not in ROUTING_PRESETS:
        return jsonify({"message": f"未知评分质量: {quality}"}), 400

    lang = OCR_LANG_MAP.get(request.form.get('language'), 'ch')
    force_online = request.form.get('forceOnline') in ('true', 'True', '1')

    image_path = save_upload(file)
    try:
        work_content = recognize_texts([image_path], lang=lang)[0]
    except Exception as exc:  # noqa: BLE001 - 与 /ocr 一致，网络/服务错误统一返回 500
        logger.error("单图评分 OCR 处理出错: %s", exc, exc_info=True)
        return jsonify({"message": "文字识别失败，请重试"}), 500

    # 延迟导入避免循环依赖（与 /compare_texts 一致）
    from backend.auth.session import current_plan

    result = grade_answer(
        reference,
        work_content,
        force_online=force_online,
        quality_mode=quality,
        allow_online=(current_plan() == 'pro'),
    )
    return jsonify({
        "score": result["score"],
        "method": result["method"],
        "degraded": result["degraded"],
        "routed": result["routed"],
        "workContent": work_content,
    }), 200
