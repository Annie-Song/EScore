"""纯文本指标（services）：无第三方依赖、字符级相似度，供评分离线 benchmark 多指标综合判别。

P5 问题：MiniLM 离线分被词汇重叠污染（good 强制改写→低重叠、medium 贴原文→高重叠，
medium 82.6 > good 80.8 反超）。本模块提供三个纯标准库字符级指标，弱化单一词汇重叠
信号，与 MiniLM 语义分融合为综合判别。中英文文本均可处理（中文按字、英文按字符，
Python str 即为 Unicode 码点序列，无需分词）。
"""
from __future__ import annotations


def _char_ngrams(text: str, n: int) -> set[str]:
    """取字符 n-gram 集合；文本长度不足 n 时退化为整篇去重字符集合。

    字符级、set 去重（仅取相异 n-gram，不做滑窗频率计数）；中文按字、英文按字母，
    均以 str 的码点序列处理。
    """
    if len(text) < n:
        return set(text)
    return {text[i:i + n] for i in range(len(text) - n + 1)}


def reference_ngram_coverage(reference: str, answer: str, n: int = 3) -> float:
    """参考答案的字符 n-gram 在作答中的覆盖比例。

    定义 |ref 的 n-gram ∩ ans 的 n-gram| / |ref 的 n-gram|，衡量作答覆盖了多少参考
    答案的字面措辞。空输入（reference 为空或 n-gram 集为空）返回 0.0。
    """
    ref_ngrams = _char_ngrams(reference, n)
    if not ref_ngrams:
        return 0.0
    ans_ngrams = _char_ngrams(answer, n)
    return len(ref_ngrams & ans_ngrams) / len(ref_ngrams)


def lexical_dice(reference: str, answer: str, n: int = 2) -> float:
    """字符 n-gram 的 Dice 系数 = 2*|A∩B| / (|A|+|B|)，衡量字面重叠度。

    任一侧 n-gram 集为空（含空文本）返回 0.0，避免除零。
    """
    ref_ngrams = _char_ngrams(reference, n)
    ans_ngrams = _char_ngrams(answer, n)
    if not ref_ngrams or not ans_ngrams:
        return 0.0
    return 2.0 * len(ref_ngrams & ans_ngrams) / (len(ref_ngrams) + len(ans_ngrams))


def length_ratio(reference: str, answer: str) -> float:
    """作答长度与参考答案长度之比，截断到 [0, 2]（过长作答信息量存疑，上限防离群值）。

    reference 为空返回 0.0；reference 非空而 answer 为空时比例自然为 0.0。
    """
    if not reference:
        return 0.0
    return max(0.0, min(2.0, len(answer) / len(reference)))
