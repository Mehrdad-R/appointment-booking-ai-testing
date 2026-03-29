import json
import xml.etree.ElementTree as ET
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
REPORT_FILE = Path("agent-report.xml")
OUTPUT_FILE = BASE_DIR / "history_runtime.json"


def load_existing_history():
    if OUTPUT_FILE.exists():
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    return {
        "recent_failures": [],
        "slow_tests": [],
        "high_risk_modules": [],
        "failure_counts": {},
        "avg_runtime_seconds": {},
        "runtime_totals": {},
        "run_counts": {}
    }


def iter_testcases(root):
    if root.tag == "testsuite":
        for testcase in root.findall("testcase"):
            yield testcase
    else:
        for testcase in root.findall(".//testcase"):
            yield testcase


def infer_module_from_test_name(test_name: str):
    keywords_for_backend = [
        "appointment",
        "overlap",
        "reschedule",
        "cancel",
        "invalid_time"
    ]

    if any(keyword in test_name for keyword in keywords_for_backend):
        return "backend/app.py"

    return None


def deduplicate_failures(failures):
    seen = set()
    result = []

    for item in failures:
        key = item.get("test_name")
        if key not in seen:
            seen.add(key)
            result.append(item)

    return result[:10]


def recompute_slow_tests(avg_runtime_seconds):
    slow_tests = []

    for test_name, runtime in avg_runtime_seconds.items():
        if runtime >= 1.0:
            level = "high"
        elif runtime >= 0.2:
            level = "medium"
        else:
            continue

        slow_tests.append({
            "test_name": test_name,
            "estimated_runtime": level
        })

    return slow_tests[:10]


def update_history():
    if not REPORT_FILE.exists():
        raise FileNotFoundError("agent-report.xml not found in workspace root.")

    history = load_existing_history()

    tree = ET.parse(REPORT_FILE)
    root = tree.getroot()

    for testcase in iter_testcases(root):
        test_name = testcase.attrib.get("name", "unknown_test")
        runtime = float(testcase.attrib.get("time", "0") or 0)

        history["runtime_totals"][test_name] = history["runtime_totals"].get(test_name, 0.0) + runtime
        history["run_counts"][test_name] = history["run_counts"].get(test_name, 0) + 1
        history["avg_runtime_seconds"][test_name] = round(
            history["runtime_totals"][test_name] / history["run_counts"][test_name],
            4
        )

        failure_node = testcase.find("failure")
        error_node = testcase.find("error")
        problem_node = failure_node if failure_node is not None else error_node

        if problem_node is not None:
            message = problem_node.attrib.get("message", "Recent Jenkins failure.")
            history["recent_failures"].insert(0, {
                "test_name": test_name,
                "failure_reason": message[:160]
            })

            history["failure_counts"][test_name] = history["failure_counts"].get(test_name, 0) + 1

            inferred_module = infer_module_from_test_name(test_name)
            if inferred_module and inferred_module not in history["high_risk_modules"]:
                history["high_risk_modules"].append(inferred_module)

    history["recent_failures"] = deduplicate_failures(history["recent_failures"])
    history["slow_tests"] = recompute_slow_tests(history["avg_runtime_seconds"])

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)

    print("Updated history_runtime.json successfully.")
    print(json.dumps(history, indent=2))


if __name__ == "__main__":
    update_history()