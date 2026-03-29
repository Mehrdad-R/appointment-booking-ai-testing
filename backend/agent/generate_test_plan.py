import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
MAPPING_FILE = BASE_DIR / "test_mapping.json"
INPUT_FILE = BASE_DIR / "changed_files.json"
OUTPUT_FILE = BASE_DIR / "test_plan.json"


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


def build_test_plan(changed_files, mapping):
    risk_level = "low"
    selected_groups = []
    priority_tests = []
    reasons = []
    matched_files = []

    for changed_file in changed_files:
        if changed_file in mapping:
            matched_files.append(changed_file)
            rule = mapping[changed_file]

            risk_level = combine_risk(risk_level, rule["risk"])
            selected_groups.extend(rule["groups"])
            priority_tests.extend(rule["priority_tests"])
            reasons.append(f"{changed_file}: {rule['reason']}")

    if not matched_files:
        return {
            "risk_level": "medium",
            "selected_groups": ["smoke"],
            "priority_tests": [
                "test_create_appointment_success",
                "test_list_appointments_returns_items"
            ],
            "changed_files": changed_files,
            "matched_files": [],
            "reason": "No specific mapping matched; defaulting to smoke coverage."
        }

    return {
        "risk_level": risk_level,
        "selected_groups": deduplicate_preserve_order(selected_groups),
        "priority_tests": deduplicate_preserve_order(priority_tests),
        "changed_files": changed_files,
        "matched_files": matched_files,
        "reason": " | ".join(reasons)
    }


def main():
    mapping = load_json_file(MAPPING_FILE)
    changed_files = load_json_file(INPUT_FILE)

    test_plan = build_test_plan(changed_files, mapping)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(test_plan, f, indent=2)

    print("Generated test_plan.json successfully.")
    print(json.dumps(test_plan, indent=2))


if __name__ == "__main__":
    main()