"""确定性标签派生模块（services/question_bank_tags.py）单元测试。

覆盖科目/题型从真实文件名派生、未知 token 与匹配不到题型抛错、
分值分档与对错难度映射、年级标签等，全部为纯函数离线测试。
"""
import pytest

from services import question_bank_tags as tags
from utils import config

# 真实 GAOKAO-Bench 主观题全量文件名 → 期望中文科目（Data/Subjective_Questions）
_SUBJECTIVE_FILENAMES = [
    ("2010-2022_Biology_Open-ended_Questions.json", "生物"),
    ("2010-2022_Chemistry_Open-ended_Questions.json", "化学"),
    ("2010-2022_Chinese_Language_Ancient_Poetry_Reading.json", "语文"),
    ("2010-2022_Chinese_Language_Classical_Chinese_Reading.json", "语文"),
    ("2010-2022_Chinese_Language_Famous_Passages_and_Sentences_Dictation.json", "语文"),
    (
        "2010-2022_Chinese_Language_Language_and_Writing_Skills_Open-ended_Questions.json",
        "语文",
    ),
    ("2010-2022_Chinese_Language_Literary_Text_Reading.json", "语文"),
    ("2010-2022_Chinese_Language_Practical_Text_Reading.json", "语文"),
    ("2010-2022_Geography_Open-ended_Questions.json", "地理"),
    ("2010-2022_History_Open-ended_Questions.json", "历史"),
    ("2010-2022_Math_I_Fill-in-the-Blank.json", "数学（理）"),
    ("2010-2022_Math_I_Open-ended_Questions.json", "数学（理）"),
    ("2010-2022_Math_II_Fill-in-the-Blank.json", "数学（文）"),
    ("2010-2022_Math_II_Open-ended_Questions.json", "数学（文）"),
    ("2010-2022_Physics_Open-ended_Questions.json", "物理"),
    ("2010-2022_Political_Science_Open-ended_Questions.json", "政治"),
    ("2012-2022_English_Language_Error_Correction.json", "英语"),
    ("2014-2022_English_Language_Cloze_Passage.json", "英语"),
]

# 真实 GAOKAO-Bench 客观题全量文件名 → 期望中文科目（Data/Objective_Questions）
_OBJECTIVE_FILENAMES = [
    ("2010-2013_English_MCQs.json", "英语"),
    ("2010-2022_Biology_MCQs.json", "生物"),
    ("2010-2022_Chemistry_MCQs.json", "化学"),
    ("2010-2022_Chinese_Lang_and_Usage_MCQs.json", "语文"),
    ("2010-2022_Chinese_Modern_Lit.json", "语文"),
    ("2010-2022_English_Fill_in_Blanks.json", "英语"),
    ("2010-2022_English_Reading_Comp.json", "英语"),
    ("2010-2022_Geography_MCQs.json", "地理"),
    ("2010-2022_History_MCQs.json", "历史"),
    ("2010-2022_Math_I_MCQs.json", "数学（理）"),
    ("2010-2022_Math_II_MCQs.json", "数学（文）"),
    ("2010-2022_Physics_MCQs.json", "物理"),
    ("2010-2022_Political_Science_MCQs.json", "政治"),
    ("2012-2022_English_Cloze_Test.json", "英语"),
]

# 文件名 → 期望中文题型（覆盖长后缀优先等关键路径）
_QTYPE_FILENAMES = [
    ("2010-2022_Biology_Open-ended_Questions.json", "解答题"),
    ("2010-2022_Math_I_Fill-in-the-Blank.json", "填空题"),
    ("2010-2022_English_Fill_in_Blanks.json", "填空题"),
    ("2010-2022_Chinese_Language_Ancient_Poetry_Reading.json", "古诗文阅读"),
    (
        "2010-2022_Chinese_Language_Language_and_Writing_Skills_Open-ended_Questions.json",
        "语言文字运用",
    ),
    ("2010-2022_Chinese_Lang_and_Usage_MCQs.json", "语言文字运用（选择）"),
    ("2010-2022_Chinese_Modern_Lit.json", "现代文阅读"),
    ("2014-2022_English_Language_Cloze_Passage.json", "完形填空"),
    ("2012-2022_English_Cloze_Test.json", "完形填空"),
    ("2010-2022_Chinese_Language_Classical_Chinese_Reading.json", "文言文阅读"),
    ("2010-2022_Chinese_Language_Famous_Passages_and_Sentences_Dictation.json", "名篇名句默写"),
    ("2010-2022_Chinese_Language_Literary_Text_Reading.json", "文学类文本阅读"),
    ("2010-2022_Chinese_Language_Practical_Text_Reading.json", "实用类文本阅读"),
    ("2012-2022_English_Language_Error_Correction.json", "短文改错"),
    ("2010-2022_English_Reading_Comp.json", "阅读理解"),
    ("2010-2013_English_MCQs.json", "选择题"),
]


@pytest.mark.parametrize(
    "filename,expected_subject",
    _SUBJECTIVE_FILENAMES + _OBJECTIVE_FILENAMES,
    ids=[name for name, _ in _SUBJECTIVE_FILENAMES + _OBJECTIVE_FILENAMES],
)
def test_subject_from_filename_全科覆盖(filename: str, expected_subject: str) -> None:
    """真实全量主观/客观题文件名应派生正确中文科目（含同科多 token）。"""
    assert tags.subject_from_filename(filename) == expected_subject


@pytest.mark.parametrize(
    "filename,expected_qtype",
    _QTYPE_FILENAMES,
    ids=[name for name, _ in _QTYPE_FILENAMES],
)
def test_qtype_from_filename_题型覆盖(filename: str, expected_qtype: str) -> None:
    """文件名应派生正确中文题型，长后缀优先不被短后缀误截。"""
    assert tags.qtype_from_filename(filename) == expected_qtype


def test_未知科目token_抛异常() -> None:
    """未知科目 token 应抛 ValueError（fail-fast，不塞默认值）。"""
    with pytest.raises(ValueError, match="未知科目 token"):
        tags.subject_from_filename("2010-2022_Unknown_Open-ended_Questions.json")


def test_匹配不到题型_抛异常() -> None:
    """匹配不到题型后缀应抛 ValueError。"""
    with pytest.raises(ValueError, match="匹配题型后缀"):
        tags.subject_from_filename("2010-2022_Biology_WeirdType.json")
    with pytest.raises(ValueError, match="匹配题型后缀"):
        tags.qtype_from_filename("2010-2022_Biology_WeirdType.json")


@pytest.mark.parametrize(
    "score,expected_difficulty",
    [
        (12, "进阶"),
        (13, "进阶"),
        (6, "中等"),
        (11, "中等"),
        (5, "基础"),
        (0, "基础"),
    ],
)
def test_difficulty_from_score_边界(score: int, expected_difficulty: str) -> None:
    """分值分档：>=12 进阶、<6 基础、其余中等。"""
    assert tags.difficulty_from_score(score) == expected_difficulty


def test_difficulty_from_correctness() -> None:
    """客观题对错难度：正确→基础、错误→进阶。"""
    assert tags.difficulty_from_correctness(True) == "基础"
    assert tags.difficulty_from_correctness(False) == "进阶"


def test_grade_label() -> None:
    """年级标签应与 config 常量一致。"""
    assert tags.grade_label() == config.QUESTION_BANK_GRADE
