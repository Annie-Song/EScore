"""Flask 路由：首页、OCR 识别、文本评分、报告下载。"""
import logging
import os
import uuid
from datetime import datetime
from urllib.parse import quote

from flask import Blueprint, Response, jsonify, render_template, request, send_file

from backend.ocr.client import recognize_texts
from backend.grading.report import build_report_docx, build_report_html
from backend.scoring.engine import grade_answer
from backend.core.config import (
    DEFAULT_ROUTING_PRESET,
    OCR_LANG_MAP,
    REPORT_FILENAME,
    REPORT_FOLDER,
    ROUTING_PRESETS,
)
from backend.core.files import allowed_file, save_upload

_DOCX_MIMETYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

logger = logging.getLogger(__name__)

bp = Blueprint('main', __name__)


@bp.route('/')
def home():
    """渲染首页。"""
    return render_template('index.html')


@bp.route('/guide')
def guide():
    """渲染快速开始教程页。"""
    return render_template('guide.html')


@bp.route('/ocr', methods=['POST'])
def ocr_service():
    """识别学生作业图片与参考答案图片中的文字。"""
    if 'file1' not in request.files or 'file2' not in request.files:
        return jsonify({"message": "没有找到文件！"}), 400

    file1 = request.files['file1']
    file2 = request.files['file2']

    if not file1 or not file1.filename or not file2 or not file2.filename:
        return jsonify({"message": "上传文件失败"}), 400

    if not allowed_file(file1.filename) or not allowed_file(file2.filename):
        return jsonify({"message": "不支持的文件类型"}), 400

    file1_path = save_upload(file1)
    file2_path = save_upload(file2)

    language = request.form.get('language')
    lang = OCR_LANG_MAP.get(language, 'en')
    logger.info("OCR 请求: %s, %s, language=%s", file1_path, file2_path, language)

    try:
        work_content, answer_content = recognize_texts([file1_path, file2_path], lang=lang)
        return jsonify({
            "workContent": work_content,
            "answerContent": answer_content,
        }), 200

    except Exception as e:
        logger.error("OCR 处理出错: %s", e, exc_info=True)
        return jsonify({"message": "文字识别失败，请重试"}), 500


@bp.route('/compare_texts', methods=['POST'])
def compare_texts():
    """对作业内容与参考答案评分，支持在线/离线模式。"""
    data = request.json
    work_content = data.get('workContent')
    answer_content = data.get('answerContent')
    force_online = data.get('forceOnline', False)
    quality = data.get('quality') or DEFAULT_ROUTING_PRESET
    if quality not in ROUTING_PRESETS:
        return jsonify({"message": f"未知评分质量: {quality}"}), 400

    if not work_content or not answer_content:
        return jsonify({"message": "请输入作业内容和参考答案内容"}), 400

    # 延迟导入避免与 backend.auth.session 的循环依赖；free 档无在线精排权限，
    # allow_online=False 让 grade_answer 内部把显式精排优雅降级为离线。
    from backend.auth.session import current_plan

    result = grade_answer(
        answer_content,
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
    }), 200


@bp.route('/download_report', methods=['POST'])
def download_report():
    """根据比对结果生成批改报告并下载，支持 html 与 docx 两种格式。"""
    data = request.json
    if not data:
        return jsonify({"message": "请求体不能为空"}), 400

    work_content = data.get('workContent')
    answer_content = data.get('answerContent')
    fmt = data.get('format', 'html')

    if not work_content or not answer_content:
        return jsonify({"message": "缺少作业内容或参考答案内容"}), 400
    if fmt not in ('html', 'docx'):
        return jsonify({"message": "不支持的下载格式"}), 400

    report_data = {
        "work_content": work_content,
        "answer_content": answer_content,
        "score": data.get('score'),
        "method": data.get('method'),
        "degraded": data.get('degraded'),
        "routed": data.get('routed'),
        "generated_at": datetime.now().isoformat(),
    }

    try:
        if fmt == 'html':
            html_report = build_report_html(report_data)
            html_name = f"{REPORT_FILENAME}.html"
            return Response(
                html_report,
                mimetype='text/html',
                headers={
                    'Content-Disposition': (
                        "attachment; filename=report.html; "
                        f"filename*=UTF-8''{quote(html_name)}"
                    )
                },
            )

        os.makedirs(REPORT_FOLDER, exist_ok=True)
        docx_name = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}.docx"
        # abspath 统一解析：makedirs/写入按 CWD 落盘，send_file 却按 app.root_path 拼接相对路径，
        # 若不转绝对路径，默认配置下 send_file 会读不到文件而 500。
        out_path = os.path.abspath(os.path.join(REPORT_FOLDER, docx_name))
        build_report_docx(report_data, out_path)
        return send_file(
            out_path,
            as_attachment=True,
            download_name=f"{REPORT_FILENAME}.docx",
            mimetype=_DOCX_MIMETYPE,
        )

    except Exception as e:
        logger.error("报告下载生成出错: %s", e, exc_info=True)
        return jsonify({"message": "报告生成失败，请重试"}), 500
