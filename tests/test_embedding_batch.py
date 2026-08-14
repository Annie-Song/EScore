"""批量批改向量嵌入服务单元测试：参考嵌入缓存与批量相似度。"""
from unittest.mock import patch

import numpy as np
import pytest

import services.embedding as embedding_module
from services.embedding import batch_similarities, encode_reference
from utils import config as config_module


@pytest.fixture(autouse=True)
def _reset_ref_cache():
    """每轮测试前清空参考嵌入缓存，保证用例隔离。"""
    embedding_module._REF_CACHE.clear()
    yield
    embedding_module._REF_CACHE.clear()


def test_encode_reference_caches_same_text_once():
    """同一参考答案第二次调用不重新编码，命中缓存返回同一对象。"""
    with patch("services.embedding.encode", return_value=np.array([[0.5, 0.5]])) as mock_encode:
        first = encode_reference("同一参考答案")
        second = encode_reference("同一参考答案")
    np.testing.assert_array_equal(first, np.array([0.5, 0.5]))
    assert first is second
    mock_encode.assert_called_once_with(["同一参考答案"])


def test_encode_reference_different_texts_encode_each_once():
    """不同参考答案各编码一次，已缓存文本复用。"""
    with patch("services.embedding.encode", side_effect=[
        np.array([[1.0, 0.0]]),
        np.array([[0.0, 1.0]]),
    ]) as mock_encode:
        v1 = encode_reference("参考甲")
        v2 = encode_reference("参考乙")
        v1_again = encode_reference("参考甲")
    assert mock_encode.call_count == 2
    np.testing.assert_array_equal(v1, np.array([1.0, 0.0]))
    np.testing.assert_array_equal(v2, np.array([0.0, 1.0]))
    assert v1_again is v1


def test_encode_reference_cache_overflow_clears_and_recomputes(monkeypatch):
    """缓存达到上限整体清空后，旧键需重新编码。"""
    monkeypatch.setattr(config_module, "REF_CACHE_MAX", 2)
    with patch("services.embedding.encode", side_effect=[
        np.array([[1.0]]),
        np.array([[2.0]]),
        np.array([[3.0]]),
        np.array([[4.0]]),
    ]) as mock_encode:
        encode_reference("a")
        encode_reference("b")
        encode_reference("c")  # 缓存满（2 条），写入触发整体清空
        encode_reference("a")  # 旧键已清空，重新编码
    assert mock_encode.call_count == 4
    assert [call.args[0] for call in mock_encode.call_args_list] == [
        ["a"], ["b"], ["c"], ["a"],
    ]


def test_batch_similarities_encodes_reference_once_then_all_answers():
    """参考嵌入编码一次 + 全部答案批编码一次，点积结果正确。"""

    def fake_encode(texts):
        if texts == ["参考"]:
            return np.array([[1.0, 0.0]])
        return np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])

    with patch("services.embedding.encode", side_effect=fake_encode) as mock_encode:
        sims = batch_similarities("参考", ["答1", "答2", "答3"])
    assert sims == [1.0, 0.0, 1.0]
    assert mock_encode.call_count == 2
    assert mock_encode.call_args_list[0] == ((["参考"],),)
    assert mock_encode.call_args_list[1] == ((["答1", "答2", "答3"],),)


def test_batch_similarities_empty_answers_returns_empty_list():
    """answers 为空时直接返回空列表，不触发任何编码。"""
    with patch("services.embedding.encode") as mock_encode:
        assert batch_similarities("参考", []) == []
    mock_encode.assert_not_called()


def test_batch_similarities_reference_cached_not_reencoded():
    """参考已在缓存时，batch_similarities 不再重复编码参考。"""
    with patch("services.embedding.encode", side_effect=[
        np.array([[1.0, 0.0]]),
    ]):
        encode_reference("参考")
    with patch("services.embedding.encode", return_value=np.array([[0.0, 1.0]])) as mock_encode:
        sims = batch_similarities("参考", ["答"])
    assert sims == [0.0]
    mock_encode.assert_called_once_with(["答"])


def test_batch_similarities_empty_reference_returns_zeros():
    """参考答案为空时相似度全为 0，不触发编码。"""
    with patch("services.embedding.encode") as mock_encode:
        sims = batch_similarities("", ["答1", "答2"])
    assert sims == [0.0, 0.0]
    mock_encode.assert_not_called()
