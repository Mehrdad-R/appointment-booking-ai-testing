import json
import sqlite3
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DB_FILE = PROJECT_ROOT / "appointments.db"


def load_json_file(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_mapping(mapping_file: Path):
    return load_json_file(mapping_file)


def load_changed_files(input_file: Path):
    return load_json_file(input_file)


def load_optional_json(path: Path):
    if not path.exists():
        return {}
    return load_json_file(path)


def merge_history_sources(seed, runtime):
    combined_recent_failures = []
    seen_failures = set()

    for item in runtime.get("recent_failures", []) + seed.get("recent_failures", []):
        test_name = item.get("test_name")
        if test_name not in seen_failures:
            seen_failures.add(test_name)
            combined_recent_failures.append(item)

    combined_slow_tests = []
    seen_slow = set()

    for item in runtime.get("slow_tests", []) + seed.get("slow_tests", []):
        test_name = item.get("test_name")
        if test_name not in seen_slow:
            seen_slow.add(test_name)
            combined_slow_tests.append(item)

    combined_high_risk_modules = []
    for module in runtime.get("high_risk_modules", []) + seed.get("high_risk_modules", []):
        if module not in combined_high_risk_modules:
            combined_high_risk_modules.append(module)

    combined_failure_counts = {}
    for source in [seed.get("failure_counts", {}), runtime.get("failure_counts", {})]:
        for test_name, count in source.items():
            combined_failure_counts[test_name] = combined_failure_counts.get(test_name, 0) + count

    combined_avg_runtime = {}
    combined_avg_runtime.update(seed.get("avg_runtime_seconds", {}))
    combined_avg_runtime.update(runtime.get("avg_runtime_seconds", {}))

    return {
        "recent_failures": combined_recent_failures[:10],
        "slow_tests": combined_slow_tests[:10],
        "high_risk_modules": combined_high_risk_modules,
        "failure_counts": combined_failure_counts,
        "avg_runtime_seconds": combined_avg_runtime
    }


def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def load_runtime_history_from_db():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        latest_run = cursor.execute(
            """
            SELECT id
            FROM agent_build_runs
            ORDER BY created_at DESC
            LIMIT 1
            """
        ).fetchone()

        if latest_run is None:
            conn.close()
            return {}

        build_run_id = latest_run["id"]

        recent_failures_rows = cursor.execute(
            """
            SELECT test_name, failure_reason, module_name
            FROM agent_recent_failures
            WHERE build_run_id = ?
            ORDER BY id DESC
            """,
            (build_run_id,)
        ).fetchall()

        slow_tests_rows = cursor.execute(
            """
            SELECT test_name, estimated_runtime
            FROM agent_slow_tests
            WHERE build_run_id = ?
            ORDER BY id DESC
            """,
            (build_run_id,)
        ).fetchall()

        high_risk_rows = cursor.execute(
            """
            SELECT module_name
            FROM agent_high_risk_modules
            WHERE build_run_id = ?
            ORDER BY id DESC
            """,
            (build_run_id,)
        ).fetchall()

        build_run_rows = cursor.execute(
            """
            SELECT risk_level, selected_groups_json
            FROM agent_build_runs
            ORDER BY created_at DESC
            LIMIT 10
            """
        ).fetchall()

        priority_test_rows = cursor.execute(
            """
            SELECT test_name, COUNT(*) as usage_count
            FROM agent_build_priority_tests
            GROUP BY test_name
            ORDER BY usage_count DESC
            LIMIT 10
            """
        ).fetchall()

        conn.close()

        risk_counts = {"low": 0, "medium": 0, "high": 0}
        selected_group_frequency = {}

        for row in build_run_rows:
            risk_level = row["risk_level"]
            if risk_level in risk_counts:
                risk_counts[risk_level] += 1

            groups = json.loads(row["selected_groups_json"] or "[]")
            for group in groups:
                selected_group_frequency[group] = selected_group_frequency.get(group, 0) + 1

        debug_payload = {
            "recent_failures": [
                {
                    "test_name": row["test_name"],
                    "failure_reason": row["failure_reason"],
                    "module": row["module_name"]
                }
                for row in recent_failures_rows
            ],
            "slow_tests": [
                {
                    "test_name": row["test_name"],
                    "estimated_runtime": row["estimated_runtime"]
                }
                for row in slow_tests_rows
            ],
            "high_risk_modules": [row["module_name"] for row in high_risk_rows],
            "recent_risk_distribution": risk_counts,
            "priority_test_frequency": {
                row["test_name"]: row["usage_count"] for row in priority_test_rows
            },
            "selected_group_frequency": selected_group_frequency
        }

        print("DEBUG: Retrieved runtime history from SQLite:")
        print(json.dumps(debug_payload, indent=2))

        return debug_payload

    except sqlite3.OperationalError:
        return {}