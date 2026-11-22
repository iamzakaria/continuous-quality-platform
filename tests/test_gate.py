import json
import os
import time

import pytest

from quality_platform.gate import (
    EvidenceError,
    coverage_result,
    evaluate,
    junit_result,
    performance_result,
    read_file,
)


def write(tmp_path, content):
    path = tmp_path / "report.xml"
    path.write_text(content)
    return path


def test_passing_junit(tmp_path):
    path = write(
        tmp_path, '<testsuites><testsuite tests="1"><testcase name="ok"/></testsuite></testsuites>'
    )
    assert junit_result(path)["executed"] == 1


@pytest.mark.parametrize(
    "content",
    [
        "<testsuites/>",
        "<invalid/>",
        "<testsuite><testcase><failure/></testcase></testsuite>",
        "<testsuite><testcase><error/></testcase></testsuite>",
        "<testsuite><testcase><skipped/></testcase></testsuite>",
        '<testsuite errors="1"><testcase/></testsuite>',
    ],
)
def test_bad_or_empty_junit_fails(tmp_path, content):
    with pytest.raises(EvidenceError):
        junit_result(write(tmp_path, content))


def test_minimum_test_count(tmp_path):
    with pytest.raises(EvidenceError):
        junit_result(write(tmp_path, "<testsuite><testcase/></testsuite>"), min_tests=2)


def test_coverage_uses_counts_not_reported_rate(tmp_path):
    path = write(tmp_path, '<coverage lines-valid="100" lines-covered="50" line-rate="1.0"/>')
    with pytest.raises(EvidenceError):
        coverage_result(path, 70)
    assert coverage_result(path, 40)["line_coverage_percent"] == 50


@pytest.mark.parametrize(
    "content",
    [
        '<coverage lines-valid="0" lines-covered="0"/>',
        '<coverage lines-valid="1" lines-covered="2"/>',
        "<invalid/>",
    ],
)
def test_invalid_coverage(tmp_path, content):
    with pytest.raises(EvidenceError):
        coverage_result(write(tmp_path, content), 70)


def good_perf():
    return {
        "schema_version": "1.0",
        "passed": True,
        "requests": 50,
        "p95_ms": 12,
        "profile": "smoke",
        "thresholds": [
            {"metric": m, "passed": True}
            for m in ["http_req_failed", "http_req_duration", "checks", "iterations"]
        ],
    }


def test_performance_gate(tmp_path):
    path = write(tmp_path, json.dumps(good_perf()))
    assert performance_result(path)["requests"] == 50


@pytest.mark.parametrize("mutation", ["empty", "failed", "nan", "zero", "slow", "missing"])
def test_invalid_performance(tmp_path, mutation):
    data = good_perf()
    if mutation == "empty":
        data["thresholds"] = []
    if mutation == "failed":
        data["thresholds"][0]["passed"] = False
    if mutation == "nan":
        data["p95_ms"] = float("nan")
    if mutation == "zero":
        data["requests"] = 0
    if mutation == "slow":
        data["p95_ms"] = 500
    if mutation == "missing":
        data.pop("passed")
    with pytest.raises(EvidenceError):
        performance_result(write(tmp_path, json.dumps(data)))


def test_missing_stale_and_escape_fail(tmp_path):
    with pytest.raises(EvidenceError):
        read_file(tmp_path, "missing.xml", 60)
    with pytest.raises(EvidenceError):
        read_file(tmp_path, "../outside.xml", 60)
    path = write(tmp_path, "report")
    os.utime(path, (time.time() - 100, time.time() - 100))
    with pytest.raises(EvidenceError):
        read_file(tmp_path, path.name, 60)


def test_mixed_evidence_fails_closed(tmp_path):
    path = write(tmp_path, "<testsuite><testcase/></testsuite>")
    policy = {
        "checks": [
            {"name": "pass", "kind": "junit", "path": path.name},
            {"name": "missing", "kind": "junit", "path": "missing.xml"},
        ]
    }
    result = evaluate(tmp_path, policy)
    assert result["passed"] is False
    assert [r["passed"] for r in result["checks"]] == [True, False]


def test_invalid_xml_and_unknown_kind_fail_closed(tmp_path):
    path = write(tmp_path, "<broken")
    for kind in ["junit", "unexpected"]:
        assert (
            evaluate(tmp_path, {"checks": [{"name": "bad", "kind": kind, "path": path.name}]})[
                "passed"
            ]
            is False
        )


def test_empty_policy_rejected(tmp_path):
    with pytest.raises(EvidenceError):
        evaluate(tmp_path, {"checks": []})


def test_orchestrator_preserves_virtualenv_interpreter_symlink(tmp_path):
    from quality_platform.run import python_interpreter

    system = tmp_path / "system-python"
    system.touch()
    venv = tmp_path / "venv-python"
    venv.symlink_to(system)
    assert python_interpreter(tmp_path, venv) == venv.absolute()
    assert python_interpreter(tmp_path, venv) != system
    assert python_interpreter(tmp_path, None) == tmp_path / ".venv/bin/python"
