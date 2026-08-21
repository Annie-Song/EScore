"""题库构建脚本（scripts/build_question_bank.py）单元测试。

用 tmp_path 构造小型 GAOKAO 目录（主观/客观题目 + gpt-4 结果），直接调用 main()
以及用子进程直接运行脚本，离线独立验证入库结果，不触碰真实 data/gaokao。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Generator

import pytest

from scripts.build_question_bank import main as build_main
from services.question_bank_store import QuestionBankStore
from utils import config

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _restore_gaokao_dir() -> Generator[None, None, None]:
    """每个用例结束恢复 config.QUESTION_BANK_GAOKAO_DIR，避免 main() 全局副作用泄漏。"""
    original = config.QUESTION_BANK_GAOKAO_DIR
    yield
    config.QUESTION_BANK_GAOKAO_DIR = original


def _write_json(path: Path, payload) -> None:
    """把 payload 以 UTF-8 写入 path（自动创建父目录）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _make_question_file(path: Path, examples: list[dict]) -> None:
    """写 GAOKAO 风格题目文件（顶层 keywords + example）。"""
    _write_json(path, {"keywords": [], "example": examples})


def _build_source_dir(tmp_path: Path) -> Path:
    """构造 tmp 源目录：生物主观 2 题+1 空题干、数学客观 2 题、对应 gpt4 结果。"""
    src = tmp_path / "src"

    subj = src / "Data" / "Subjective_Questions" / "2010-2022_Biology_Open-ended_Questions.json"
    _make_question_file(
        subj,
        [
            {
                "year": 2018, "category": "（新课标）", "question": "描述线粒体的功能。",
                "answer": "有氧呼吸", "analysis": "线粒体是有氧呼吸的主要场所。",
                "index": 0, "score": 15,
            },
            {
                "year": 2019, "category": "（新课标）", "question": "孟德尔分离定律的实质。",
                "answer": "等位基因分离", "analysis": "减数分裂时等位基因随同源染色体分开。",
                "index": 1, "score": 5,
            },
            {
                "year": 2020, "category": "（新课标）", "question": "",
                "answer": "空题干", "analysis": "", "index": 2, "score": 10,
            },
        ],
    )

    obj = src / "Data" / "Objective_Questions" / "2010-2022_Math_I_MCQs.json"
    _make_question_file(
        obj,
        [
            {
                "year": 2010, "category": "（新课标）", "question": "集合 A∩B 等于",
                "answer": ["A"], "analysis": "交集为 {0,1,2}。", "index": 0, "score": 5,
            },
            {
                "year": 2010, "category": "（新课标）", "question": "复数 z 的模",
                "answer": ["C"], "analysis": "|z|=1/2。", "index": 1, "score": 5,
            },
        ],
    )

    gpt4 = src / "Results" / "gpt_4_0314_obj" / "gpt-4-0314_2010-2022_Math_I_MCQs.json"
    _write_json(
        gpt4,
        {
            "keyword": "math",
            "model_name": "gpt-4-0314",
            "prompt": "",
            "example": [
                {"index": 0, "standard_answer": ["A"], "model_answer": ["A"]},  # 正确
                {"index": 1, "standard_answer": ["C"], "model_answer": ["D"]},  # 错误
            ],
        },
    )
    return src


@pytest.fixture()
def src_dir(tmp_path) -> Path:
    """返回构造好的 tmp GAOKAO 源目录。"""
    return _build_source_dir(tmp_path)


def test_main_构建入库_汇总正确(src_dir, tmp_path) -> None:
    """main 构建入库：空题干跳过，总条数 4，source_type 分布主观 2、客观 2。"""
    db_path = str(tmp_path / "out.db")
    rc = build_main(["--db", db_path, "--source-dir", str(src_dir)])
    assert rc == 0
    store = QuestionBankStore(db_path)
    assert store.count() == 4
    assert store.count(source_type="subjective") == 2
    assert store.count(source_type="objective") == 2


def test_main_客观题难度来自gpt4(src_dir, tmp_path) -> None:
    """客观题难度来自 gpt4 对错（基础/进阶），主观题难度为分值分档。"""
    db_path = str(tmp_path / "out2.db")
    build_main(["--db", db_path, "--source-dir", str(src_dir)])
    store = QuestionBankStore(db_path)
    obj_by_index = {
        row["index"]: row
        for row in store.search(subject="数学（理）", source_type="objective")
    }
    assert obj_by_index[0]["difficulty"] == "基础"  # gpt4 正确
    assert obj_by_index[1]["difficulty"] == "进阶"  # gpt4 错误
    subj_by_index = {
        row["index"]: row
        for row in store.search(subject="生物", source_type="subjective")
    }
    assert subj_by_index[0]["difficulty"] == "进阶"  # 15 >= 12
    assert subj_by_index[1]["difficulty"] == "基础"  # 5 < 6


def test_main_缺gpt4结果_抛异常(src_dir, tmp_path) -> None:
    """删除 gpt4 结果文件后调用 main 应抛 FileNotFoundError（fail-fast，不静默回退）。"""
    gpt4 = (
        src_dir / "Results" / "gpt_4_0314_obj"
        / "gpt-4-0314_2010-2022_Math_I_MCQs.json"
    )
    gpt4.unlink()
    with pytest.raises(FileNotFoundError):
        build_main(["--db", str(tmp_path / "no_gpt4.db"), "--source-dir", str(src_dir)])


def test_直接运行脚本_sys_path引导(src_dir, tmp_path) -> None:
    """子进程直接运行脚本，验证 sys.path 根引导有效（python scripts/xxx.py 可直接跑）。"""
    db_path = str(tmp_path / "sub.db")
    script = _PROJECT_ROOT / "scripts" / "build_question_bank.py"
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.run(
        [sys.executable, str(script), "--db", db_path, "--source-dir", str(src_dir)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        cwd=str(_PROJECT_ROOT),
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "入库 4 题" in proc.stdout
