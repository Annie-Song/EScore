"""向量嵌入服务单元测试。"""
from unittest.mock import patch

import numpy as np

from services.embedding import semantic_similarity


def test_semantic_similarity_identical_vectors_return_one():
    vectors = np.array([[1.0, 0.0], [1.0, 0.0]])
    with patch("services.embedding.encode", return_value=vectors):
        assert semantic_similarity("a", "a") == 1.0


def test_semantic_similarity_orthogonal_vectors_return_zero():
    vectors = np.array([[1.0, 0.0], [0.0, 1.0]])
    with patch("services.embedding.encode", return_value=vectors):
        assert semantic_similarity("a", "b") == 0.0
