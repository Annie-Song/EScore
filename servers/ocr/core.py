"""OCR 服务端实现：封装 PaddleOCR 文字识别，低置信度时用 ESRGAN 增强后重识别。

A11 拆分：本模块为独立服务端实现，供 ocr_server.py 与 region_ocr.py 使用；
业务调用方通过 services/ocr.py HTTP 客户端访问。
"""
import logging
import os
import threading
import uuid
from typing import List, Tuple

from backend.core import config

logger = logging.getLogger(__name__)

# 模块级单例缓存：键为语言，值为对应的 PaddleOCR 实例
_ocr_instances: dict[str, object] = {}
# 保护缓存创建，避免并发请求重复实例化
_load_lock = threading.Lock()
# 保护实例推理：PaddleOCR 底层不线程安全，并发请求排队串行识别
_infer_lock = threading.Lock()
# 增强降级警告只记录一次，避免每个低置信度图片重复刷日志
_enhance_warned = False


def _load_paddleocr(lang: str) -> object:
    """懒加载 PaddleOCR 实例并按语言缓存为单例，隔离导入以便离线测试 mock。"""
    if lang in _ocr_instances:
        return _ocr_instances[lang]
    with _load_lock:
        if lang not in _ocr_instances:
            from paddleocr import PaddleOCR
            _ocr_instances[lang] = PaddleOCR(
                show_log=False,
                use_angle_cls=True,
                lang=lang,
                cpu_threads=config.OCR_CPU_THREADS,
                device=config.OCR_DEVICE,
            )
    return _ocr_instances[lang]


def _extract_lines(result: object) -> List[Tuple[str, float]]:
    """从 PaddleOCR 返回的 result[0] 中提取 (文本, 置信度) 列表，无文本时返回空列表。"""
    lines: List[Tuple[str, float]] = []
    for item in result[0] or []:
        text, score = item[1]
        lines.append((text, score))
    return lines


def _avg_confidence(lines: List[Tuple[str, float]]) -> float:
    """计算平均置信度；lines 为空时返回 0.0。"""
    if not lines:
        return 0.0
    return sum(score for _, score in lines) / len(lines)


def _recognize_lines(ocr: object, path: str) -> List[Tuple[str, float]]:
    """识别单张图片并返回 (文本, 置信度) 列表。"""
    with _infer_lock:
        result = ocr.ocr(path, cls=True)
    return _extract_lines(result)


def _enhance_and_retry(ocr: object, path: str) -> List[Tuple[str, float]]:
    """用 ESRGAN 增强图片后重识别，返回重识别结果。

    增强输出写入 config.ENHANCE_OUTPUT_FOLDER，文件名用 uuid 避免并发冲突。
    """
    from servers.ocr import enhance

    os.makedirs(config.ENHANCE_OUTPUT_FOLDER, exist_ok=True)
    dst_path = os.path.join(config.ENHANCE_OUTPUT_FOLDER, f"{uuid.uuid4().hex}.png")
    enhance.enhance_image(path, dst_path)
    return _recognize_lines(ocr, dst_path)


def _retry_with_enhance(
    ocr: object,
    path: str,
    lines: List[Tuple[str, float]],
) -> List[Tuple[str, float]]:
    """低置信度时尝试 ESRGAN 增强重识别，返回最终采用的 (文本, 置信度) 列表。"""
    global _enhance_warned
    from servers.ocr import enhance

    if not enhance.is_available():
        if not _enhance_warned:
            logger.warning("ESRGAN 模型不可用，跳过增强，仅走普通识别")
            _enhance_warned = True
        return lines
    try:
        enhanced_lines = _enhance_and_retry(ocr, path)
    except Exception as exc:  # noqa: BLE001 - 增强为备选功能，失败时降级为原识别结果
        logger.warning("ESRGAN 增强重识别失败，降级为原识别结果: %s", exc)
        return lines
    logger.info("低置信度，已增强重识别: %s", path)
    if _avg_confidence(enhanced_lines) > _avg_confidence(lines):
        return enhanced_lines
    return lines


def ocr_instance(lang: str = 'ch') -> object:
    """获取按语言缓存的 PaddleOCR 单例实例（懒加载），供批量链路直接复用。"""
    return _load_paddleocr(lang)


def recognize_lines_of(path: str, ocr: object) -> Tuple[List[Tuple[str, float]], float]:
    """识别单张图片并返回 (lines, avg_confidence)，不做增强决策。

    batch 层用它判断整图或区域平均置信度是否低，决定是否触发增强。
    """
    lines = _recognize_lines(ocr, path)
    return lines, _avg_confidence(lines)


def enhance_retry(
    ocr: object,
    path: str,
    lines: List[Tuple[str, float]],
) -> List[Tuple[str, float]]:
    """低置信度时对单张图片做 ESRGAN 增强重识别，返回最终采用的 lines。"""
    return _retry_with_enhance(ocr, path, lines)


def recognize_single(path: str, lang: str = 'ch') -> str:
    """识别单张图片文字：低置信度时增强重识别，返回按行拼接的文本。

    与 recognize_texts 单张图语义一致，供逐图循环与批量链路复用。
    """
    ocr = ocr_instance(lang)
    lines, avg_conf = recognize_lines_of(path, ocr)
    if avg_conf < config.ENHANCE_CONFIDENCE_THRESHOLD:
        lines = enhance_retry(ocr, path, lines)
    return '\n'.join(text for text, _ in lines)


def recognize_texts(image_paths: List[str], lang: str = 'ch') -> List[str]:
    """识别多张图片文字，逐图复用 recognize_single，返回按行拼接的文本列表。

    单张图片平均置信度低于 config.ENHANCE_CONFIDENCE_THRESHOLD 且 ESRGAN 增强
    可用时，增强该图后重识别；若增强后置信度更高则采用增强结果。
    """
    return [recognize_single(path, lang) for path in image_paths]
