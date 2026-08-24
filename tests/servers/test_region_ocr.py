"""services/region_ocr.py 整图增强去重识别单元测试。

通过 mock servers.ocr.region 命名空间内的 enhance/ocr_instance/recognize_lines_of/
crop_region/enhance_retry/_image_size，覆盖增强不可用、整图高置信零成本路径、
低置信整图共享增强、区域级低置信兜底、增强/裁剪失败降级、bbox 缩放与空区域等分支。
全程不加载真实 PaddleOCR/ESRGAN，可离线独立运行。
"""
from unittest.mock import patch

import servers.ocr.region as region_ocr
from servers.ocr.region import regions_with_shared_enhance

# 两区域样例：与 batch._regions_of 里 segment_image 的输出结构一致
_REGIONS = [
    {"index": 1, "bbox": (0, 0, 10, 20)},
    {"index": 2, "bbox": (0, 20, 10, 20)},
]

# 假 OCR 单例哨兵：ocr_instance 被 mock 返回，recognize_lines_of 也被 mock，无需真实对象
_FAKE_OCR = object()


def _lines(text: str, conf: float) -> tuple:
    """构造 recognize_lines_of 的返回元组 (lines, avg_confidence)。"""
    return [(text, conf)], conf


def test_shared_enhance_unavailable_returns_none_without_ocr():
    """增强不可用 → 直接返回 None，不触发任何 OCR 实例化与识别。"""
    with patch.object(region_ocr.enhance, "is_available", return_value=False), \
         patch.object(region_ocr, "ocr_instance") as mock_ocr, \
         patch.object(region_ocr, "recognize_lines_of") as mock_rec:
        result = regions_with_shared_enhance("img.jpg", "ch", _REGIONS)
    assert result is None
    mock_ocr.assert_not_called()
    mock_rec.assert_not_called()


def test_shared_enhance_high_whole_confidence_returns_none():
    """整图平均置信度 ≥ 阈值 → 返回 None，不触发增强（零成本路径）。"""
    with patch.object(region_ocr.enhance, "is_available", return_value=True), \
         patch.object(region_ocr, "ocr_instance", return_value=_FAKE_OCR), \
         patch.object(region_ocr, "recognize_lines_of",
                      return_value=_lines("整图清晰", 0.9)) as mock_rec, \
         patch.object(region_ocr.enhance, "enhance_image") as mock_enhance:
        result = regions_with_shared_enhance("img.jpg", "ch", _REGIONS)
    assert result is None
    mock_rec.assert_called_once_with("img.jpg", _FAKE_OCR)
    mock_enhance.assert_not_called()


def test_shared_enhance_low_confidence_enhances_once_and_returns_regions():
    """整图低置信且增强可用 → 整图增强仅一次，各区域从增强图裁剪识别，结构一一对应。"""
    with patch.object(region_ocr.enhance, "is_available", return_value=True), \
         patch.object(region_ocr, "ocr_instance", return_value=_FAKE_OCR), \
         patch.object(region_ocr, "recognize_lines_of", side_effect=[
             _lines("整图模糊", 0.3),
             _lines("区域1清晰", 0.9),
             _lines("区域2清晰", 0.95),
         ]) as mock_rec, \
         patch.object(region_ocr.enhance, "enhance_image",
                      side_effect=lambda src, dst: dst) as mock_enhance, \
         patch.object(region_ocr, "_image_size", side_effect=[(100, 200), (400, 800)]), \
         patch.object(region_ocr, "crop_region",
                      side_effect=lambda src, bbox, out: out) as mock_crop, \
         patch.object(region_ocr, "enhance_retry",
                      side_effect=lambda ocr, path, lines: lines) as mock_retry:
        result = regions_with_shared_enhance("img.jpg", "ch", _REGIONS)

    assert result == [
        {"question_no": 1, "work_text": "区域1清晰"},
        {"question_no": 2, "work_text": "区域2清晰"},
    ]
    # 整图只增强一次，不是每区域一次
    mock_enhance.assert_called_once()
    assert mock_crop.call_count == 2
    # 裁剪源为增强输出图
    enhance_dst = mock_enhance.call_args[0][1]
    assert enhance_dst.startswith(region_ocr.config.ENHANCE_OUTPUT_FOLDER)
    for call in mock_crop.call_args_list:
        assert call.args[0] == enhance_dst
    # bbox 按 4x 缩放（src 100x200 → dst 400x800）
    assert mock_crop.call_args_list[0].args[1] == (0, 0, 40, 80)
    assert mock_crop.call_args_list[1].args[1] == (0, 80, 40, 80)
    # 总识别 1 次整图 + 2 次区域
    assert mock_rec.call_count == 3
    mock_retry.assert_not_called()


def test_shared_enhance_low_region_confidence_triggers_region_retry():
    """区域级低置信 → 对该区域裁剪图调 enhance_retry 兜底，其余区域不受影响。"""
    with patch.object(region_ocr.enhance, "is_available", return_value=True), \
         patch.object(region_ocr, "ocr_instance", return_value=_FAKE_OCR), \
         patch.object(region_ocr, "recognize_lines_of", side_effect=[
             _lines("整图模糊", 0.3),
             _lines("区域1清晰", 0.9),
             _lines("区域2模糊", 0.4),
         ]), \
         patch.object(region_ocr.enhance, "enhance_image",
                      side_effect=lambda src, dst: dst), \
         patch.object(region_ocr, "_image_size", side_effect=[(100, 200), (400, 800)]), \
         patch.object(region_ocr, "crop_region",
                      side_effect=lambda src, bbox, out: out) as mock_crop, \
         patch.object(region_ocr, "enhance_retry",
                      side_effect=lambda ocr, path, lines: [("区域2清晰", 0.9)]) as mock_retry:
        result = regions_with_shared_enhance("img.jpg", "ch", _REGIONS)

    assert result[1] == {"question_no": 2, "work_text": "区域2清晰"}
    mock_retry.assert_called_once()
    retry_args = mock_retry.call_args[0]
    assert retry_args[0] is _FAKE_OCR
    assert retry_args[1] == mock_crop.call_args_list[1].args[2]
    assert retry_args[2] == [("区域2模糊", 0.4)]


def test_shared_enhance_enhance_failure_degrades_to_none():
    """整图增强步骤抛异常 → 整体降级返回 None。"""
    with patch.object(region_ocr.enhance, "is_available", return_value=True), \
         patch.object(region_ocr, "ocr_instance", return_value=_FAKE_OCR), \
         patch.object(region_ocr, "recognize_lines_of",
                      return_value=_lines("整图模糊", 0.3)), \
         patch.object(region_ocr.enhance, "enhance_image",
                      side_effect=RuntimeError("mock enhance fail")):
        result = regions_with_shared_enhance("img.jpg", "ch", _REGIONS)
    assert result is None


def test_shared_enhance_crop_failure_degrades_to_none():
    """区域裁剪抛异常 → 整体降级返回 None。"""
    with patch.object(region_ocr.enhance, "is_available", return_value=True), \
         patch.object(region_ocr, "ocr_instance", return_value=_FAKE_OCR), \
         patch.object(region_ocr, "recognize_lines_of",
                      return_value=_lines("整图模糊", 0.3)), \
         patch.object(region_ocr.enhance, "enhance_image",
                      side_effect=lambda src, dst: dst), \
         patch.object(region_ocr, "_image_size", side_effect=[(100, 200), (400, 800)]), \
         patch.object(region_ocr, "crop_region",
                      side_effect=ValueError("裁剪越界")):
        result = regions_with_shared_enhance("img.jpg", "ch", _REGIONS)
    assert result is None


def test_shared_enhance_empty_regions_returns_empty_list():
    """空 regions → 整图低置信增强后无区域可识别，返回空列表。"""
    with patch.object(region_ocr.enhance, "is_available", return_value=True), \
         patch.object(region_ocr, "ocr_instance", return_value=_FAKE_OCR), \
         patch.object(region_ocr, "recognize_lines_of",
                      return_value=_lines("整图模糊", 0.3)), \
         patch.object(region_ocr.enhance, "enhance_image",
                      side_effect=lambda src, dst: dst) as mock_enhance, \
         patch.object(region_ocr, "_image_size", side_effect=[(100, 200), (400, 800)]), \
         patch.object(region_ocr, "crop_region",
                      side_effect=lambda src, bbox, out: out):
        result = regions_with_shared_enhance("img.jpg", "ch", [])
    assert result == []
    mock_enhance.assert_called_once()


def test_scaled_bbox_scales_xy_and_rounds():
    """_scaled_bbox 按 x/y 缩放比例映射并四舍五入取整。"""
    assert region_ocr._scaled_bbox((10, 20, 30, 40), 4.0, 2.0) == (40, 40, 120, 80)
    # 非整数缩放：7.5→8、17.5→18、13.5→14（Python 银行家舍入）
    assert region_ocr._scaled_bbox((3, 5, 7, 9), 2.5, 1.5) == (8, 8, 18, 14)
