"""OCR 识别服务：封装 PaddleOCR 文字识别。"""
import logging
import threading
from typing import List

logger = logging.getLogger(__name__)

# 模块级单例缓存：键为语言，值为对应的 PaddleOCR 实例
_ocr_instances: dict[str, object] = {}
# 保护缓存创建，避免并发请求重复实例化
_load_lock = threading.Lock()


def _load_paddleocr(lang: str) -> object:
    """懒加载 PaddleOCR 实例并按语言缓存为单例，隔离导入以便离线测试 mock。"""
    if lang in _ocr_instances:
        return _ocr_instances[lang]
    with _load_lock:
        if lang not in _ocr_instances:
            from paddleocr import PaddleOCR
            _ocr_instances[lang] = PaddleOCR(show_log=False, use_angle_cls=True, lang=lang)
    return _ocr_instances[lang]


def recognize_texts(image_paths: List[str], lang: str = 'ch') -> List[str]:
    """识别多张图片文字，共享一个 OCR 实例，返回按行拼接的文本列表。"""
    ocr = _load_paddleocr(lang)
    texts = []
    for path in image_paths:
        result = ocr.ocr(path, cls=True)
        texts.append('\n'.join(str(line[1][0]) for line in (result[0] or [])))
    return texts
