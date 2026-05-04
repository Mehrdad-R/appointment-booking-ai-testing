from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from urllib.parse import urlparse, unquote


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_SQLITE_PATH = BASE_DIR.parent / "appointments.db"


def get_database_url() -> str:
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return database_url

    sqlite_path = os.getenv("APP_DB_PATH", str(DEFAULT_SQLITE_PATH))
    return f"sqlite:///{sqlite_path}"


def get_database_engine() -> str:
    url = get_database_url()

    if url.startswith("sqlite:///"):
        return "sqlite"

    if url.startswith("postgresql://") or url.startswith("postgres://"):
        return "postgres"

    raise RuntimeError(f"Unsupported DATABASE_URL format: {url}")


def _sqlite_path_from_url(url: str) -> str:
    parsed = urlparse(url)
    path = unquote(parsed.path)

    # Fix Windows paths like /C:/Users/...
    if os.name == "nt" and path.startswith("/") and len(path) > 3 and path[2] == ":":
        path = path[1:]

    return path


def _convert_qmark_to_postgres(query: str) -> str:
    return query.replace("?", "%s")


class CursorWrapper:
    def __init__(self, engine: str, cursor):
        self.engine = engine
        self._cursor = cursor

    def execute(self, query: str, params=None):
        if params is None:
            params = ()

        if self.engine == "postgres":
            query = _convert_qmark_to_postgres(query)

        self._cursor.execute(query, params)
        return self

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()


class ConnectionWrapper:
    def __init__(self, engine: str, connection):
        self.engine = engine
        self._connection = connection

    def cursor(self):
        return CursorWrapper(self.engine, self._connection.cursor())

    def commit(self):
        self._connection.commit()

    def close(self):
        self._connection.close()


def get_connection():
    engine = get_database_engine()
    url = get_database_url()

    if engine == "sqlite":
        sqlite_path = _sqlite_path_from_url(url)
        conn = sqlite3.connect(sqlite_path)
        conn.row_factory = sqlite3.Row
        return ConnectionWrapper("sqlite", conn)

    if engine == "postgres":
        try:
            from psycopg import connect
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError(
                "Postgres support requires psycopg. Install it with: pip install psycopg[binary]"
            ) from exc

        conn = connect(url, row_factory=dict_row)
        return ConnectionWrapper("postgres", conn)

    raise RuntimeError(f"Unsupported database engine: {engine}")


def column_exists(table_name: str, column_name: str) -> bool:
    engine = get_database_engine()
    conn = get_connection()
    cursor = conn.cursor()

    try:
        if engine == "sqlite":
            rows = cursor.execute(f"PRAGMA table_info({table_name})").fetchall()
            return any(row["name"] == column_name for row in rows)

        row = cursor.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = ?
              AND column_name = ?
            LIMIT 1
            """,
            (table_name, column_name)
        ).fetchone()

        return row is not None
    finally:
        conn.close()


def initialize_schema():
    engine = get_database_engine()
    conn = get_connection()
    cursor = conn.cursor()

    try:
        if engine == "sqlite":
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS appointments (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    "start" TEXT NOT NULL,
                    "end" TEXT NOT NULL,
                    status TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS agent_build_runs (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    decision_source TEXT,
                    risk_level TEXT,
                    selected_groups_json TEXT,
                    reason TEXT,
                    summary_text TEXT
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS agent_build_changed_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    build_run_id TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    FOREIGN KEY (build_run_id) REFERENCES agent_build_runs(id)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS agent_build_priority_tests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    build_run_id TEXT NOT NULL,
                    test_name TEXT NOT NULL,
                    FOREIGN KEY (build_run_id) REFERENCES agent_build_runs(id)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS agent_recent_failures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    build_run_id TEXT NOT NULL,
                    test_name TEXT NOT NULL,
                    failure_reason TEXT,
                    module_name TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (build_run_id) REFERENCES agent_build_runs(id)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS agent_slow_tests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    build_run_id TEXT NOT NULL,
                    test_name TEXT NOT NULL,
                    estimated_runtime TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (build_run_id) REFERENCES agent_build_runs(id)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS agent_high_risk_modules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    build_run_id TEXT NOT NULL,
                    module_name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (build_run_id) REFERENCES agent_build_runs(id)
                )
            """)

        elif engine == "postgres":
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS appointments (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    "start" TEXT NOT NULL,
                    "end" TEXT NOT NULL,
                    status TEXT NOT NULL,
                    customer_id TEXT
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id),
                    created_at TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS agent_build_runs (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    decision_source TEXT,
                    risk_level TEXT,
                    selected_groups_json TEXT,
                    reason TEXT,
                    summary_text TEXT
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS agent_build_changed_files (
                    id BIGSERIAL PRIMARY KEY,
                    build_run_id TEXT NOT NULL REFERENCES agent_build_runs(id),
                    file_path TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS agent_build_priority_tests (
                    id BIGSERIAL PRIMARY KEY,
                    build_run_id TEXT NOT NULL REFERENCES agent_build_runs(id),
                    test_name TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS agent_recent_failures (
                    id BIGSERIAL PRIMARY KEY,
                    build_run_id TEXT NOT NULL REFERENCES agent_build_runs(id),
                    test_name TEXT NOT NULL,
                    failure_reason TEXT,
                    module_name TEXT,
                    created_at TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS agent_slow_tests (
                    id BIGSERIAL PRIMARY KEY,
                    build_run_id TEXT NOT NULL REFERENCES agent_build_runs(id),
                    test_name TEXT NOT NULL,
                    estimated_runtime TEXT,
                    created_at TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS agent_high_risk_modules (
                    id BIGSERIAL PRIMARY KEY,
                    build_run_id TEXT NOT NULL REFERENCES agent_build_runs(id),
                    module_name TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)

        conn.commit()

        if not column_exists("appointments", "customer_id"):
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("ALTER TABLE appointments ADD COLUMN customer_id TEXT")
            conn.commit()

    finally:
        conn.close()