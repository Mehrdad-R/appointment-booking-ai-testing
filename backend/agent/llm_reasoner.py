import json
import os
import urllib.request
import urllib.error
from pathlib import Path

from tools.context_tools import load_optional_json, merge_history_sources, load_runtime_history_from_db


BASE_DIR = Path(__file__).resolve().parent
HISTORY_SEED_FILE = BASE_DIR / "history_summary.json"


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


def load_history_summary():
    runtime = load_runtime_history_from_db()
    if runtime:
        return runtime

    seed = load_optional_json(HISTORY_SEED_FILE)
    return seed


def build_llm_prompt(changed_files, mapping, history_summary):
    return f"""
You are an AI regression test orchestration agent for a CI pipeline.

Your job is to produce a JSON test plan for Jenkins.

You are given:
1. The list of files changed in the current commit
2. A project-specific mapping of files to risk levels, test groups, and important tests
3. Retrieved CI/test history from previous builds stored in the database

Instructions:
- Think about which files are most important
- Use the retrieved history to adjust your risk judgment
- Prefer smoke tests for low-risk frontend or styling-only changes
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

Retrieved CI/test history from database:
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