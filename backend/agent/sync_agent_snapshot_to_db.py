import json
import sqlite3
from datetime import datetime
from pathlib import Path
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[2]
AGENT_DIR = PROJECT_ROOT / "backend" / "agent"
DB_FILE = PROJECT_ROOT / "appointments.db"

PLAN_FILE = AGENT_DIR / "test_plan.json"
SUMMARY_FILE = AGENT_DIR / "agent_decision_summary.md"
HISTORY_FILE = AGENT_DIR / "history_runtime.json"


def load_json_if_exists(path: Path):
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_text_if_exists(path: Path):
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def get_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_agent_tables(conn):
    cursor = conn.cursor()

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

    conn.commit()


def save_agent_snapshot_to_db(plan: dict, summary: str | None, history: dict | None):
    conn = get_connection()
    ensure_agent_tables(conn)
    cursor = conn.cursor()

    build_run_id = str(uuid4())
    created_at = datetime.utcnow().isoformat()

    cursor.execute(
        """
        INSERT INTO agent_build_runs (
            id, created_at, decision_source, risk_level,
            selected_groups_json, reason, summary_text
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            build_run_id,
            created_at,
            plan.get("decision_source"),
            plan.get("risk_level"),
            json.dumps(plan.get("selected_groups", [])),
            plan.get("reason"),
            summary
        )
    )

    for file_path in plan.get("changed_files", []):
        cursor.execute(
            """
            INSERT INTO agent_build_changed_files (build_run_id, file_path)
            VALUES (?, ?)
            """,
            (build_run_id, file_path)
        )

    for test_name in plan.get("priority_tests", []):
        cursor.execute(
            """
            INSERT INTO agent_build_priority_tests (build_run_id, test_name)
            VALUES (?, ?)
            """,
            (build_run_id, test_name)
        )

    if history:
        for item in history.get("recent_failures", []):
            cursor.execute(
                """
                INSERT INTO agent_recent_failures (
                    build_run_id, test_name, failure_reason, module_name, created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    build_run_id,
                    item.get("test_name"),
                    item.get("failure_reason"),
                    item.get("module"),
                    created_at
                )
            )

        for item in history.get("slow_tests", []):
            cursor.execute(
                """
                INSERT INTO agent_slow_tests (
                    build_run_id, test_name, estimated_runtime, created_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    build_run_id,
                    item.get("test_name"),
                    item.get("estimated_runtime"),
                    created_at
                )
            )

        for module_name in history.get("high_risk_modules", []):
            cursor.execute(
                """
                INSERT INTO agent_high_risk_modules (
                    build_run_id, module_name, created_at
                )
                VALUES (?, ?, ?)
                """,
                (
                    build_run_id,
                    module_name,
                    created_at
                )
            )

    conn.commit()
    conn.close()

    return build_run_id


def main():
    plan = load_json_if_exists(PLAN_FILE)
    history = load_json_if_exists(HISTORY_FILE)
    summary = load_text_if_exists(SUMMARY_FILE)

    if plan is None:
        raise FileNotFoundError("test_plan.json not found. Cannot sync agent snapshot.")

    build_run_id = save_agent_snapshot_to_db(plan, summary, history)

    print("Synced agent snapshot to database successfully.")
    print(json.dumps({
        "message": "agent snapshot saved to database",
        "build_run_id": build_run_id
    }, indent=2))


if __name__ == "__main__":
    main()