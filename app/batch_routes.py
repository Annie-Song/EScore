"""Flask 路由：批量批改异步任务提交与状态查询。"""
import logging

from flask import Blueprint, jsonify, render_template, request

from utils.config import ERROR_AI_MODE, OCR_LANG_MAP
from utils.files import allowed_file, save_upload

logger = logging.getLogger(__name__)

bp = Blueprint('batch', __name__)


@bp.route('/batch_grade', methods=['POST'])
def batch_grade():
    """批量批改入口：接收参考答案图与多份作业图，异步启动批改线程。"""
    import threading

    from services.batch import run_batch_job
    from services.task_store import create_task

    file2 = request.files.get('file2')
    files = request.files.getlist('files')

    if not file2 or not file2.filename:
        return jsonify({"message": "缺少参考答案图片"}), 400
    if not files:
        return jsonify({"message": "缺少作业图片"}), 400
    if not allowed_file(file2.filename):
        return jsonify({"message": "不支持的文件类型"}), 400
    for file in files:
        if not file or not file.filename or not allowed_file(file.filename):
            return jsonify({"message": "不支持的文件类型"}), 400

    reference_path = save_upload(file2)
    work_paths = [save_upload(file) for file in files]

    language = request.form.get('language')
    lang = OCR_LANG_MAP.get(language, 'en')
    enable_segment = request.form.get('enable_segment') == 'true'
    error_ai_mode_raw = request.form.get('error_ai_mode')
    error_ai_mode = (
        error_ai_mode_raw == 'true'
        if error_ai_mode_raw is not None
        else ERROR_AI_MODE
    )

    task_id = create_task(len(work_paths))
    threading.Thread(
        target=run_batch_job,
        args=(task_id, reference_path, work_paths, lang, enable_segment, error_ai_mode),
        daemon=True,
    ).start()
    logger.info("批量批改任务已启动: task_id=%s, 作业数=%d", task_id, len(work_paths))
    return jsonify({"task_id": task_id}), 202


@bp.route('/batch_task/<task_id>', methods=['GET'])
def batch_task(task_id: str):
    """查询批量批改任务状态，任务不存在返回 404。"""
    from services.task_store import get_task

    task = get_task(task_id)
    if task is None:
        return jsonify({"message": "任务不存在"}), 404
    return jsonify(task), 200


@bp.route('/batch')
def batch_page():
    """渲染批量批改页面。"""
    return render_template('batch.html')
