"""OCR 识别服务：封装 PaddleOCR 文字识别。"""
import logging
from typing import List

logger = logging.getLogger(__name__)


def _load_paddleocr(lang: str):
    """懒加载 PaddleOCR 实例，隔离导入以便离线测试 mock。"""
    from paddleocr import PaddleOCR
    return PaddleOCR(show_log=False, use_angle_cls=True, lang=lang)


def recognize_texts(image_paths: List[str], lang: str = 'ch') -> List[str]:
    """识别多张图片文字，共享一个 OCR 实例，返回按行拼接的文本列表。"""
    ocr = _load_paddleocr(lang)
    texts = []
    for path in image_paths:
        result = ocr.ocr(path, cls=True)
        texts.append('\n'.join(str(line[1][0]) for line in (result[0] or [])))
    return texts
