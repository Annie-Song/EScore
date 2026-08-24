"""/api/grade_image 路由单元测试（外部依赖 recognize_texts/grade_answer 全 mock）。

覆盖正常路径、四类 400 校验、OCR 异常 500、allow_online 与档位联动、
forceOnline/language 透传、双层重复图缓存。save_upload 被 mock 返回真实临时文件
路径（file_sha1 需要读字节算缓存键），避免测试落盘业务上传目录。
"""
import io
from unittest.mock import patch

import pytest

import servers.ocr.core as ocr_core
from backend.app import create_app
from backend.grading import routes_image

# 1x1 透明 PNG，仅占位；save_upload 被 mock，字节不会被真实读取
_PNG = b"\x89PNG\r\n\x1a\n" \
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89" \
    b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"


def _write_upload(tmp_path, content: bytes = _PNG, name: str = "upload.png") -> str:
    """写入真实占位图片字节并返回路径，供 save_upload mock 返回（file_sha1 需可读）。"""
    path = tmp_path / name
    path.write_bytes(content)
    return str(path)


@pytest.fixture(autouse=True)
def _reset_caches():
    """每轮测试前后清空模块级评分结果缓存与 OCR 文本缓存，隔离用例间状态。"""
    routes_image._grade_cache.clear()
    ocr_core._text_cache.clear()
    yield
    routes_image._grade_cache.clear()
    ocr_core._text_cache.clear()


@pytest.fixture
def client():
    """构造 Flask 测试客户端。"""
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _multipart(reference="参考答案", filename="test.png", **fields) -> dict:
    """构造 multipart 请求体；reference=None 时省略 reference 字段。"""
    data = {"file": (io.BytesIO(_PNG), filename)}
    if reference is not None:
        data["reference"] = reference
    data.update(fields)
    return data


def _result(score: float = 90.0, method: str = "offline") -> dict:
    """构造 grade_answer 的完整返回结构。"""
    return {"score": score, "method": method, "degraded": False, "routed": False}


def test_grade_image_success_passes_args_and_returns_structure(client, tmp_path):
    """正常路径：grade_answer 收到 reference/quality_mode='fast'/allow_online=False。"""
    upload = _write_upload(tmp_path)
    with patch("backend.grading.routes_image.recognize_texts",
               return_value=["学生作答"]) as mock_rec, \
         patch("backend.grading.routes_image.grade_answer",
               return_value=_result()) as mock_grade, \
         patch("backend.grading.routes_image.save_upload", return_value=upload):
        resp = client.post("/api/grade_image", data=_multipart())
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["score"] == 90.0
    assert body["method"] == "offline"
    assert body["degraded"] is False
    assert body["routed"] is False
    assert body["workContent"] == "学生作答"
    mock_rec.assert_called_once_with([upload], lang="ch")
    assert mock_grade.call_args.args[0] == "参考答案"
    assert mock_grade.call_args.args[1] == "学生作答"
    assert mock_grade.call_args.kwargs["quality_mode"] == "fast"
    assert mock_grade.call_args.kwargs["allow_online"] is False


def test_grade_image_missing_file_returns_400(client):
    """缺 file → 400，message 含没有找到文件。"""
    resp = client.post("/api/grade_image", data={"reference": "参考答案"})
    assert resp.status_code == 400
    assert "没有找到文件" in resp.get_json()["message"]


def test_grade_image_unsupported_type_returns_400(client):
    """file 后缀不在白名单 → 400 不支持的文件类型。"""
    resp = client.post("/api/grade_image", data=_multipart(filename="x.txt"))
    assert resp.status_code == 400
    assert "不支持的文件类型" in resp.get_json()["message"]


def test_grade_image_missing_reference_returns_400(client):
    """缺 reference → 400 缺少参考答案文本。"""
    resp = client.post("/api/grade_image", data=_multipart(reference=None))
    assert resp.status_code == 400
    assert "缺少参考答案" in resp.get_json()["message"]


def test_grade_image_invalid_quality_returns_400_without_calling_grade(client, tmp_path):
    """quality 非法 → 400，grade_answer 不被调用。"""
    with patch("backend.grading.routes_image.recognize_texts",
               return_value=["学生作答"]), \
         patch("backend.grading.routes_image.grade_answer") as mock_grade, \
         patch("backend.grading.routes_image.save_upload",
               return_value=_write_upload(tmp_path)):
        resp = client.post("/api/grade_image", data=_multipart(quality="garbage"))
    assert resp.status_code == 400
    message = resp.get_json()["message"]
    assert "未知评分质量" in message
    assert "garbage" in message
    mock_grade.assert_not_called()


def test_grade_image_ocr_error_returns_500(client, tmp_path):
    """OCR 识别抛异常 → 500，message 含文字识别失败。"""
    with patch("backend.grading.routes_image.recognize_texts",
               side_effect=RuntimeError("mock ocr fail")), \
         patch("backend.grading.routes_image.grade_answer") as mock_grade, \
         patch("backend.grading.routes_image.save_upload",
               return_value=_write_upload(tmp_path)):
        resp = client.post("/api/grade_image", data=_multipart())
    assert resp.status_code == 500
    assert "文字识别失败" in resp.get_json()["message"]
    mock_grade.assert_not_called()


@pytest.mark.parametrize("plan,expected", [("pro", True), ("free", False)])
def test_grade_image_allow_online_depends_on_plan(client, plan, expected, tmp_path):
    """档位 pro → allow_online=True；free → allow_online=False。"""
    with patch("backend.auth.session.current_plan", return_value=plan), \
         patch("backend.grading.routes_image.recognize_texts",
               return_value=["学生作答"]), \
         patch("backend.grading.routes_image.grade_answer",
               return_value=_result(score=80.0)) as mock_grade, \
         patch("backend.grading.routes_image.save_upload",
               return_value=_write_upload(tmp_path)):
        resp = client.post("/api/grade_image", data=_multipart())
    assert resp.status_code == 200
    assert mock_grade.call_args.kwargs["allow_online"] is expected


def test_grade_image_force_online_and_language_passed_through(client, tmp_path):
    """forceOnline=true 与 language=英文 → force_online=True、lang='en'。"""
    with patch("backend.grading.routes_image.recognize_texts",
               return_value=["学生作答"]) as mock_rec, \
         patch("backend.grading.routes_image.grade_answer",
               return_value=_result(method="online")) as mock_grade, \
         patch("backend.grading.routes_image.save_upload",
               return_value=_write_upload(tmp_path)):
        resp = client.post(
            "/api/grade_image",
            data=_multipart(forceOnline="true", language="英文"),
        )
    assert resp.status_code == 200
    assert mock_rec.call_args.kwargs["lang"] == "en"
    assert mock_grade.call_args.kwargs["force_online"] is True


def test_grade_image_cache_hit_same_image_same_reference(client, tmp_path):
    """相同图片+相同参考第二次请求命中缓存：recognize_texts/grade_answer 均不再调用。"""
    upload = _write_upload(tmp_path)
    with patch("backend.grading.routes_image.recognize_texts",
               return_value=["学生作答"]) as mock_rec, \
         patch("backend.grading.routes_image.grade_answer",
               return_value=_result(score=88.0)) as mock_grade, \
         patch("backend.grading.routes_image.save_upload", return_value=upload):
        first = client.post("/api/grade_image", data=_multipart())
        second = client.post("/api/grade_image", data=_multipart())
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.get_json() == second.get_json()
    assert mock_rec.call_count == 1
    assert mock_grade.call_count == 1


def test_grade_image_cache_miss_different_reference(client, tmp_path):
    """参考不同 → 不命中缓存，recognize_texts/grade_answer 各再次调用。"""
    upload = _write_upload(tmp_path)
    with patch("backend.grading.routes_image.recognize_texts",
               return_value=["学生作答"]) as mock_rec, \
         patch("backend.grading.routes_image.grade_answer",
               return_value=_result()) as mock_grade, \
         patch("backend.grading.routes_image.save_upload", return_value=upload):
        client.post("/api/grade_image", data=_multipart(reference="参考答案A"))
        client.post("/api/grade_image", data=_multipart(reference="参考答案B"))
    assert mock_rec.call_count == 2
    assert mock_grade.call_count == 2


def test_grade_image_cache_miss_different_image(client, tmp_path):
    """图片不同 → 不命中缓存，recognize_texts/grade_answer 各再次调用。"""
    upload_a = _write_upload(tmp_path, content=b"image-content-a", name="a.png")
    upload_b = _write_upload(tmp_path, content=b"image-content-b", name="b.png")
    with patch("backend.grading.routes_image.recognize_texts",
               return_value=["学生作答"]) as mock_rec, \
         patch("backend.grading.routes_image.grade_answer",
               return_value=_result()) as mock_grade, \
         patch("backend.grading.routes_image.save_upload",
               side_effect=[upload_a, upload_b]):
        client.post("/api/grade_image", data=_multipart())
        client.post("/api/grade_image", data=_multipart())
    assert mock_rec.call_count == 2
    assert mock_grade.call_count == 2
