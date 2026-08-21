"""分类题库 SQLite 存储实现（F7）：标准库 sqlite3，零新依赖。

每操作独立连接（天然跨线程安全），WAL 日志模式，供题库检索与构建脚本使用。
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from dataclasses import astuple
from typing import Iterator

from services.question_bank import BankQuestion
from utils import config

_SCHEMA = """
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
    "index" INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_qbank_subject ON question_bank(subject);
CREATE INDEX IF NOT EXISTS idx_qbank_qtype ON question_bank(qtype);
CREATE INDEX IF NOT EXISTS idx_qbank_difficulty ON question_bank(difficulty);
"""

_FACET_SQL = (
    "SELECT {column} AS value, COUNT(*) AS count "
    "FROM question_bank GROUP BY {column} ORDER BY count DESC"
)


class QuestionBankStore:
    """标准库 sqlite3 题库数据访问类：WAL 模式、每操作独立连接、with 事务语义。"""

    _INSERT_SQL = (
        'INSERT OR REPLACE INTO question_bank '
        '(qid, subject, qtype, grade, year, region, difficulty, source_type, '
        'source_file, question, answer, analysis, score, "index") '
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
    )

    def __init__(self, db_path: str = config.QUESTION_BANK_DB_PATH) -> None:
        """建父目录并幂等建表建索引，可重复初始化。"""
        self._db_path = db_path
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with self._session() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        """开新连接：设置行工厂并启用 WAL 日志模式。"""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    @contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        """事务会话：正常提交、异常回滚，退出时关闭连接。"""
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def insert_many(self, questions: list[BankQuestion]) -> int:
        """批量插入题库（INSERT OR REPLACE），返回插入条数。"""
        with self._session() as conn:
            conn.executemany(
                self._INSERT_SQL, [astuple(q) for q in questions]
            )
        return len(questions)

    def _filter_clause(
        self,
        subject: str | None = None,
        qtype: str | None = None,
        difficulty: str | None = None,
        source_type: str | None = None,
        year: str | None = None,
        keyword: str | None = None,
    ) -> tuple[str, list]:
        """按过滤条件动态拼 WHERE 子句与参数，keyword 走 LIKE 三字段。"""
        clauses: list[str] = []
        params: list[str] = []
        for column, value in (
            ("subject", subject),
            ("qtype", qtype),
            ("difficulty", difficulty),
            ("source_type", source_type),
            ("year", year),
        ):
            if value:
                clauses.append(f"{column}=?")
                params.append(value)
        if keyword:
            clauses.append("(question LIKE ? OR answer LIKE ? OR analysis LIKE ?)")
            params.extend([f"%{keyword}%"] * 3)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        return where, params

    def search(
        self,
        subject: str | None = None,
        qtype: str | None = None,
        difficulty: str | None = None,
        source_type: str | None = None,
        year: str | None = None,
        keyword: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """按过滤条件检索，返回 dict 列表；limit 默认 50、上限 200。"""
        where, params = self._filter_clause(
            subject, qtype, difficulty, source_type, year, keyword
        )
        params.append(min(limit, 200))
        params.append(offset)
        with self._session() as conn:
            rows = conn.execute(
                "SELECT * FROM question_bank" + where
                + ' ORDER BY subject, qtype, year, "index" LIMIT ? OFFSET ?',
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def count(
        self,
        subject: str | None = None,
        qtype: str | None = None,
        difficulty: str | None = None,
        source_type: str | None = None,
        year: str | None = None,
        keyword: str | None = None,
    ) -> int:
        """返回同过滤条件的总条数，供分页使用。"""
        where, params = self._filter_clause(
            subject, qtype, difficulty, source_type, year, keyword
        )
        with self._session() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM question_bank" + where, params
            ).fetchone()
        return int(row["cnt"])

    def get(self, qid: str) -> dict | None:
        """按主键查单条，不存在返回 None。"""
        with self._session() as conn:
            row = conn.execute(
                "SELECT * FROM question_bank WHERE qid=?", (qid,)
            ).fetchone()
        return dict(row) if row is not None else None

    def facets(self) -> dict:
        """返回各维度取值计数：subjects/qtypes/difficulties/source_types。"""
        result: dict[str, list[dict]] = {}
        with self._session() as conn:
            for name, column in (
                ("subjects", "subject"),
                ("qtypes", "qtype"),
                ("difficulties", "difficulty"),
                ("source_types", "source_type"),
            ):
                rows = conn.execute(_FACET_SQL.format(column=column)).fetchall()
                result[name] = [
                    {"value": row["value"], "count": row["count"]} for row in rows
                ]
        return result
