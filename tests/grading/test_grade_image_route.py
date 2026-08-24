"""/api/grade_image 路由单元测试（外部依赖 recognize_texts/grade_answer 全 mock）。

覆盖正常路径、四类 400 校验、OCR 异常 500、allow_online 与档位联动、
forceOnline/language 透传。save_upload 一并 mock，避免测试落盘真实文件。
"""
import io
from unittest.mock import patch

import pytest

from backend.app import create_app

# 1x1 透明 PNG，仅占位；save_upload 被 mock，字节不会被真实读取
_PNG = b"\x89PNG\r\n\x1a\n" \
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89" \
    b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"


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


def test_grade_image_success_passes_args_and_returns_structure(client):
    """正常路径：grade_answer 收到 reference/quality_mode='fast'/allow_online=False。"""
    with patch("backend.grading.routes_image.recognize_texts",
               return_value=["学生作答"]) as mock_rec, \
         patch("backend.grading.routes_image.grade_answer",
               return_value=_result()) as mock_grade, \
         patch("backend.grading.routes_image.save_upload", return_value="uploads/x.png"):
        resp = client.post("/api/grade_image", data=_multipart())
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["score"] == 90.0
    assert body["method"] == "offline"
    assert body["degraded"] is False
    assert body["routed"] is False
    assert body["workContent"] == "学生作答"
    mock_rec.assert_called_once_with(["uploads/x.png"], lang="ch")
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


def test_grade_image_invalid_quality_returns_400_without_calling_grade(client):
    """quality 非法 → 400，grade_answer 不被调用。"""
    with patch("backend.grading.routes_image.recognize_texts",
               return_value=["学生作答"]), \
         patch("backend.grading.routes_image.grade_answer") as mock_grade, \
         patch("backend.grading.routes_image.save_upload", return_value="uploads/x.png"):
        resp = client.post("/api/grade_image", data=_multipart(quality="garbage"))
    assert resp.status_code == 400
    message = resp.get_json()["message"]
    assert "未知评分质量" in message
    assert "garbage" in message
    mock_grade.assert_not_called()


def test_grade_image_ocr_error_returns_500(client):
    """OCR 识别抛异常 → 500，message 含文字识别失败。"""
    with patch("backend.grading.routes_image.recognize_texts",
               side_effect=RuntimeError("mock ocr fail")), \
         patch("backend.grading.routes_image.grade_answer") as mock_grade, \
         patch("backend.grading.routes_image.save_upload", return_value="uploads/x.png"):
        resp = client.post("/api/grade_image", data=_multipart())
    assert resp.status_code == 500
    assert "文字识别失败" in resp.get_json()["message"]
    mock_grade.assert_not_called()


@pytest.mark.parametrize("plan,expected", [("pro", True), ("free", False)])
def test_grade_image_allow_online_depends_on_plan(client, plan, expected):
    """档位 pro → allow_online=True；free → allow_online=False。"""
    with patch("backend.auth.session.current_plan", return_value=plan), \
         patch("backend.grading.routes_image.recognize_texts",
               return_value=["学生作答"]), \
         patch("backend.grading.routes_image.grade_answer",
               return_value=_result(score=80.0)) as mock_grade, \
         patch("backend.grading.routes_image.save_upload", return_value="uploads/x.png"):
        resp = client.post("/api/grade_image", data=_multipart())
    assert resp.status_code == 200
    assert mock_grade.call_args.kwargs["allow_online"] is expected


def test_grade_image_force_online_and_language_passed_through(client):
    """forceOnline=true 与 language=英文 → force_online=True、lang='en'。"""
    with patch("backend.grading.routes_image.recognize_texts",
               return_value=["学生作答"]) as mock_rec, \
         patch("backend.grading.routes_image.grade_answer",
               return_value=_result(method="online")) as mock_grade, \
         patch("backend.grading.routes_image.save_upload", return_value="uploads/x.png"):
        resp = client.post(
            "/api/grade_image",
            data=_multipart(forceOnline="true", language="英文"),
        )
    assert resp.status_code == 200
    assert mock_rec.call_args.kwargs["lang"] == "en"
    assert mock_grade.call_args.kwargs["force_online"] is True
