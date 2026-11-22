"""Fail-closed evidence gate. Never infer a pass from missing/empty reports."""

import argparse
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

from defusedxml import ElementTree


class EvidenceError(ValueError):
    pass


def read_file(root: Path, relative: str, max_age: float) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise EvidenceError("Evidence path escapes workspace")
    if not path.is_file():
        raise EvidenceError(f"Missing evidence: {relative}")
    age = time.time() - path.stat().st_mtime
    if age > max_age or age < -60:
        raise EvidenceError(f"Evidence timestamp outside accepted window: {relative}")
    return path


def junit_result(path: Path, min_tests: int = 1, max_skipped: int = 0):
    root = ElementTree.parse(path).getroot()
    if root.tag not in {"testsuite", "testsuites"}:
        raise EvidenceError("Invalid JUnit root")
    cases = list(root.iter("testcase"))
    failures = sum(len(list(root.iter(tag))) for tag in ("failure", "error"))
    skipped = sum(case.find("skipped") is not None for case in cases)
    executed = len(cases) - skipped
    # Some producers report suite-level errors without testcase children.
    declared_errors = sum(
        int(suite.get("errors", "0")) + int(suite.get("failures", "0"))
        for suite in root.iter("testsuite")
    )
    if executed < min_tests or failures or declared_errors or skipped > max_skipped:
        raise EvidenceError(
            f"JUnit gate failed: executed={executed}, failures={max(failures, declared_errors)}, "
            f"skipped={skipped}"
        )
    return {"executed": executed, "skipped": skipped, "failures": 0}


def coverage_result(path: Path, minimum: float):
    root = ElementTree.parse(path).getroot()
    if root.tag != "coverage":
        raise EvidenceError("Invalid coverage root")
    valid = int(root.attrib["lines-valid"])
    covered = int(root.attrib["lines-covered"])
    if valid <= 0 or not 0 <= covered <= valid:
        raise EvidenceError("Invalid or empty coverage report")
    percentage = covered / valid * 100
    if percentage < minimum:
        raise EvidenceError(f"Coverage {percentage:.2f}% is below {minimum}%")
    return {"line_coverage_percent": round(percentage, 2)}


def performance_result(path: Path):
    data = json.loads(path.read_text())
    required = {"http_req_failed", "http_req_duration", "checks", "iterations"}
    thresholds = data.get("thresholds", [])
    if (
        data.get("schema_version") != "1.0"
        or data.get("passed") is not True
        or not required.issubset({t["metric"] for t in thresholds})
        or not all(t.get("passed") is True for t in thresholds)
    ):
        raise EvidenceError("Performance thresholds missing or failing")
    requests, p95 = data.get("requests"), data.get("p95_ms")
    if (
        not isinstance(requests, (float, int))
        or isinstance(requests, bool)
        or requests <= 0
        or not isinstance(p95, (float, int))
        or isinstance(p95, bool)
        or not math.isfinite(p95)
        or not 0 <= p95 < 500
    ):
        raise EvidenceError("Invalid performance samples or p95 exceeds 500ms")
    return {"requests": requests, "p95_ms": p95, "profile": data.get("profile")}


def evaluate(workspace: Path, policy: dict, max_age: float = 3600):
    if max_age <= 0 or not policy.get("checks"):
        raise EvidenceError("Policy must include checks and a positive evidence age limit")
    results = []
    for check in policy["checks"]:
        try:
            path = read_file(workspace, check["path"], max_age)
            if check["kind"] == "junit":
                detail = junit_result(path, check.get("min_tests", 1), check.get("max_skipped", 0))
            elif check["kind"] == "coverage":
                detail = coverage_result(path, check["minimum"])
            elif check["kind"] == "performance":
                detail = performance_result(path)
            else:
                raise EvidenceError("Unknown evidence kind")
            results.append({"name": check["name"], "passed": True, **detail})
        except Exception as exc:
            # Invalid/unreadable reports are failures, never skipped gate conditions.
            results.append(
                {
                    "name": check.get("name", "unnamed"),
                    "passed": False,
                    "reason": f"{type(exc).__name__}: {exc}",
                }
            )
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "passed": all(r["passed"] for r in results),
        "checks": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--policy", type=Path, default=Path("quality-policy.json"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/quality-summary.json"))
    parser.add_argument("--max-age", type=float, default=3600)
    args = parser.parse_args()
    try:
        result = evaluate(args.workspace, json.loads(args.policy.read_text()), args.max_age)
    except (ValueError, OSError) as exc:
        result = {"passed": False, "reason": str(exc), "checks": []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
