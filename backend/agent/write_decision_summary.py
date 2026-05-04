import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AGENT_DIR = PROJECT_ROOT / "backend" / "agent"

PLAN_FILE = AGENT_DIR / "test_plan.json"
SUMMARY_FILE = AGENT_DIR / "agent_decision_summary.md"


def main():
    if not PLAN_FILE.exists():
        raise FileNotFoundError("test_plan.json not found")

    plan = json.loads(PLAN_FILE.read_text(encoding="utf-8"))

    decision_source = plan.get("decision_source", "unknown")
    risk_level = plan.get("risk_level", "unknown")
    selected_groups = ", ".join(plan.get("selected_groups", [])) or "None"
    changed_files = ", ".join(plan.get("changed_files", [])) or "None"
    priority_tests = plan.get("priority_tests", [])
    reason = plan.get("reason", "No reasoning available.")

    priority_tests_md = "\n".join(f"- {test}" for test in priority_tests) if priority_tests else "- None"

    summary = f"""# AI Agent Decision Summary

## Decision Source
{decision_source}

## Risk Level
{risk_level}

## Selected Test Groups
{selected_groups}

## Changed Files
{changed_files}

## Priority Tests
{priority_tests_md}

## Reasoning
{reason}
"""

    SUMMARY_FILE.write_text(summary, encoding="utf-8")
    print("Generated agent_decision_summary.md successfully.")


if __name__ == "__main__":
    main()