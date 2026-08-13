"""向量嵌入服务单元测试。"""
from unittest.mock import patch

import numpy as np
import pytest
from huggingface_hub.errors import LocalEntryNotFoundError

import services.embedding as embedding_module
from services.embedding import REPO_ID, _get_model, semantic_similarity


def test_semantic_similarity_identical_vectors_return_one():
    vectors = np.array([[1.0, 0.0], [1.0, 0.0]])
    with patch("services.embedding.encode", return_value=vectors):
        assert semantic_similarity("a", "a") == 1.0


def test_semantic_similarity_orthogonal_vectors_return_zero():
    vectors = np.array([[1.0, 0.0], [0.0, 1.0]])
    with patch("services.embedding.encode", return_value=vectors):
        assert semantic_similarity("a", "b") == 0.0


@pytest.fixture(autouse=True)
def _reset_model_singleton():
    """每轮测试前重置 _model 单例，保证用例隔离。"""
    embedding_module._model = None
    yield
    embedding_module._model = None


def test_get_model_cached_loads_from_local_path():
    """已缓存：snapshot_download 返回本地路径，SentenceTransformer 以该路径离线加载。"""
    local_path = "/cache/sentence-transformers_paraphrase-multilingual-MiniLM-L12-v2"
    with patch("huggingface_hub.snapshot_download", return_value=local_path) as mock_download, \
            patch("sentence_transformers.SentenceTransformer") as mock_st:
        model = _get_model()

        mock_download.assert_called_once_with(REPO_ID, local_files_only=True)
        mock_st.assert_called_once_with(local_path)
        assert model is mock_st.return_value


def test_get_model_not_cached_falls_back_to_repo_id():
    """未缓存：snapshot_download 抛 LocalEntryNotFoundError，回退到在线下载 REPO_ID。"""
    with patch(
        "huggingface_hub.snapshot_download",
        side_effect=LocalEntryNotFoundError("no local snapshot"),
    ) as mock_download, \
            patch("sentence_transformers.SentenceTransformer") as mock_st:
        model = _get_model()

        mock_download.assert_called_once_with(REPO_ID, local_files_only=True)
        mock_st.assert_called_once_with(REPO_ID)
        assert model is mock_st.return_value


def test_get_model_singleton_loads_model_once():
    """懒加载缓存：连续调用两次，snapshot_download 与 SentenceTransformer 各只被调用一次。"""
    local_path = "/cache/snapshot"
    with patch("huggingface_hub.snapshot_download", return_value=local_path) as mock_download, \
            patch("sentence_transformers.SentenceTransformer") as mock_st:
        first = _get_model()
        second = _get_model()

        assert first is second
        mock_download.assert_called_once()
        mock_st.assert_called_once()
