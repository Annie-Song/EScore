"""文件处理工具单元测试。"""
from unittest.mock import MagicMock

from utils.files import allowed_file, save_upload


def test_allowed_file_accepts_jpg():
    assert allowed_file("photo.jpg") is True


def test_allowed_file_accepts_uppercase_extension():
    assert allowed_file("photo.PNG") is True


def test_allowed_file_rejects_executable():
    assert allowed_file("script.exe") is False


def test_allowed_file_rejects_no_extension():
    assert allowed_file("noext") is False


def test_save_upload_saves_with_unique_name(tmp_path):
    file = MagicMock()
    file.filename = "answer.png"
    path = save_upload(file, upload_folder=str(tmp_path))
    assert path.startswith(str(tmp_path))
    assert path.endswith(".png")
    file.save.assert_called_once()
