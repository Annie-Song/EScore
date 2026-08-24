"""确定性标签派生模块（F7）：从文件名/分值/对错派生科目、题型、难度等分类标签。

纯函数、无 IO，供题库构建与检索复用。文件名格式为
`<年份段>_<科目token>_<题型后缀>.json`，例如
`2010-2022_Biology_Open-ended_Questions.json`、`2010-2013_English_MCQs.json`。
"""
from __future__ import annotations

import re

from backend.core import config

# 年份前缀，如 "2010-2022_" / "2012-2022_"
_YEAR_PREFIX_RE = re.compile(r"^\d{4}-\d{4}_")

# 科目 token → 中文科目
_SUBJECT_MAP = {
    "Math_I": "数学（理）",
    "Math_II": "数学（文）",
    "Chinese_Language": "语文",
    "Chinese_Lang": "语文",
    "Chinese": "语文",
    "English_Language": "英语",
    "English": "英语",
    "Biology": "生物",
    "Chemistry": "化学",
    "Geography": "地理",
    "History": "历史",
    "Physics": "物理",
    "Political_Science": "政治",
}

# 题型后缀 → 中文题型；匹配时按长度降序，长的优先，避免
# "Open-ended_Questions" 被 "Questions" 之类误截
_QTYPE_SUFFIX_MAP = {
    "Language_and_Writing_Skills_Open-ended_Questions": "语言文字运用",
    "Famous_Passages_and_Sentences_Dictation": "名篇名句默写",
    "Classical_Chinese_Reading": "文言文阅读",
    "Ancient_Poetry_Reading": "古诗文阅读",
    "Open-ended_Questions": "解答题",
    "Practical_Text_Reading": "实用类文本阅读",
    "Literary_Text_Reading": "文学类文本阅读",
    "Lang_and_Usage_MCQs": "语言文字运用（选择）",
    "Fill-in-the-Blank": "填空题",
    "Fill_in_Blanks": "填空题",
    "Cloze_Passage": "完形填空",
    "Cloze_Test": "完形填空",
    "Error_Correction": "短文改错",
    "Modern_Lit": "现代文阅读",
    "Reading_Comp": "阅读理解",
    "MCQs": "选择题",
}

_QTYPE_SUFFIX_SORTED = sorted(_QTYPE_SUFFIX_MAP, key=len, reverse=True)


def _strip_year_prefix(filename: str) -> str:
    """去掉文件名年份前缀与 .json 后缀，返回科目+题型部分。"""
    return _YEAR_PREFIX_RE.sub("", filename).removesuffix(".json")


def _match_qtype_suffix(rest: str) -> tuple[str, str]:
    """匹配最长题型后缀，返回 (剩余科目部分, 题型中文标签)。

    匹配不到时抛 ValueError（fail-fast，不塞默认值）。
    """
    for suffix in _QTYPE_SUFFIX_SORTED:
        if rest.endswith(suffix):
            return rest[: -len(suffix)], _QTYPE_SUFFIX_MAP[suffix]
    raise ValueError(f"无法从 {rest!r} 匹配题型后缀")


def subject_from_filename(filename: str) -> str:
    """从文件名派生中文科目。

    未知科目 token 时抛 ValueError。
    """
    rest, _ = _match_qtype_suffix(_strip_year_prefix(filename))
    token = rest.strip("_")
    if token not in _SUBJECT_MAP:
        raise ValueError(f"未知科目 token: {token!r}（来自文件名 {filename!r}）")
    return _SUBJECT_MAP[token]


def qtype_from_filename(filename: str) -> str:
    """从文件名派生中文题型。

    匹配不到题型后缀时抛 ValueError。
    """
    _, qtype = _match_qtype_suffix(_strip_year_prefix(filename))
    return qtype


def difficulty_from_score(score: int) -> str:
    """主观题分值分档弱代理难度。

    分值 >= 进阶下限判为"进阶"，< 基础上限判为"基础"，其余为"中等"。
    """
    if score >= config.QUESTION_BANK_DIFFICULTY_ADVANCED_MIN:
        return "进阶"
    if score < config.QUESTION_BANK_DIFFICULTY_BASIC_MAX:
        return "基础"
    return "中等"


def difficulty_from_correctness(correct: bool) -> str:
    """客观题 gpt-4 对错难度：正确→"基础"，错误→"进阶"。"""
    return "基础" if correct else "进阶"


def grade_label() -> str:
    """返回统一年级标签（分类题库覆盖高中）。"""
    return config.QUESTION_BANK_GRADE
