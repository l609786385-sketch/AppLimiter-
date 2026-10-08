from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .model import Rule, Session, canonical_path


class Store:
    """One connection per process/thread. Mutations use atomic SQLite transactions."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS rules (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL,
                single_seconds INTEGER NOT NULL CHECK(single_seconds > 0),
                daily_seconds INTEGER NOT NULL CHECK(daily_seconds > 0),
                enabled INTEGER NOT NULL DEFAULT 1, deleted INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS paths (
                path TEXT PRIMARY KEY, rule_id INTEGER NOT NULL REFERENCES rules(id)
            );
            CREATE TABLE IF NOT EXISTS usage (
                rule_id INTEGER NOT NULL REFERENCES rules(id), day TEXT NOT NULL,
                seconds REAL NOT NULL DEFAULT 0 CHECK(seconds >= 0),
                PRIMARY KEY(rule_id, day)
            );
            CREATE TABLE IF NOT EXISTS sessions (
                rule_id INTEGER PRIMARY KEY REFERENCES rules(id), seconds REAL NOT NULL,
                tokens TEXT NOT NULL, warnings TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY, at TEXT NOT NULL, rule_id INTEGER,
                kind TEXT NOT NULL, message TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS status (
                key TEXT PRIMARY KEY, value TEXT NOT NULL
            );
        """)

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.db.rollback()
            raise
        else:
            self.db.commit()

    def close(self):
        self.db.close()

    def rules(self) -> list[Rule]:
        # A single read transaction prevents observing a half-edited path list.
        self.db.execute("BEGIN")
        try:
            rows = self.db.execute("SELECT * FROM rules WHERE deleted=0 ORDER BY id").fetchall()
            paths = self.db.execute("SELECT * FROM paths ORDER BY path").fetchall()
            return [Rule(r["id"], r["name"], tuple(p["path"] for p in paths if p["rule_id"] == r["id"]),
                         r["single_seconds"], r["daily_seconds"], bool(r["enabled"])) for r in rows]
        finally:
            self.db.commit()

    def save_rule(self, name: str, paths: list[str], single: int, daily: int,
                  rule_id: int | None = None) -> int:
        if not name.strip() or single <= 0 or daily <= 0:
            raise ValueError("名称不能为空，时长必须大于零")
        normalized = sorted({canonical_path(p) for p in paths})
        if not normalized:
            raise ValueError("至少添加一个 EXE")
        with self.transaction():
            if rule_id is None:
                rule_id = self.db.execute(
                    "INSERT INTO rules(name,single_seconds,daily_seconds) VALUES(?,?,?)",
                    (name.strip(), single, daily)).lastrowid
            else:
                result = self.db.execute(
                    "UPDATE rules SET name=?,single_seconds=?,daily_seconds=? WHERE id=? AND deleted=0",
                    (name.strip(), single, daily, rule_id))
                if not result.rowcount:
                    raise ValueError("规则已经删除")
                self.db.execute("DELETE FROM paths WHERE rule_id=?", (rule_id,))
            try:
                self.db.executemany("INSERT INTO paths(path,rule_id) VALUES(?,?)",
                                    [(p, rule_id) for p in normalized])
            except sqlite3.IntegrityError as exc:
                raise ValueError("该 EXE 已属于另一条规则，请编辑原有规则") from exc
        return rule_id

    def enable(self, rule_id: int, value: bool):
        with self.transaction():
            self.db.execute("UPDATE rules SET enabled=? WHERE id=? AND deleted=0", (int(value), rule_id))

    def delete(self, rule_id: int):
        # Keep the historical usage; deleting a rule must not erase past records.
        with self.transaction():
            self.db.execute("UPDATE rules SET deleted=1,enabled=0 WHERE id=?", (rule_id,))
            self.db.execute("DELETE FROM paths WHERE rule_id=?", (rule_id,))

    def used(self, rule_id: int, day: str) -> float:
        row = self.db.execute("SELECT seconds FROM usage WHERE rule_id=? AND day=?", (rule_id, day)).fetchone()
        return row[0] if row else 0.0

    def add_usage(self, rule_id: int, day: str, seconds: float):
        if seconds <= 0:
            return
        self.db.execute("""INSERT INTO usage(rule_id,day,seconds) VALUES(?,?,?)
            ON CONFLICT(rule_id,day) DO UPDATE SET seconds=seconds+excluded.seconds""",
                        (rule_id, day, seconds))

    def session(self, rule_id: int) -> Session:
        row = self.db.execute("SELECT * FROM sessions WHERE rule_id=?", (rule_id,)).fetchone()
        return Session(row["seconds"], set(json.loads(row["tokens"])), set(json.loads(row["warnings"]))) if row else Session()

    def save_session(self, rule_id: int, session: Session):
        self.db.execute("""INSERT INTO sessions VALUES(?,?,?,?) ON CONFLICT(rule_id)
            DO UPDATE SET seconds=excluded.seconds,tokens=excluded.tokens,warnings=excluded.warnings""",
                        (rule_id, session.seconds, json.dumps(sorted(session.tokens)), json.dumps(sorted(session.warnings))))

    def event(self, at: str, rule_id: int | None, kind: str, message: str):
        self.db.execute("INSERT INTO events(at,rule_id,kind,message) VALUES(?,?,?,?)", (at, rule_id, kind, message))

    def events_after(self, event_id: int, limit: int = 100):
        return self.db.execute("SELECT * FROM events WHERE id>? ORDER BY id LIMIT ?", (event_id, limit)).fetchall()

    def latest_event_id(self) -> int:
        return self.db.execute("SELECT COALESCE(MAX(id),0) FROM events").fetchone()[0]

    def records(self, day: str):
        return self.db.execute("""SELECT r.name,r.deleted,u.day,u.seconds FROM usage u
            JOIN rules r ON r.id=u.rule_id WHERE u.day=? ORDER BY u.seconds DESC""", (day,)).fetchall()

    def set_status(self, key: str, value: str):
        self.db.execute("INSERT INTO status VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    def status(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM status WHERE key=?", (key,)).fetchone()
        return row[0] if row else None
