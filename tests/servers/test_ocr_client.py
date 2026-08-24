"""services/ocr.py OCR HTTP 客户端单元测试。

mock backend.ocr.client._post，覆盖客户端 4 个公开函数：recognize_texts 正常返回/
空列表短路/fail-fast 异常传播，segment_image 区域透传，crop_region 把 tuple
bbox 转 list 序列化进 payload，regions_with_shared_enhance 正常返回与 regions
为 null 时返回 None 的降级语义。全程不发起真实 HTTP，可离线独立运行。
"""
from unittest.mock import patch

import pytest

import backend.ocr.client as ocr_module
from backend.ocr.client import (
    crop_region,
    recognize_texts,
    regions_with_shared_enhance,
    segment_image,
)


def test_recognize_texts_posts_paths_and_lang():
    """recognize_texts 正常识别：payload 为 {paths, lang}，返回文本列表。"""
    with patch.object(
        ocr_module, "_post", return_value={"texts": ["第一题", "第二题"]}
    ) as mock_post:
        result = recognize_texts(["a.jpg", "b.jpg"], lang="ch")
    assert result == ["第一题", "第二题"]
    mock_post.assert_called_once_with(
        "/recognize_texts", {"paths": ["a.jpg", "b.jpg"], "lang": "ch"}
    )


def test_recognize_texts_empty_paths_short_circuits_without_post():
    """空图片列表本地短路返回空列表，_post 不被调用。"""
    with patch.object(ocr_module, "_post") as mock_post:
        result = recognize_texts([])
    assert result == []
    mock_post.assert_not_called()


def test_recognize_texts_post_runtime_error_propagates():
    """_post 抛 RuntimeError 时异常向上传播，不吞不塞默认值（fail-fast）。"""
    with patch.object(
        ocr_module, "_post", side_effect=RuntimeError("OCR 微服务不可达")
    ):
        with pytest.raises(RuntimeError, match="OCR 微服务不可达"):
            recognize_texts(["a.jpg"])


def test_segment_image_returns_regions_list():
    """segment_image 透传服务端 regions 列表，payload 为 {path}。"""
    expected = [{"index": 1, "bbox": [0, 0, 10, 10]}]
    with patch.object(
        ocr_module, "_post", return_value={"regions": expected}
    ) as mock_post:
        result = segment_image("hw.png")
    assert result == expected
    mock_post.assert_called_once_with("/segment_image", {"path": "hw.png"})


def test_crop_region_converts_bbox_tuple_to_list_and_returns_dst():
    """crop_region 把 tuple bbox 转成 list 序列化进 payload，返回落盘路径。"""
    with patch.object(ocr_module, "_post", return_value={"dst": "out.png"}) as mock_post:
        result = crop_region("src.png", (0, 0, 10, 10), "out.png")
    assert result == "out.png"
    mock_post.assert_called_once_with(
        "/crop_region", {"src": "src.png", "bbox": [0, 0, 10, 10], "dst": "out.png"}
    )


def test_regions_with_shared_enhance_returns_regions_list():
    """regions_with_shared_enhance 透传服务端 regions 列表，payload 原样带 regions。"""
    input_regions = [{"index": 1, "bbox": [0, 0, 10, 20]}]
    expected = [{"question_no": 1, "work_text": "题1"}]
    with patch.object(
        ocr_module, "_post", return_value={"regions": expected}
    ) as mock_post:
        result = regions_with_shared_enhance("img.jpg", "ch", input_regions)
    assert result == expected
    mock_post.assert_called_once_with(
        "/regions_with_shared_enhance",
        {"image_path": "img.jpg", "lang": "ch", "regions": input_regions},
    )


def test_regions_with_shared_enhance_null_regions_returns_none():
    """服务端 regions 为 null → 返回 None，保留降级回逐区原路径的语义。"""
    with patch.object(ocr_module, "_post", return_value={"regions": None}):
        result = regions_with_shared_enhance("img.jpg", "ch", [])
    assert result is None
