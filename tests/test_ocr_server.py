"""services/ocr_server.py FastAPI OCR 微服务的单元测试。

通过 mock services.ocr / services.segment / services.region_ocr 模块命名空间内的
函数（patch 约定见任务说明），覆盖 5 个端点的正常路径、空输入短路、tuple bbox
序列化、None 降级语义与 mock 抛异常返回 500。全程不触发真实 PaddleOCR/ESRGAN，
可离线独立运行。
"""
from unittest.mock import patch

from fastapi.testclient import TestClient

from services.ocr_server import app


def _make_client(raise_server_exceptions: bool = True) -> TestClient:
    """构造 FastAPI TestClient；500 用例需关闭 raise_server_exceptions。"""
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def test_health_returns_ok_service_ocr():
    """/health GET 返回 200 且 status=ok、service=ocr。"""
    with _make_client() as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "service": "ocr"}


def test_recognize_texts_returns_texts():
    """/recognize_texts 正常识别：mock 返回文本列表，响应按 {texts: [...]} 透传。"""
    with _make_client() as client, patch(
        "services.ocr.recognize_texts", return_value=["第一题答案", "第二题答案"]
    ) as mock_rec:
        resp = client.post(
            "/recognize_texts", json={"paths": ["a.png", "b.png"], "lang": "ch"}
        )
    assert resp.status_code == 200
    assert resp.json() == {"texts": ["第一题答案", "第二题答案"]}
    mock_rec.assert_called_once_with(["a.png", "b.png"], lang="ch")


def test_recognize_texts_empty_paths_short_circuits_without_ocr():
    """/recognize_texts 空 paths 本地短路返回 {texts: []}，不调用 OCR。"""
    with _make_client() as client, patch("services.ocr.recognize_texts") as mock_rec:
        resp = client.post("/recognize_texts", json={"paths": [], "lang": "ch"})
    assert resp.status_code == 200
    assert resp.json() == {"texts": []}
    mock_rec.assert_not_called()


def test_recognize_texts_mock_raises_returns_500():
    """/recognize_texts 底层识别抛异常 → 响应 500，fail-fast 不塞默认值。"""
    with _make_client(raise_server_exceptions=False) as client, patch(
        "services.ocr.recognize_texts", side_effect=RuntimeError("mock ocr fail")
    ):
        resp = client.post(
            "/recognize_texts", json={"paths": ["a.png"], "lang": "ch"}
        )
    assert resp.status_code == 500


def test_segment_image_bbox_tuple_serialized_as_list():
    """/segment_image 区域 bbox 由 tuple 序列化为 list[int]。"""
    regions = [{"index": 1, "bbox": (10, 20, 30, 40)}]
    with _make_client() as client, patch(
        "services.segment.segment_image", return_value=regions
    ) as mock_seg:
        resp = client.post("/segment_image", json={"path": "hw.png"})
    assert resp.status_code == 200
    assert resp.json() == {"regions": [{"index": 1, "bbox": [10, 20, 30, 40]}]}
    mock_seg.assert_called_once_with("hw.png")


def test_segment_image_mock_raises_returns_500():
    """/segment_image 分区抛异常 → 响应 500，fail-fast 不塞默认值。"""
    with _make_client(raise_server_exceptions=False) as client, patch(
        "services.segment.segment_image", side_effect=ValueError("mock segment fail")
    ):
        resp = client.post("/segment_image", json={"path": "hw.png"})
    assert resp.status_code == 500


def test_crop_region_bbox_converted_to_tuple_and_returns_dst():
    """/crop_region 请求 bbox 列表被转成 tuple 传给底层，返回 {dst: 路径}。"""
    with _make_client() as client, patch(
        "services.segment.crop_region", return_value="out.png"
    ) as mock_crop:
        resp = client.post(
            "/crop_region",
            json={"src": "src.png", "bbox": [10, 20, 30, 40], "dst": "out.png"},
        )
    assert resp.status_code == 200
    assert resp.json() == {"dst": "out.png"}
    mock_crop.assert_called_once_with("src.png", (10, 20, 30, 40), "out.png")


def test_regions_shared_enhance_returns_regions():
    """/regions_with_shared_enhance 正常识别：mock 返回区域列表，响应按 {regions: [...]} 透传。"""
    expected = [{"question_no": 1, "work_text": "题1"}]
    request_regions = [{"index": 1, "bbox": [0, 0, 10, 20]}]
    with _make_client() as client, patch(
        "services.region_ocr.regions_with_shared_enhance", return_value=expected
    ) as mock_fn:
        resp = client.post(
            "/regions_with_shared_enhance",
            json={"image_path": "img.jpg", "lang": "ch", "regions": request_regions},
        )
    assert resp.status_code == 200
    assert resp.json() == {"regions": expected}
    mock_fn.assert_called_once_with("img.jpg", "ch", request_regions)


def test_regions_shared_enhance_none_degrades_to_null():
    """/regions_with_shared_enhance 底层返回 None → 响应 {regions: null} 供客户端降级。"""
    with _make_client() as client, patch(
        "services.region_ocr.regions_with_shared_enhance", return_value=None
    ) as mock_fn:
        resp = client.post(
            "/regions_with_shared_enhance",
            json={"image_path": "img.jpg", "lang": "ch", "regions": []},
        )
    assert resp.status_code == 200
    assert resp.json() == {"regions": None}
    mock_fn.assert_called_once_with("img.jpg", "ch", [])
