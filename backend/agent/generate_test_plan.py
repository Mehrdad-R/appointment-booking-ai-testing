import json
from pathlib import Path
import os

from llm_reasoner import call_gemini_for_test_plan
from tools.context_tools import load_changed_files, load_mapping

BASE_DIR = Path(__file__).resolve().parent
MAPPING_FILE = BASE_DIR / "test_mapping.json"
INPUT_FILE = BASE_DIR / "changed_files.json"
OUTPUT_FILE = BASE_DIR / "test_plan.json"

IGNORED_PATTERNS = [
    "venv/",
    ".venv/",
    "__pycache__/",
    ".pytest_cache/",
    "appointments.db",
    "backend/appointments.db",
    "backend/agent/changed_files.json",
    "backend/agent/test_plan.json"
]


def load_json_file(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def deduplicate_preserve_order(items):
    seen = set()
    result = []

    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)

    return result


def combine_risk(current_risk: str, new_risk: str) -> str:
    order = {"low": 1, "medium": 2, "high": 3}
    return new_risk if order[new_risk] > order[current_risk] else current_risk


def should_ignore_file(file_path: str) -> bool:
    normalized = file_path.replace("\\", "/")

    for pattern in IGNORED_PATTERNS:
        if normalized == pattern or normalized.startswith(pattern):
            return True

    if normalized.endswith(".db") or normalized.endswith(".sqlite3"):
        return True

    return False


def filter_changed_files(changed_files):
    return [f for f in changed_files if f.strip() and not should_ignore_file(f)]


def build_rule_based_test_plan(changed_files, mapping):
    filtered_files = filter_changed_files(changed_files)

    risk_level = "low"
    selected_groups = []
    priority_tests = []
    reasons = []
    matched_files = []

    for changed_file in filtered_files:
        if changed_file in mapping:
            matched_files.append(changed_file)
            rule = mapping[changed_file]

            risk_level = combine_risk(risk_level, rule["risk"])
            selected_groups.extend(rule["groups"])
            priority_tests.extend(rule["priority_tests"])
            reasons.append(f"{changed_file}: {rule['reason']}")

    if not filtered_files:
        return {
            "decision_source": "rules",
            "risk_level": "low",
            "selected_groups": ["smoke"],
            "priority_tests": [
                "test_create_appointment_success"
            ],
            "changed_files": changed_files,
            "filtered_files": [],
            "matched_files": [],
            "reason": "Only ignored or runtime-generated files changed; minimal smoke coverage selected."
        }

    if not matched_files:
        return {
            "decision_source": "rules",
            "risk_level": "medium",
            "selected_groups": ["smoke"],
            "priority_tests": [
                "test_create_appointment_success",
                "test_list_appointments_returns_items"
            ],
            "changed_files": changed_files,
            "filtered_files": filtered_files,
            "matched_files": [],
            "reason": "No specific mapping matched; defaulting to smoke coverage."
        }

    return {
        "decision_source": "rules",
        "risk_level": risk_level,
        "selected_groups": deduplicate_preserve_order(selected_groups),
        "priority_tests": deduplicate_preserve_order(priority_tests),
        "changed_files": changed_files,
        "filtered_files": filtered_files,
        "matched_files": matched_files,
        "reason": " | ".join(reasons)
    }


def normalize_llm_plan(llm_plan, changed_files):
    return {
        "decision_source": "gemini",
        "risk_level": llm_plan.get("risk_level", "medium"),
        "selected_groups": deduplicate_preserve_order(llm_plan.get("selected_groups", ["smoke"])),
        "priority_tests": deduplicate_preserve_order(llm_plan.get("priority_tests", [])),
        "changed_files": changed_files,
        "filtered_files": filter_changed_files(changed_files),
        "matched_files": [],
        "reason": llm_plan.get("reason", "Gemini-generated test selection.")
    }


def main():
    mapping = load_mapping(MAPPING_FILE)
    changed_files = load_changed_files(INPUT_FILE)

    use_llm = bool(os.getenv("GEMINI_API_KEY")) and bool(os.getenv("GEMINI_MODEL"))

    if use_llm:
        try:
            llm_plan = call_gemini_for_test_plan(changed_files, mapping)
            test_plan = normalize_llm_plan(llm_plan, changed_files)
        except Exception as e:
            print(f"Gemini reasoning failed, falling back to rule-based plan. Error: {e}")
            test_plan = build_rule_based_test_plan(changed_files, mapping)
    else:
        test_plan = build_rule_based_test_plan(changed_files, mapping)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(test_plan, f, indent=2)

    print("Generated test_plan.json successfully.")
    print(json.dumps(test_plan, indent=2))


if __name__ == "__main__":
    main()