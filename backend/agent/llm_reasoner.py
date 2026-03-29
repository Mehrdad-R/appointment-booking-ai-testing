import json
import os
import urllib.request
import urllib.error
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
HISTORY_SEED_FILE = BASE_DIR / "history_summary.json"
HISTORY_RUNTIME_FILE = BASE_DIR / "history_runtime.json"


def strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            lines = lines[1:]
            if lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
    return text


def load_json_if_exists(path: Path):
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def deduplicate_dict_list(items, key_field):
    seen = set()
    result = []

    for item in items:
        key = item.get(key_field)
        if key not in seen:
            seen.add(key)
            result.append(item)

    return result


def merge_history_sources(seed, runtime):
    combined_recent_failures = deduplicate_dict_list(
        runtime.get("recent_failures", []) + seed.get("recent_failures", []),
        "test_name"
    )

    combined_slow_tests = deduplicate_dict_list(
        runtime.get("slow_tests", []) + seed.get("slow_tests", []),
        "test_name"
    )

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


def load_history_summary():
    seed = load_json_if_exists(HISTORY_SEED_FILE)
    runtime = load_json_if_exists(HISTORY_RUNTIME_FILE)
    return merge_history_sources(seed, runtime)


def build_llm_prompt(changed_files, mapping, history_summary):
    return f"""
You are an AI regression test orchestration agent for a CI pipeline.

Your job is to produce a JSON test plan for Jenkins.

You are given:
1. The list of files changed in the current commit
2. A project-specific mapping of files to risk levels, test groups, and important tests
3. Retrieved CI/test history from previous builds

Instructions:
- Think about which files are most important
- Use the retrieved history to adjust your risk judgment
- Prefer smoke tests for low-risk frontend/styling-only changes
- Prefer smoke + regression for backend, agent, or core test changes
- If changed files overlap with previously high-risk or failure-prone areas, increase confidence in running regression
- Return ONLY valid JSON
- Do not wrap the JSON in markdown
- Keep the output concise and machine-readable

Required JSON schema:
{{
  "risk_level": "low | medium | high",
  "selected_groups": ["smoke", "regression"],
  "priority_tests": ["test_name_1", "test_name_2"],
  "reason": "short explanation"
}}

Changed files:
{json.dumps(changed_files, indent=2)}

Project mapping:
{json.dumps(mapping, indent=2)}

Retrieved CI/test history:
{json.dumps(history_summary, indent=2)}
""".strip()


def extract_gemini_text(response_json: dict) -> str:
    candidates = response_json.get("candidates", [])
    if not candidates:
        raise RuntimeError(f"No candidates returned by Gemini: {json.dumps(response_json, indent=2)}")

    parts = candidates[0].get("content", {}).get("parts", [])
    text_chunks = [part.get("text", "") for part in parts if "text" in part]
    text = "\n".join(text_chunks).strip()

    if not text:
        raise RuntimeError(f"No text found in Gemini response: {json.dumps(response_json, indent=2)}")

    return text


def call_gemini_for_test_plan(changed_files, mapping):
    api_key = os.getenv("GEMINI_API_KEY")
    model = os.getenv("GEMINI_MODEL")

    if not api_key or not model:
        raise RuntimeError("GEMINI_API_KEY and GEMINI_MODEL must be set for Gemini reasoning.")

    history_summary = load_history_summary()
    prompt = build_llm_prompt(changed_files, mapping, history_summary)

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    payload = {
        "system_instruction": {
            "parts": [
                {
                    "text": "Return only valid JSON. Do not include markdown or extra commentary."
                }
            ]
        },
        "contents": [
            {
                "parts": [
                    {
                        "text": prompt
                    }
                ]
            }
        ]
    }

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "x-goog-api-key": api_key,
            "Content-Type": "application/json"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(request) as response:
            response_json = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Gemini API HTTP error {e.code}: {error_body}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Gemini API connection error: {e}")

    raw_text = extract_gemini_text(response_json)
    cleaned_text = strip_code_fences(raw_text)

    try:
        return json.loads(cleaned_text)
    except json.JSONDecodeError:
        raise RuntimeError(f"Gemini returned non-JSON output:\n{cleaned_text}")