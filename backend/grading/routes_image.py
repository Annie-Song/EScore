"""Flask 路由：单图合并评分（一次请求内 OCR + 评分）。

与 routes.py 拆分的独立 Blueprint（bp_image），避免单文件超过 200 行约束门禁。
"""
import logging

from flask import Blueprint, jsonify, request

from backend.core.cache import BoundedCache, file_sha1, text_sha1
from backend.core.config import (
    DEFAULT_ROUTING_PRESET,
    GRADE_CACHE_MAX,
    OCR_LANG_MAP,
    ROUTING_PRESETS,
)
from backend.core.files import allowed_file, save_upload
from backend.ocr.client import recognize_texts
from backend.scoring.engine import grade_answer

logger = logging.getLogger(__name__)

bp_image = Blueprint('image', __name__)

# 单图评分结果缓存：键 = (image_sha1, reference_sha1, lang, quality, force_online, plan)
_grade_cache = BoundedCache(GRADE_CACHE_MAX)


@bp_image.route('/api/grade_image', methods=['POST'])
def grade_image():
    """单图合并评分：上传单题作业图+参考答案文本，一次请求内 OCR+评分返回。

    为"一道题一张图"优化：把 /ocr + /compare_texts 两次 HTTP 往返合并为一次，
    减少 4-8ms HTTP 开销与文件重复落盘。返回 score/method/degraded/routed 之外
    附带 workContent（识别出的作业文本），供前端展示识别结果。

    双层重复图缓存：内容哈希相同的图片命中单图评分缓存时直接返回先前冷算的
    完全相同结果（跳过 OCR+评分）；未命中评分缓存时，OCR 层另有文本缓存跳过
    PaddleOCR 推理。缓存只是优化，任何缓存错误都不影响主流程正确性。
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

    # 延迟导入避免循环依赖（与 /compare_texts 一致）；current_plan 需在缓存键之前求值
    from backend.auth.session import current_plan

    plan = current_plan()

    image_path = save_upload(file)
    image_sha1 = file_sha1(image_path)
    reference_sha1 = text_sha1(reference)
    cache_key = (image_sha1, reference_sha1, lang, quality, force_online, plan)

    cached = _grade_cache.get(cache_key)
    if cached is not None:
        return jsonify(cached), 200

    try:
        work_content = recognize_texts([image_path], lang=lang)[0]
    except Exception as exc:  # noqa: BLE001 - 与 /ocr 一致，网络/服务错误统一返回 500
        logger.error("单图评分 OCR 处理出错: %s", exc, exc_info=True)
        return jsonify({"message": "文字识别失败，请重试"}), 500

    result = grade_answer(
        reference,
        work_content,
        force_online=force_online,
        quality_mode=quality,
        allow_online=(plan == 'pro'),
    )
    payload = {
        "score": result["score"],
        "method": result["method"],
        "degraded": result["degraded"],
        "routed": result["routed"],
        "workContent": work_content,
    }
    _grade_cache.set(cache_key, payload)
    return jsonify(payload), 200
