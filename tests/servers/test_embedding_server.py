"""向量嵌入微服务 (services/embedding_server.py) 的单元测试。

模型加载与 HuggingFace 下载全部 mock，测试离线独立运行、不触发真实模型加载、不联网。
边界行为遵循 /encode /similarity /encode_reference /batch_similarity 的契约。
"""
from unittest.mock import Mock, call, patch

import numpy as np
import pytest
from fastapi.testclient import TestClient
from huggingface_hub.errors import LocalEntryNotFoundError

import servers.embedding.server as server_module
from servers.embedding.server import app
from backend.core import config


@pytest.fixture(autouse=True)
def _reset_server_state() -> None:
    """每轮测试前清空参考缓存与模型单例，保证用例隔离。"""
    server_module._REF_CACHE.clear()
    server_module._model = None
    yield
    server_module._REF_CACHE.clear()
    server_module._model = None


@pytest.fixture()
def client() -> TestClient:
    """FastAPI TestClient：纯内存 HTTP 请求，无外部依赖。"""
    with TestClient(app) as c:
        yield c


class _NormalizingFakeModel:
    """encode 返回 L2 归一化行向量，用于验证端点输出确为单位向量。"""

    def encode(self, texts: list[str], normalize_embeddings: bool = True) -> np.ndarray:
        vectors = [[3.0, 4.0] if i % 2 == 0 else [0.0, 5.0] for i in range(len(texts))]
        arr = np.array(vectors, dtype=np.float32)
        if normalize_embeddings:
            norms = np.linalg.norm(arr, axis=1, keepdims=True)
            arr = arr / np.where(norms == 0, 1.0, norms)
        return arr


def test_health_returns_ok_and_model_name_without_loading_model(client: TestClient) -> None:
    """/health 返回状态与模型名，且不触发模型加载。"""
    with patch.object(server_module, "_get_model") as mock_get_model:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "model": "paraphrase-multilingual-MiniLM-L12-v2"}
    mock_get_model.assert_not_called()


def test_encode_returns_normalized_vectors(client: TestClient) -> None:
    """/encode 对每段文本返回归一化向量（单位向量）并正确序列化。"""
    with patch.object(server_module, "_get_model", return_value=_NormalizingFakeModel()):
        resp = client.post("/encode", json={"texts": ["甲", "乙"]})
    assert resp.status_code == 200
    vectors = resp.json()["vectors"]
    assert vectors[0] == pytest.approx([0.6, 0.8], abs=1e-5)
    assert vectors[1] == pytest.approx([0.0, 1.0], abs=1e-5)
    for vec in vectors:
        norm = (vec[0] ** 2 + vec[1] ** 2) ** 0.5
        assert norm == pytest.approx(1.0, abs=1e-5)


def test_encode_non_list_texts_returns_422(client: TestClient) -> None:
    """/encode 请求体 texts 非列表返回 422。"""
    resp = client.post("/encode", json={"texts": "不是列表"})
    assert resp.status_code == 422


def test_similarity_identical_vectors_return_one(client: TestClient) -> None:
    """参考与答案编码为相同向量时 /similarity 返回 1.0，参考与答案各编码一次。"""

    def fake_encode(texts: list[str], normalize_embeddings: bool = True) -> np.ndarray:
        if texts == ["同一参考"]:
            return np.array([[1.0, 0.0]])
        return np.array([[1.0, 0.0]])

    model = Mock()
    model.encode.side_effect = fake_encode
    with patch.object(server_module, "_get_model", return_value=model):
        resp = client.post("/similarity", json={"reference": "同一参考", "answer": "同一答案"})
    assert resp.status_code == 200
    assert resp.json() == {"score": 1.0}
    assert model.encode.call_args_list == [
        call(["同一参考"], normalize_embeddings=True),
        call(["同一答案"], normalize_embeddings=True),
    ]


def test_similarity_orthogonal_vectors_return_zero(client: TestClient) -> None:
    """正交参考与答案向量点积为 0，参考经缓存路径、答案单独编码。"""

    def fake_encode(texts: list[str], normalize_embeddings: bool = True) -> np.ndarray:
        if texts == ["参考"]:
            return np.array([[1.0, 0.0]])
        return np.array([[0.0, 1.0]])

    model = Mock()
    model.encode.side_effect = fake_encode
    with patch.object(server_module, "_get_model", return_value=model):
        resp = client.post("/similarity", json={"reference": "参考", "answer": "答案"})
    assert resp.status_code == 200
    assert resp.json() == {"score": 0.0}


def test_similarity_same_reference_twice_reuses_cache_without_reencode(client: TestClient) -> None:
    """同一参考连续两次 /similarity：第二次参考命中缓存不重复编码，答案仍每次编码。"""

    def fake_encode(texts: list[str], normalize_embeddings: bool = True) -> np.ndarray:
        if texts == ["参考"]:
            return np.array([[1.0, 0.0]])
        return np.array([[1.0, 0.0]])

    model = Mock()
    model.encode.side_effect = fake_encode
    with patch.object(server_module, "_get_model", return_value=model):
        first = client.post("/similarity", json={"reference": "参考", "answer": "答案"})
        second = client.post("/similarity", json={"reference": "参考", "answer": "答案"})
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == {"score": 1.0}
    assert second.json() == {"score": 1.0}
    assert model.encode.call_args_list == [
        call(["参考"], normalize_embeddings=True),
        call(["答案"], normalize_embeddings=True),
        call(["答案"], normalize_embeddings=True),
    ]


def test_similarity_reference_precached_not_reencoded(client: TestClient) -> None:
    """参考已通过 /encode_reference 写入缓存时，/similarity 复用缓存不重复编码参考。"""

    def fake_encode(texts: list[str], normalize_embeddings: bool = True) -> np.ndarray:
        if texts == ["参考"]:
            return np.array([[1.0, 0.0]])
        return np.array([[0.0, 1.0]])

    model = Mock()
    model.encode.side_effect = fake_encode
    with patch.object(server_module, "_get_model", return_value=model):
        pre = client.post("/encode_reference", json={"text": "参考"})
        resp = client.post("/similarity", json={"reference": "参考", "answer": "答案"})
    assert pre.status_code == 200
    assert resp.status_code == 200
    assert resp.json() == {"score": 0.0}
    assert model.encode.call_args_list == [
        call(["参考"], normalize_embeddings=True),
        call(["答案"], normalize_embeddings=True),
    ]


def test_similarity_empty_reference_returns_zero_without_encode(client: TestClient) -> None:
    """/similarity 参考为空返回 {"score": 0.0}，且不触发任何编码。"""
    model = Mock()
    with patch.object(server_module, "_get_model", return_value=model):
        resp = client.post("/similarity", json={"reference": "", "answer": "答案"})
    assert resp.status_code == 200
    assert resp.json() == {"score": 0.0}
    model.encode.assert_not_called()


def test_encode_reference_same_text_uses_cache_without_reencode(client: TestClient) -> None:
    """同一参考文本第二次命中缓存，不重复编码模型。"""
    model = Mock()
    model.encode.return_value = np.array([[0.5, 0.5]])
    with patch.object(server_module, "_get_model", return_value=model):
        first = client.post("/encode_reference", json={"text": "参考甲"})
        second = client.post("/encode_reference", json={"text": "参考甲"})
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == {"vector": [0.5, 0.5]}
    assert second.json() == {"vector": [0.5, 0.5]}
    model.encode.assert_called_once_with(["参考甲"], normalize_embeddings=True)


def test_encode_reference_empty_text_returns_empty_vector(client: TestClient) -> None:
    """空参考文本返回空向量数组，不触发模型编码。"""
    model = Mock()
    with patch.object(server_module, "_get_model", return_value=model):
        resp = client.post("/encode_reference", json={"text": ""})
    assert resp.status_code == 200
    assert resp.json() == {"vector": []}
    model.encode.assert_not_called()


def test_batch_similarity_encodes_reference_once_then_answers_batch(client: TestClient) -> None:
    """参考嵌入编码一次 + 答案批编码一次，点积结果正确。"""

    def fake_encode(texts: list[str], normalize_embeddings: bool = True) -> np.ndarray:
        if texts == ["参考"]:
            return np.array([[1.0, 0.0]])
        return np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])

    model = Mock()
    model.encode.side_effect = fake_encode
    with patch.object(server_module, "_get_model", return_value=model):
        resp = client.post("/batch_similarity", json={
            "reference": "参考",
            "answers": ["答1", "答2", "答3"],
        })
    assert resp.status_code == 200
    assert resp.json() == {"scores": [1.0, 0.0, 1.0]}
    assert model.encode.call_count == 2
    assert model.encode.call_args_list == [
        call(["参考"], normalize_embeddings=True),
        call(["答1", "答2", "答3"], normalize_embeddings=True),
    ]


def test_batch_similarity_empty_answers_returns_empty_without_encode(client: TestClient) -> None:
    """answers 为空返回空列表，且不触发任何编码。"""
    model = Mock()
    with patch.object(server_module, "_get_model", return_value=model):
        resp = client.post("/batch_similarity", json={"reference": "参考", "answers": []})
    assert resp.status_code == 200
    assert resp.json() == {"scores": []}
    model.encode.assert_not_called()


def test_batch_similarity_empty_reference_returns_all_zeros(client: TestClient) -> None:
    """reference 为空返回全 0 分数，且不触发任何编码。"""
    model = Mock()
    with patch.object(server_module, "_get_model", return_value=model):
        resp = client.post("/batch_similarity", json={"reference": "", "answers": ["答1", "答2"]})
    assert resp.status_code == 200
    assert resp.json() == {"scores": [0.0, 0.0]}
    model.encode.assert_not_called()


def test_batch_similarity_reference_cached_not_reencoded(client: TestClient) -> None:
    """参考已在缓存时，批量接口不重复编码参考，只批编码答案。"""
    model = Mock()
    model.encode.side_effect = [
        np.array([[1.0, 0.0]]),
        np.array([[0.0, 1.0]]),
    ]
    with patch.object(server_module, "_get_model", return_value=model):
        first = client.post("/encode_reference", json={"text": "参考"})
        resp = client.post("/batch_similarity", json={"reference": "参考", "answers": ["答"]})
    assert first.status_code == 200
    assert resp.status_code == 200
    assert resp.json() == {"scores": [0.0]}
    assert model.encode.call_args_list == [
        call(["参考"], normalize_embeddings=True),
        call(["答"], normalize_embeddings=True),
    ]


def test_get_model_uses_local_snapshot_when_cached() -> None:
    """模型已缓存时 snapshot_download 返回本地路径，以本地路径离线加载。"""
    local_path = "/cache/sentence-transformers_paraphrase-multilingual-MiniLM-L12-v2"
    with patch("huggingface_hub.snapshot_download", return_value=local_path) as mock_download, \
            patch("sentence_transformers.SentenceTransformer") as mock_st:
        model = server_module._get_model()
    mock_download.assert_called_once_with(server_module.REPO_ID, local_files_only=True)
    mock_st.assert_called_once_with(local_path)
    assert model is mock_st.return_value


def test_get_model_falls_back_to_online_download_when_not_cached() -> None:
    """模型未缓存（LocalEntryNotFoundError）时回退在线下载 REPO_ID。"""
    with patch(
        "huggingface_hub.snapshot_download",
        side_effect=LocalEntryNotFoundError("no local snapshot"),
    ) as mock_download, \
            patch("sentence_transformers.SentenceTransformer") as mock_st:
        model = server_module._get_model()
    mock_download.assert_called_once_with(server_module.REPO_ID, local_files_only=True)
    mock_st.assert_called_once_with(server_module.REPO_ID)
    assert model is mock_st.return_value


def test_get_model_lazy_loads_model_singleton_once() -> None:
    """连续两次调用只加载一次模型。"""
    local_path = "/cache/snapshot"
    with patch("huggingface_hub.snapshot_download", return_value=local_path) as mock_download, \
            patch("sentence_transformers.SentenceTransformer") as mock_st:
        first = server_module._get_model()
        second = server_module._get_model()
    assert first is second
    mock_download.assert_called_once()
    mock_st.assert_called_once()


def test_ref_cache_overflow_clears_and_recomputes(monkeypatch, client: TestClient) -> None:
    """缓存达到上限整体清空后，旧键重新编码（内存有界）。"""
    monkeypatch.setattr(config, "REF_CACHE_MAX", 2)
    model = Mock()
    model.encode.side_effect = [
        np.array([[1.0]]),
        np.array([[2.0]]),
        np.array([[3.0]]),
        np.array([[4.0]]),
    ]
    with patch.object(server_module, "_get_model", return_value=model):
        client.post("/encode_reference", json={"text": "a"})
        client.post("/encode_reference", json={"text": "b"})
        client.post("/encode_reference", json={"text": "c"})
        client.post("/encode_reference", json={"text": "a"})
    assert model.encode.call_count == 4
    assert model.encode.call_args_list == [
        call(["a"], normalize_embeddings=True),
        call(["b"], normalize_embeddings=True),
        call(["c"], normalize_embeddings=True),
        call(["a"], normalize_embeddings=True),
    ]


def test_encode_missing_texts_returns_422(client: TestClient) -> None:
    """/encode 请求体缺 texts 字段返回 422。"""
    resp = client.post("/encode", json={})
    assert resp.status_code == 422


def test_similarity_missing_answer_returns_422(client: TestClient) -> None:
    """/similarity 请求体缺 answer 字段返回 422。"""
    resp = client.post("/similarity", json={"reference": "参考"})
    assert resp.status_code == 422


def test_encode_reference_missing_text_returns_422(client: TestClient) -> None:
    """/encode_reference 请求体缺 text 字段返回 422。"""
    resp = client.post("/encode_reference", json={})
    assert resp.status_code == 422


def test_batch_similarity_missing_answers_returns_422(client: TestClient) -> None:
    """/batch_similarity 请求体缺 answers 字段返回 422。"""
    resp = client.post("/batch_similarity", json={"reference": "参考"})
    assert resp.status_code == 422
