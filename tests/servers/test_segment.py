"""services/segment.py 水平投影作业分区单元测试。

用 cv2 在 tmp_path 下合成白底黑块图片（纯色矩形模拟文字块），验证：
区域数、index 序号、bbox 精确位置、间隙合并/切分阈值、噪声带过滤、
异常路径（全黑/全白/不存在/越界裁剪）。全程无外部依赖，可离线运行。
"""
from typing import List, Tuple

import cv2
import numpy as np
import pytest

from servers.ocr import segment

_WHITE = 255
_BLACK = 0
_WIDTH = 200
_HEIGHT = 200

# 块 = (y_start, y_end, x_start, x_end)，y_end/x_end 为闭区间
Block = Tuple[int, int, int, int]


def _make_image(path: str, blocks: List[Block], width: int = _WIDTH, height: int = _HEIGHT) -> str:
    """合成白底黑块图片并写为 PNG，返回路径。"""
    img = np.full((height, width), _WHITE, dtype=np.uint8)
    for y0, y1, x0, x1 in blocks:
        img[y0 : y1 + 1, x0 : x1 + 1] = _BLACK
    cv2.imwrite(str(path), img)
    return str(path)


def test_segment_image_single_block_returns_whole_image(tmp_path):
    """单题图：一整块文字无分界 → 1 个区域，bbox 为整图。"""
    path = _make_image(tmp_path / "single.png", [(10, 89, 20, 179)])
    regions = segment.segment_image(path)
    assert len(regions) == 1
    assert regions[0]["index"] == 1
    assert regions[0]["bbox"] == (0, 0, _WIDTH, _HEIGHT)


def test_segment_image_three_blocks_returns_three_regions_sorted(tmp_path):
    """多题图：3 个文字块（块间空白行 30 > 20）→ 3 个区域，按 y 排序且不重叠。"""
    blocks: List[Block] = [
        (10, 39, 20, 179),
        (70, 99, 50, 149),
        (130, 159, 30, 99),
    ]
    path = _make_image(tmp_path / "multi.png", blocks)
    regions = segment.segment_image(path)

    assert len(regions) == 3
    assert [r["index"] for r in regions] == [1, 2, 3]
    assert [r["bbox"] for r in regions] == [
        (20, 10, 160, 30),
        (50, 70, 100, 30),
        (30, 130, 70, 30),
    ]
    # 按 y 从上到下排序，区域间纵向不重叠
    ys = [r["bbox"][1] for r in regions]
    assert ys == sorted(ys)
    for prev, cur in zip(regions, regions[1:]):
        _, prev_y, _, prev_h = prev["bbox"]
        assert prev_y + prev_h <= cur["bbox"][1]


def test_segment_image_gap_19_merges_into_one_region(tmp_path):
    """间隙合并：两文字块间空白行 = 19（< 20）→ 合并为 1 个区域。"""
    blocks: List[Block] = [(20, 49, 20, 179), (69, 98, 50, 149)]
    path = _make_image(tmp_path / "gap19.png", blocks)
    regions = segment.segment_image(path)
    assert len(regions) == 1
    assert regions[0]["index"] == 1
    # 合并后单带 → 整图作为一个区域
    assert regions[0]["bbox"] == (0, 0, _WIDTH, _HEIGHT)


def test_segment_image_gap_20_splits_into_two_regions(tmp_path):
    """间隙切分：两文字块间空白行 = 20（≥ 20）→ 切成 2 个区域。"""
    blocks: List[Block] = [(20, 49, 20, 179), (70, 99, 50, 149)]
    path = _make_image(tmp_path / "gap20.png", blocks)
    regions = segment.segment_image(path)
    assert len(regions) == 2
    assert [r["index"] for r in regions] == [1, 2]
    assert [r["bbox"] for r in regions] == [
        (20, 20, 160, 30),
        (50, 70, 100, 30),
    ]


def test_segment_image_filters_thin_noise_strip(tmp_path):
    """噪声过滤：3 个正常文字块 + 1 个高 5px 细条 → 只返回 3 个区域。"""
    blocks: List[Block] = [
        (10, 39, 20, 179),
        (70, 99, 50, 149),
        (130, 134, 60, 139),  # 高 5px 的噪声细条，独立成带后应被丢弃
        (155, 184, 30, 99),
    ]
    path = _make_image(tmp_path / "noise.png", blocks)
    regions = segment.segment_image(path)
    assert len(regions) == 3
    assert [r["index"] for r in regions] == [1, 2, 3]
    assert [r["bbox"] for r in regions] == [
        (20, 10, 160, 30),
        (50, 70, 100, 30),
        (30, 155, 70, 30),
    ]


def test_segment_image_fully_black_raises_value_error(tmp_path):
    """全黑图：无可分区内容 → ValueError。"""
    path = str(tmp_path / "black.png")
    cv2.imwrite(path, np.zeros((_HEIGHT, _WIDTH), dtype=np.uint8))
    with pytest.raises(ValueError, match="全黑"):
        segment.segment_image(path)


def test_segment_image_all_white_no_content_raises_value_error(tmp_path):
    """全白图（无内容）→ ValueError。"""
    path = str(tmp_path / "white.png")
    cv2.imwrite(path, np.full((_HEIGHT, _WIDTH), _WHITE, dtype=np.uint8))
    with pytest.raises(ValueError, match="未检测到任何内容"):
        segment.segment_image(path)


def test_segment_image_missing_file_raises_value_error(tmp_path):
    """不存在的图片路径 → ValueError。"""
    with pytest.raises(ValueError, match="无法读取图片"):
        segment.segment_image(str(tmp_path / "missing.png"))


def test_crop_region_writes_png_with_matching_size(tmp_path):
    """crop_region 成功：返回 out_path，文件存在且尺寸与 bbox 一致。"""
    src = _make_image(tmp_path / "src.png", [(10, 89, 20, 179)])
    out = str(tmp_path / "out" / "region.png")
    bbox = (20, 10, 50, 30)

    result = segment.crop_region(src, bbox, out)

    assert result == out
    assert cv2.imread(out) is not None
    cropped = cv2.imread(out)
    x, y, w, h = bbox
    assert cropped.shape[0] == h
    assert cropped.shape[1] == w
    # 内容与原始图中对应区域完全一致
    src_img = cv2.imread(src)
    assert np.array_equal(cropped, src_img[y : y + h, x : x + w])


def test_crop_region_out_of_bounds_raises_value_error(tmp_path):
    """crop_region 越界 bbox（完全位于图外）→ ValueError。"""
    src = _make_image(tmp_path / "src.png", [(10, 89, 20, 179)])
    out = str(tmp_path / "out.png")
    with pytest.raises(ValueError, match="超出图片范围"):
        segment.crop_region(src, (220, 0, 50, 50), out)


def test_crop_region_unreadable_image_raises_value_error(tmp_path):
    """crop_region 无法读取图片 → ValueError。"""
    with pytest.raises(ValueError, match="无法读取图片"):
        segment.crop_region(str(tmp_path / "missing.png"), (0, 0, 10, 10), str(tmp_path / "o.png"))
