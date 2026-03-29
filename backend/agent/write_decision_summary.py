import json
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
TEST_PLAN_FILE = BASE_DIR / "test_plan.json"
OUTPUT_FILE = BASE_DIR / "agent_decision_summary.md"


def load_test_plan():
    with open(TEST_PLAN_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def write_summary(plan):
    summary = f"""# AI Agent Decision Summary

## Decision Source
{plan.get("decision_source", "unknown")}

## Risk Level
{plan.get("risk_level", "unknown")}

## Selected Test Groups
{", ".join(plan.get("selected_groups", [])) or "None"}

## Priority Tests
"""
    priority_tests = plan.get("priority_tests", [])
    if priority_tests:
        for test_name in priority_tests:
            summary += f"- {test_name}\n"
    else:
        summary += "- None\n"

    summary += f"""
## Changed Files
"""
    changed_files = plan.get("changed_files", [])
    if changed_files:
        for file_name in changed_files:
            summary += f"- {file_name}\n"
    else:
        summary += "- None\n"

    summary += f"""
## Filtered Files Used by Agent
"""
    filtered_files = plan.get("filtered_files", [])
    if filtered_files:
        for file_name in filtered_files:
            summary += f"- {file_name}\n"
    else:
        summary += "- None\n"

    summary += f"""
## Reasoning
{plan.get("reason", "No reason provided.")}
"""

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(summary)

    print("Generated agent_decision_summary.md successfully.")
    print(summary)


if __name__ == "__main__":
    test_plan = load_test_plan()
    write_summary(test_plan)