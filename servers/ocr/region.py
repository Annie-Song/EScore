"""分区低置信度区域整图增强去重识别：整图增强一次，各区域共享该增强图。

一图多题且整图平均置信度低时，逐区各自增强的成本随区域数线性放大（9 记录实测
耗 542s，单区域约 60s）。本模块改为整图先 Real-ESRGAN 增强一次，再从增强图
按比例放大后的 bbox 裁剪各区域逐区 OCR，各区域共享这一次增强；仍低置信的罕见
区域再逐区增强兜底，保持原行为。增强不可用、整图置信度不低或任一步骤异常时
返回 None，由调用方降级回逐区从原图裁剪的原路径。
"""
import logging
import os
import uuid
from typing import List, Optional, Tuple

import cv2

from servers.ocr import enhance
from servers.ocr.core import enhance_retry, ocr_instance, recognize_lines_of
from servers.ocr.segment import crop_region
from backend.core import config

logger = logging.getLogger(__name__)


def regions_with_shared_enhance(
    image_path: str,
    lang: str,
    regions: List[dict],
) -> Optional[List[dict]]:
    """对一图多题作业做整图增强去重识别，返回各区域识别结果列表。

    返回结构与 _regions_of 一致：每个元素含 question_no 与 work_text。
    整图平均置信度低于 config.ENHANCE_CONFIDENCE_THRESHOLD 且增强可用时，
    整图增强一次，再从增强图按比例缩放 bbox 裁剪各区域逐区 OCR；某区域仍低置信
    度时对该区域裁剪图再逐区增强兜底。增强不可用、整图置信度不低或任一步骤异常
    时返回 None，由调用方降级回逐区原路径。
    """
    try:
        return _try_shared_enhance(image_path, lang, regions)
    except Exception as exc:  # noqa: BLE001 - 增强为备选优化，异常时降级回原路径
        logger.warning("整图增强去重识别失败，降级回逐区原路径: %s", exc)
        return None


def _try_shared_enhance(
    image_path: str,
    lang: str,
    regions: List[dict],
) -> Optional[List[dict]]:
    """共享增强核心流程：判断整图置信度、增强一次、逐区识别；失败返回 None。"""
    if not enhance.is_available():
        return None
    ocr = ocr_instance(lang)
    _, whole_conf = recognize_lines_of(image_path, ocr)
    if whole_conf >= config.ENHANCE_CONFIDENCE_THRESHOLD:
        return None
    os.makedirs(config.ENHANCE_OUTPUT_FOLDER, exist_ok=True)
    enhanced_path = os.path.join(
        config.ENHANCE_OUTPUT_FOLDER, f"{uuid.uuid4().hex}.png"
    )
    enhance.enhance_image(image_path, enhanced_path)
    return _recognize_regions_from_enhanced(image_path, enhanced_path, regions, ocr)


def _recognize_regions_from_enhanced(
    image_path: str,
    enhanced_path: str,
    regions: List[dict],
    ocr: object,
) -> List[dict]:
    """从增强图按放大 bbox 裁剪各区域逐区识别，低置信区域再逐区增强兜底。"""
    src_w, src_h = _image_size(image_path)
    dst_w, dst_h = _image_size(enhanced_path)
    scale_x = dst_w / src_w
    scale_y = dst_h / src_h
    os.makedirs(config.SEGMENT_OUTPUT_FOLDER, exist_ok=True)
    result = []
    for region in regions:
        crop_path = os.path.join(
            config.SEGMENT_OUTPUT_FOLDER, f"{uuid.uuid4().hex}.png"
        )
        bbox = _scaled_bbox(region["bbox"], scale_x, scale_y)
        crop_region(enhanced_path, bbox, crop_path)
        lines, conf = recognize_lines_of(crop_path, ocr)
        if conf < config.ENHANCE_CONFIDENCE_THRESHOLD:
            lines = enhance_retry(ocr, crop_path, lines)
        text = '\n'.join(item[0] for item in lines)
        result.append({"question_no": region["index"], "work_text": text})
    return result


def _scaled_bbox(
    bbox: Tuple[int, int, int, int],
    scale_x: float,
    scale_y: float,
) -> Tuple[int, int, int, int]:
    """把原图 bbox 按 x/y 缩放比例映射到增强图坐标，四舍五入取整。

    裁剪越界防护由 crop_region 的 clamp 逻辑保证：超出增强图范围的边被裁剪，
    区域完全在界外时抛 ValueError，交由外层降级处理。
    """
    x, y, w, h = bbox
    return (
        int(round(x * scale_x)),
        int(round(y * scale_y)),
        int(round(w * scale_x)),
        int(round(h * scale_y)),
    )


def _image_size(path: str) -> Tuple[int, int]:
    """读取图片实际宽高 (w, h)；读取失败抛 ValueError，由外层降级。"""
    img = cv2.imread(path)
    if img is None:
        raise ValueError(f"无法读取图片: {path}")
    height, width = img.shape[:2]
    return width, height
