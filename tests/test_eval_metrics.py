"""纯文本评测指标（services/eval_metrics.py）单元测试。

覆盖 reference_ngram_coverage / lexical_dice / length_ratio 三个公开函数与内部
_char_ngrams。实现为纯标准库（字符级 n-gram），测试不依赖任何外部服务，可离线运行。
"""
from __future__ import annotations

import pytest

from services.eval_metrics import (
    _char_ngrams,
    length_ratio,
    lexical_dice,
    reference_ngram_coverage,
)


def test_reference_ngram_coverage_完全重叠():
    """作答与参考答案完全一致时覆盖比例为 1.0。"""
    assert reference_ngram_coverage("abcde", "abcde") == pytest.approx(1.0)


def test_reference_ngram_coverage_完全不重叠():
    """作答与参考无共享 n-gram 时覆盖比例为 0.0。"""
    assert reference_ngram_coverage("abcde", "mnop") == pytest.approx(0.0)


def test_reference_ngram_coverage_部分覆盖():
    """共享部分 n-gram 时覆盖比例落在 (0, 1)。"""
    assert reference_ngram_coverage("abcd", "bcde") == pytest.approx(0.5)


def test_reference_ngram_coverage_空输入():
    """reference 或 answer 为空时返回 0.0。"""
    assert reference_ngram_coverage("", "abc") == pytest.approx(0.0)
    assert reference_ngram_coverage("abc", "") == pytest.approx(0.0)


def test_reference_ngram_coverage_默认n与显式n():
    """默认 n=3 与显式 n=1 行为不同：n=1 时按单字匹配产生部分覆盖。"""
    assert reference_ngram_coverage("abc", "abd") == pytest.approx(0.0)  # n=3 无共享三元组
    assert reference_ngram_coverage("abc", "abd", n=1) == pytest.approx(2.0 / 3.0)


def test_reference_ngram_coverage_中英文():
    """中文按字符（Unicode 码点）滑窗，不报错且结果符合定义。"""
    assert reference_ngram_coverage("中文a", "a中文", n=2) == pytest.approx(0.5)


def test_lexical_dice_相同文本():
    """完全相同的文本 Dice 系数为 1.0。"""
    assert lexical_dice("abc", "abc") == pytest.approx(1.0)


def test_lexical_dice_完全不相交():
    """无共享 n-gram 时 Dice 系数为 0.0。"""
    assert lexical_dice("abc", "xyz") == pytest.approx(0.0)


def test_lexical_dice_部分重叠():
    """部分共享 n-gram 时 Dice 系数按 2|A∩B|/(|A|+|B|) 计算。"""
    assert lexical_dice("abcd", "bcde") == pytest.approx(2.0 * 2 / 6)


def test_lexical_dice_空输入():
    """任一侧文本为空时返回 0.0，避免除零。"""
    assert lexical_dice("", "abc") == pytest.approx(0.0)
    assert lexical_dice("abc", "") == pytest.approx(0.0)


def test_length_ratio_等长():
    """作答与参考等长时比例为 1.0。"""
    assert length_ratio("abc", "def") == pytest.approx(1.0)


def test_length_ratio_更长():
    """作答更长时比例大于 1。"""
    assert length_ratio("abc", "abcd") == pytest.approx(4.0 / 3.0)


def test_length_ratio_截断到上限():
    """比例超过 2 时截断为 2.0。"""
    assert length_ratio("abc", "abcdefghij") == pytest.approx(2.0)


def test_length_ratio_空输入():
    """reference 为空返回 0.0，answer 为空返回 0.0。"""
    assert length_ratio("", "abc") == pytest.approx(0.0)
    assert length_ratio("abc", "") == pytest.approx(0.0)


def test_char_ngrams_正常滑窗():
    """文本长度不小于 n 时按滑窗生成全部 n-gram。"""
    assert _char_ngrams("abcde", 3) == {"abc", "bcd", "cde"}


def test_char_ngrams_短于n退化():
    """文本长度不足 n 时退化为整篇去重字符集合。"""
    assert _char_ngrams("ab", 3) == {"a", "b"}


def test_char_ngrams_中文():
    """中文按字符滑窗，不报错且生成连续 n-gram。"""
    assert _char_ngrams("中文测试", 2) == {"中文", "文测", "测试"}
