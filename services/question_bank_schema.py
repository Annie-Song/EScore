"""分类题库表结构（F10）：集中 question_bank 建表与补列迁移。

schema 与幂等迁移单独成模块，供 QuestionBankStore 复用：已有
output/question_bank.db 只含 14 列时，通过 ALTER TABLE 补齐租户维度三列。
"""
from __future__ import annotations

import sqlite3

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS question_bank (
    qid TEXT PRIMARY KEY,
    subject TEXT NOT NULL,
    qtype TEXT NOT NULL,
    grade TEXT NOT NULL,
    year TEXT NOT NULL,
    region TEXT NOT NULL,
    difficulty TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_file TEXT NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    analysis TEXT NOT NULL,
    score INTEGER NOT NULL,
    "index" INTEGER NOT NULL,
    school_id TEXT,
    created_by TEXT,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_qbank_subject ON question_bank(subject);
CREATE INDEX IF NOT EXISTS idx_qbank_qtype ON question_bank(qtype);
CREATE INDEX IF NOT EXISTS idx_qbank_difficulty ON question_bank(difficulty);
"""

# 追加的租户维度列：school_id 为 NULL 表示全局种子题
_MIGRATION_COLUMNS = ("school_id", "created_by", "created_at")

# school_id 索引依赖该列存在，旧库补列后另行创建，避免 executescript 提前失败
_SCHOOL_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_qbank_school ON question_bank(school_id)"
)


def ensure_schema(conn: sqlite3.Connection) -> None:
    """幂等建表建索引，并为旧库补齐缺失的租户维度列。

    重复初始化不报错：CREATE IF NOT EXISTS 跳过已存在对象，PRAGMA 探测
    现有列后再对缺失列逐条 ALTER TABLE ADD COLUMN；school_id 索引在补列后创建。
    """
    conn.executescript(SCHEMA_SQL)
    columns = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(question_bank)")
    }
    for name in _MIGRATION_COLUMNS:
        if name not in columns:
            conn.execute(f"ALTER TABLE question_bank ADD COLUMN {name} TEXT")
    conn.execute(_SCHOOL_INDEX_SQL)
