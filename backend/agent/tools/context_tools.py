import json
from pathlib import Path


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