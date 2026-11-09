"""SQLite persistence layer with schema migrations."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from taskplanner.core.models import (
    Category,
    Milestone,
    ParBadge,
    SourceType,
    Task,
    TaskStatus,
    WorkType,
)

MIGRATIONS: list[str] = [
    # v1
    """
    CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);

    CREATE TABLE tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        work_type TEXT NOT NULL DEFAULT 'other',
        priority INTEGER NOT NULL DEFAULT 2,
        due_date TEXT,
        tags TEXT NOT NULL DEFAULT '[]',
        match_apps TEXT NOT NULL DEFAULT '[]',
        match_keywords TEXT NOT NULL DEFAULT '[]',
        user_guess_minutes REAL,
        ai_guess_minutes REAL,
        par_minutes REAL NOT NULL DEFAULT 0,
        par_low REAL NOT NULL DEFAULT 0,
        par_high REAL NOT NULL DEFAULT 0,
        par_basis TEXT NOT NULL DEFAULT 'default',
        base_minutes REAL NOT NULL DEFAULT 0,
        original_par REAL NOT NULL DEFAULT 0,
        revisions INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'todo',
        created_at REAL NOT NULL,
        started_at REAL,
        completed_at REAL,
        badge TEXT,
        actual_minutes REAL NOT NULL DEFAULT 0
    );
    CREATE INDEX idx_tasks_status ON tasks(status);

    CREATE TABLE milestones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
        title TEXT NOT NULL,
        position INTEGER NOT NULL DEFAULT 0,
        guess_minutes REAL,
        par_minutes REAL NOT NULL DEFAULT 0,
        source_type TEXT NOT NULL DEFAULT 'manual',
        source_config TEXT NOT NULL DEFAULT '{}',
        baseline TEXT NOT NULL DEFAULT '{}',
        progress REAL NOT NULL DEFAULT 0,
        evidence TEXT NOT NULL DEFAULT '',
        done_at REAL
    );
    CREATE INDEX idx_milestones_task ON milestones(task_id);

    CREATE TABLE progress_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts REAL NOT NULL,
        task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
        milestone_id INTEGER REFERENCES milestones(id) ON DELETE SET NULL,
        delta REAL NOT NULL,
        earned_minutes REAL NOT NULL,
        source TEXT NOT NULL DEFAULT 'manual'
    );
    CREATE INDEX idx_progress_ts ON progress_events(ts);

    CREATE TABLE activity (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        start_ts REAL NOT NULL,
        end_ts REAL NOT NULL,
        process TEXT NOT NULL,
        title TEXT NOT NULL,
        category TEXT NOT NULL,
        task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL
    );
    CREATE INDEX idx_activity_start ON activity(start_ts);
    CREATE INDEX idx_activity_task ON activity(task_id);

    CREATE TABLE plans (
        date TEXT NOT NULL,
        task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
        position INTEGER NOT NULL DEFAULT 0,
        planned_minutes REAL NOT NULL,
        available_minutes REAL NOT NULL,
        PRIMARY KEY (date, task_id)
    );

    CREATE TABLE days (
        date TEXT PRIMARY KEY,
        finalized INTEGER NOT NULL DEFAULT 0,
        data TEXT NOT NULL DEFAULT '{}'
    );

    CREATE TABLE xp_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts REAL NOT NULL,
        amount INTEGER NOT NULL,
        reason TEXT NOT NULL,
        ref TEXT
    );

    CREATE TABLE achievements (
        key TEXT PRIMARY KEY,
        unlocked_at REAL NOT NULL
    );
    """,
    # v2: task-level links to the repo/document/folder the work lives in
    """
    ALTER TABLE tasks ADD COLUMN links TEXT NOT NULL DEFAULT '{}';
    """,
    # v3: plan commit time (only output earned after committing counts as delivered)
    """
    ALTER TABLE plans ADD COLUMN committed_at REAL NOT NULL DEFAULT 0;
    """,
]


def local_date(ts: float) -> str:
    return datetime.fromtimestamp(ts).date().isoformat()


def day_bounds(day: str) -> tuple[float, float]:
    d = date.fromisoformat(day)
    start = datetime(d.year, d.month, d.day).timestamp()
    end = (datetime(d.year, d.month, d.day) + timedelta(days=1)).timestamp()
    return start, end


class Database:
    """Thread-safe wrapper around a single SQLite connection."""

    def __init__(self, path: Path | str):
        self.path = str(path)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            self.conn.execute("PRAGMA journal_mode = WAL")
        self._migrate()

    # ------------------------------------------------------------------ infra
    def _migrate(self) -> None:
        with self._lock:
            version = self.conn.execute("PRAGMA user_version").fetchone()[0]
            for i, script in enumerate(MIGRATIONS[version:], start=version + 1):
                self.conn.execute("BEGIN")
                try:
                    for statement in _split_sql(script):
                        self.conn.execute(statement)
                    self.conn.execute(f"PRAGMA user_version = {i}")
                    self.conn.execute("COMMIT")
                except Exception:
                    self.conn.execute("ROLLBACK")
                    raise

    @property
    def schema_version(self) -> int:
        return self.conn.execute("PRAGMA user_version").fetchone()[0]

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self.conn.execute(sql, tuple(params))

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(sql, tuple(params)).fetchall()

    def transaction(self) -> _Transaction:
        return _Transaction(self)

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    # --------------------------------------------------------------- settings
    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self.query("SELECT value FROM settings WHERE key = ?", (key,))
        return json.loads(row[0]["value"]) if row else default

    def set_setting(self, key: str, value: Any) -> None:
        self.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )

    # ------------------------------------------------------------------ tasks
    def save_task(self, task: Task) -> Task:
        cols = {
            "title": task.title,
            "description": task.description,
            "work_type": task.work_type.value,
            "priority": task.priority,
            "due_date": task.due_date,
            "tags": json.dumps(task.tags),
            "match_apps": json.dumps(task.match_apps),
            "match_keywords": json.dumps(task.match_keywords),
            "user_guess_minutes": task.user_guess_minutes,
            "ai_guess_minutes": task.ai_guess_minutes,
            "par_minutes": task.par_minutes,
            "par_low": task.par_low,
            "par_high": task.par_high,
            "par_basis": task.par_basis,
            "base_minutes": task.base_minutes,
            "original_par": task.original_par,
            "revisions": task.revisions,
            "status": task.status.value,
            "created_at": task.created_at,
            "started_at": task.started_at,
            "completed_at": task.completed_at,
            "badge": task.badge.value if task.badge else None,
            "actual_minutes": task.actual_minutes,
            "links": json.dumps(task.links),
        }
        with self.transaction():
            if task.id is None:
                names = ", ".join(cols)
                marks = ", ".join("?" for _ in cols)
                cur = self.execute(f"INSERT INTO tasks({names}) VALUES({marks})", cols.values())
                task.id = cur.lastrowid
            else:
                sets = ", ".join(f"{k} = ?" for k in cols)
                self.execute(f"UPDATE tasks SET {sets} WHERE id = ?", [*cols.values(), task.id])
            keep_ids = []
            for pos, m in enumerate(task.milestones):
                m.position = pos
                m.task_id = task.id
                self.save_milestone(m)
                keep_ids.append(m.id)
            if keep_ids:
                marks = ", ".join("?" for _ in keep_ids)
                self.execute(
                    f"DELETE FROM milestones WHERE task_id = ? AND id NOT IN ({marks})",
                    [task.id, *keep_ids],
                )
            else:
                self.execute("DELETE FROM milestones WHERE task_id = ?", (task.id,))
        return task

    def save_milestone(self, m: Milestone) -> Milestone:
        cols = {
            "task_id": m.task_id,
            "title": m.title,
            "position": m.position,
            "guess_minutes": m.guess_minutes,
            "par_minutes": m.par_minutes,
            "source_type": m.source_type.value,
            "source_config": json.dumps(m.source_config),
            "baseline": json.dumps(m.baseline),
            "progress": m.progress,
            "evidence": m.evidence,
            "done_at": m.done_at,
        }
        if m.id is None:
            names = ", ".join(cols)
            marks = ", ".join("?" for _ in cols)
            cur = self.execute(f"INSERT INTO milestones({names}) VALUES({marks})", cols.values())
            m.id = cur.lastrowid
        else:
            sets = ", ".join(f"{k} = ?" for k in cols)
            self.execute(f"UPDATE milestones SET {sets} WHERE id = ?", [*cols.values(), m.id])
        return m

    def get_task(self, task_id: int) -> Task | None:
        rows = self.query("SELECT * FROM tasks WHERE id = ?", (task_id,))
        if not rows:
            return None
        return self._hydrate([rows[0]])[0]

    def list_tasks(self, statuses: Iterable[TaskStatus] | None = None) -> list[Task]:
        if statuses:
            vals = [s.value for s in statuses]
            marks = ", ".join("?" for _ in vals)
            rows = self.query(
                f"SELECT * FROM tasks WHERE status IN ({marks}) ORDER BY priority DESC, "
                "COALESCE(due_date, '9999') ASC, created_at ASC",
                vals,
            )
        else:
            rows = self.query("SELECT * FROM tasks ORDER BY created_at DESC")
        return self._hydrate(rows)

    def open_tasks(self) -> list[Task]:
        return self.list_tasks([TaskStatus.TODO, TaskStatus.ACTIVE])

    def delete_task(self, task_id: int) -> None:
        self.execute("DELETE FROM tasks WHERE id = ?", (task_id,))

    def _hydrate(self, rows: list[sqlite3.Row]) -> list[Task]:
        if not rows:
            return []
        ids = [r["id"] for r in rows]
        marks = ", ".join("?" for _ in ids)
        mrows = self.query(
            f"SELECT * FROM milestones WHERE task_id IN ({marks}) ORDER BY position, id", ids
        )
        by_task: dict[int, list[Milestone]] = {}
        for r in mrows:
            by_task.setdefault(r["task_id"], []).append(
                Milestone(
                    id=r["id"],
                    task_id=r["task_id"],
                    title=r["title"],
                    position=r["position"],
                    guess_minutes=r["guess_minutes"],
                    par_minutes=r["par_minutes"],
                    source_type=SourceType(r["source_type"]),
                    source_config=json.loads(r["source_config"]),
                    baseline=json.loads(r["baseline"]),
                    progress=r["progress"],
                    evidence=r["evidence"],
                    done_at=r["done_at"],
                )
            )
        tasks = []
        for r in rows:
            tasks.append(
                Task(
                    id=r["id"],
                    title=r["title"],
                    description=r["description"],
                    work_type=WorkType(r["work_type"]),
                    priority=r["priority"],
                    due_date=r["due_date"],
                    tags=json.loads(r["tags"]),
                    match_apps=json.loads(r["match_apps"]),
                    match_keywords=json.loads(r["match_keywords"]),
                    user_guess_minutes=r["user_guess_minutes"],
                    ai_guess_minutes=r["ai_guess_minutes"],
                    par_minutes=r["par_minutes"],
                    par_low=r["par_low"],
                    par_high=r["par_high"],
                    par_basis=r["par_basis"],
                    base_minutes=r["base_minutes"],
                    original_par=r["original_par"],
                    revisions=r["revisions"],
                    status=TaskStatus(r["status"]),
                    created_at=r["created_at"],
                    started_at=r["started_at"],
                    completed_at=r["completed_at"],
                    badge=ParBadge(r["badge"]) if r["badge"] else None,
                    actual_minutes=r["actual_minutes"],
                    links=json.loads(r["links"] or "{}"),
                    milestones=by_task.get(r["id"], []),
                )
            )
        return tasks

    # --------------------------------------------------------------- progress
    def add_progress_event(
        self,
        task_id: int,
        milestone_id: int | None,
        delta: float,
        earned_minutes: float,
        source: str,
        ts: float | None = None,
    ) -> None:
        self.execute(
            "INSERT INTO progress_events(ts, task_id, milestone_id, delta, earned_minutes, source) "
            "VALUES(?, ?, ?, ?, ?, ?)",
            (ts or time.time(), task_id, milestone_id, delta, earned_minutes, source),
        )

    def earned_between(self, start: float, end: float, task_ids: Iterable[int] | None = None) -> float:
        if task_ids is not None:
            ids = list(task_ids)
            if not ids:
                return 0.0
            marks = ", ".join("?" for _ in ids)
            row = self.query(
                "SELECT COALESCE(SUM(earned_minutes), 0) AS s FROM progress_events "
                f"WHERE ts >= ? AND ts < ? AND task_id IN ({marks})",
                [start, end, *ids],
            )
        else:
            row = self.query(
                "SELECT COALESCE(SUM(earned_minutes), 0) AS s FROM progress_events "
                "WHERE ts >= ? AND ts < ?",
                (start, end),
            )
        return float(row[0]["s"])

    # --------------------------------------------------------------- activity
    def add_activity(
        self,
        start: float,
        end: float,
        process: str,
        title: str,
        category: Category,
        task_id: int | None,
    ) -> int:
        cur = self.execute(
            "INSERT INTO activity(start_ts, end_ts, process, title, category, task_id) "
            "VALUES(?, ?, ?, ?, ?, ?)",
            (start, end, process, title, category.value, task_id),
        )
        return int(cur.lastrowid)

    def extend_activity(self, activity_id: int, end: float) -> None:
        self.execute("UPDATE activity SET end_ts = ? WHERE id = ?", (end, activity_id))

    def activity_between(self, start: float, end: float) -> list[sqlite3.Row]:
        return self.query(
            "SELECT * FROM activity WHERE end_ts > ? AND start_ts < ? ORDER BY start_ts",
            (start, end),
        )

    def task_minutes(self, task_id: int) -> float:
        row = self.query(
            "SELECT COALESCE(SUM(end_ts - start_ts), 0) AS s FROM activity "
            "WHERE task_id = ? AND category != 'idle'",
            (task_id,),
        )
        return float(row[0]["s"]) / 60.0

    def reassign_activity(self, activity_ids: Iterable[int], task_id: int | None) -> None:
        ids = list(activity_ids)
        if not ids:
            return
        marks = ", ".join("?" for _ in ids)
        self.execute(f"UPDATE activity SET task_id = ? WHERE id IN ({marks})", [task_id, *ids])

    def purge_activity_before(self, ts: float) -> None:
        self.execute("DELETE FROM activity WHERE end_ts < ?", (ts,))

    # ------------------------------------------------------------------ plans
    def set_plan(self, day: str, entries: list[tuple[int, float]], available: float,
                 committed_at: float | None = None) -> None:
        committed_at = committed_at if committed_at is not None else time.time()
        with self.transaction():
            self.execute("DELETE FROM plans WHERE date = ?", (day,))
            for pos, (task_id, minutes) in enumerate(entries):
                self.execute(
                    "INSERT INTO plans(date, task_id, position, planned_minutes, "
                    "available_minutes, committed_at) VALUES(?, ?, ?, ?, ?, ?)",
                    (day, task_id, pos, minutes, available, committed_at),
                )

    def get_plan(self, day: str) -> list[sqlite3.Row]:
        return self.query("SELECT * FROM plans WHERE date = ? ORDER BY position", (day,))

    def plan_days(self) -> list[str]:
        return [r["date"] for r in self.query("SELECT DISTINCT date FROM plans ORDER BY date")]

    # ------------------------------------------------------------------- days
    def save_day(self, day: str, data: dict[str, Any], finalized: bool) -> None:
        self.execute(
            "INSERT INTO days(date, finalized, data) VALUES(?, ?, ?) "
            "ON CONFLICT(date) DO UPDATE SET finalized = excluded.finalized, data = excluded.data",
            (day, int(finalized), json.dumps(data)),
        )

    def get_day(self, day: str) -> tuple[dict[str, Any], bool] | None:
        rows = self.query("SELECT * FROM days WHERE date = ?", (day,))
        if not rows:
            return None
        return json.loads(rows[0]["data"]), bool(rows[0]["finalized"])

    def finalized_days(self, limit: int | None = None) -> list[tuple[str, dict[str, Any]]]:
        sql = "SELECT date, data FROM days WHERE finalized = 1 ORDER BY date DESC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return [(r["date"], json.loads(r["data"])) for r in self.query(sql)]

    def first_activity_ts(self) -> float | None:
        row = self.query("SELECT MIN(start_ts) AS s FROM activity")
        row2 = self.query("SELECT MIN(ts) AS s FROM progress_events")
        vals = [v for v in (row[0]["s"], row2[0]["s"]) if v is not None]
        return min(vals) if vals else None

    # --------------------------------------------------------------------- xp
    def add_xp(self, amount: int, reason: str, ref: str | None = None, ts: float | None = None) -> None:
        if amount == 0:
            return
        self.execute(
            "INSERT INTO xp_log(ts, amount, reason, ref) VALUES(?, ?, ?, ?)",
            (ts or time.time(), int(amount), reason, ref),
        )

    def total_xp(self) -> int:
        return int(self.query("SELECT COALESCE(SUM(amount), 0) AS s FROM xp_log")[0]["s"])

    def xp_between(self, start: float, end: float) -> int:
        return int(
            self.query(
                "SELECT COALESCE(SUM(amount), 0) AS s FROM xp_log WHERE ts >= ? AND ts < ?",
                (start, end),
            )[0]["s"]
        )

    def recent_xp(self, limit: int = 20) -> list[sqlite3.Row]:
        return self.query("SELECT * FROM xp_log ORDER BY ts DESC, id DESC LIMIT ?", (limit,))

    def has_xp_ref(self, ref: str) -> bool:
        return bool(self.query("SELECT 1 FROM xp_log WHERE ref = ? LIMIT 1", (ref,)))

    # ----------------------------------------------------------- achievements
    def unlock(self, key: str, ts: float | None = None) -> bool:
        cur = self.execute(
            "INSERT OR IGNORE INTO achievements(key, unlocked_at) VALUES(?, ?)",
            (key, ts or time.time()),
        )
        return cur.rowcount > 0

    def unlocked(self) -> dict[str, float]:
        return {r["key"]: r["unlocked_at"] for r in self.query("SELECT * FROM achievements")}

    # ----------------------------------------------------------------- export
    def export_all(self) -> dict[str, list[dict[str, Any]]]:
        out: dict[str, list[dict[str, Any]]] = {}
        for table in ("tasks", "milestones", "progress_events", "activity", "plans", "days",
                      "xp_log", "achievements", "settings"):
            out[table] = [dict(r) for r in self.query(f"SELECT * FROM {table}")]
        return out


class _Transaction:
    def __init__(self, db: Database):
        self.db = db
        self.outer = False

    def __enter__(self) -> _Transaction:
        self.db._lock.acquire()
        self.outer = not self.db.conn.in_transaction
        if self.outer:
            self.db.conn.execute("BEGIN")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if self.outer:
                self.db.conn.execute("ROLLBACK" if exc_type else "COMMIT")
        finally:
            self.db._lock.release()


def _split_sql(script: str) -> list[str]:
    return [s.strip() for s in script.split(";") if s.strip()]
