"""作业智能分区服务：把一张图里含多道题的作业图片按水平投影切分为独立区域。

切分流程：读灰度图 → Otsu 反色二值化 + 形态学闭运算 → 计算行前景像素投影 →
按空白行切带 → 合并小间隙带、丢弃噪声带 → 输出从上到下排序的区域 bbox。
后续每个区域单独送入 OCR 评分。
"""
import os
from typing import List, Optional, Tuple

import cv2
import numpy as np

from backend.core import config

# 形态学闭运算核：3x3，把同一行内碎片笔迹连成带，避免单行被投影切成多带
_CLOSE_KERNEL = (3, 3)


def segment_image(image_path: str) -> list[dict]:
    """把包含多道题的图片按水平投影切分为独立区域，返回按从上到下排序的区域列表。

    返回: [{"index": 1, "bbox": (x, y, w, h)}, ...]，index 为 1 起始的题号，
    bbox 为左上角 (x, y) 加宽高 (w, h)，均为像素整数。图内无明显分界或本身
    就是单题时，整图作为一个区域返回。
    """
    img = _read_gray(image_path)
    binary = _binarize(img)
    height, width = binary.shape

    bands = _find_bands(
        binary,
        config.SEGMENT_BLANK_RATIO * width,
        config.SEGMENT_MIN_GAP,
        config.SEGMENT_MIN_HEIGHT,
    )

    # 单带：图内无明显分界或本身就是单题，整图作为一个区域
    if len(bands) == 1:
        return [{"index": 1, "bbox": (0, 0, width, height)}]
    if not bands:
        raise ValueError(f"图片未检测到任何内容，无法分区: {image_path}")

    return [
        {"index": index, "bbox": _band_bbox(binary, top, bottom)}
        for index, (top, bottom) in enumerate(bands, start=1)
    ]


def crop_region(image_path: str, bbox: tuple, out_path: str) -> str:
    """把 image_path 中 bbox 指定的区域裁出，写入 out_path（PNG），返回 out_path。"""
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"无法读取图片: {image_path}")
    x, y, w, h = bbox
    x = max(int(x), 0)
    y = max(int(y), 0)
    x2 = min(int(x + w), img.shape[1])
    y2 = min(int(y + h), img.shape[0])
    if x2 <= x or y2 <= y:
        raise ValueError(f"裁剪区域超出图片范围: {bbox}")
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    cv2.imwrite(out_path, img[y:y2, x:x2])
    return out_path


def _read_gray(image_path: str) -> np.ndarray:
    """读灰度图；读取失败或图片全黑时抛 ValueError，不吞异常。"""
    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError(f"无法读取图片: {image_path}")
    if int(img.max()) == 0:
        raise ValueError(f"图片全黑，无法分区: {image_path}")
    return img


def _binarize(img: np.ndarray) -> np.ndarray:
    """Otsu 反色二值化后做 3x3 闭运算，返回文字为前景(255)的二值图。"""
    _, binary = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, _CLOSE_KERNEL)
    return cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)


def _find_bands(
    binary: np.ndarray,
    blank_threshold: float,
    min_gap: int,
    min_height: int,
) -> List[Tuple[int, int]]:
    """从行投影切出非空白带，合并小间隙带并丢弃噪声带，返回 (top, bottom) 列表。"""
    row_projection = binary.sum(axis=1)
    height = len(row_projection)

    # 按空白行切出连续非空白带
    bands: List[Tuple[int, int]] = []
    start: Optional[int] = None
    for i in range(height):
        if row_projection[i] < blank_threshold:
            if start is not None:
                bands.append((start, i - 1))
                start = None
        elif start is None:
            start = i
    if start is not None:
        bands.append((start, height - 1))

    # 间隙小于 min_gap 的相邻带合并
    merged: List[Tuple[int, int]] = []
    for band in bands:
        if not merged:
            merged.append(band)
            continue
        prev_start, prev_end = merged[-1]
        if band[0] - prev_end - 1 < min_gap:
            merged[-1] = (prev_start, band[1])
        else:
            merged.append(band)

    # 高度小于 min_height 的噪声带丢弃
    return [b for b in merged if b[1] - b[0] + 1 >= min_height]


def _band_bbox(binary: np.ndarray, top: int, bottom: int) -> Tuple[int, int, int, int]:
    """计算带内列投影的前景左右界，返回 (x, y, w, h)。"""
    _, width = binary.shape
    col_projection = binary[top:bottom + 1, :].sum(axis=0)
    cols = np.where(col_projection > 0)[0]
    if cols.size == 0:
        # 带内无前景（不应发生），退化为全宽，避免返回空 bbox
        x, x2 = 0, width - 1
    else:
        x, x2 = int(cols[0]), int(cols[-1])
    return x, top, x2 - x + 1, bottom - top + 1
