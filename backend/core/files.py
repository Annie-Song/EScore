"""文件处理工具：上传文件校验与保存。"""
import os
import uuid
from typing import Any

from backend.core.config import ALLOWED_EXTENSIONS, UPLOAD_FOLDER


def allowed_file(filename: str) -> bool:
    """校验文件名后缀是否在允许范围内。"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def save_upload(file: Any, upload_folder: str = UPLOAD_FOLDER) -> str:
    """保存上传文件到 upload_folder，返回保存路径。"""
    os.makedirs(upload_folder, exist_ok=True)
    ext = file.filename.rsplit('.', 1)[1].lower()
    name = f"{uuid.uuid4().hex}.{ext}"
    path = os.path.join(upload_folder, name)
    file.save(path)
    return path
