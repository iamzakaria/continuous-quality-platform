"""Run the five sibling repositories and gate newly generated evidence."""

import argparse
import json
import os
import secrets
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from quality_platform.gate import evaluate

PROJECTS = {
    "enterprise-test-automation": "enterprise_qa",
    "ai-test-case-generator": "ai_test_generator",
    "healthcare-qa-framework": "healthcare_qa",
    "continuous-quality-platform": "quality_platform",
}


def python_interpreter(root: Path, override: Path | None) -> Path:
    # Keep the venv executable path: resolving its symlink selects system Python.
    return override.absolute() if override else root / ".venv/bin/python"


def command(args, cwd, env=None):
    print(f"Running {args[0]} in {cwd.name}", flush=True)
    try:
        return subprocess.run(args, cwd=cwd, env=env, check=False, timeout=300).returncode
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"Command failed: {type(exc).__name__}", flush=True)
        return 1


def performance(workspace, python, k6):
    target = workspace / "healthcare-qa-framework"
    lab = workspace / "performance-engineering-lab"
    with tempfile.TemporaryDirectory(prefix="qe-perf-") as directory, socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        env = dict(
            os.environ,
            PYTHONPATH=str(target / "src"),
            DATABASE_PATH=str(Path(directory) / "synthetic.db"),
            CLINICIAN_TOKEN=secrets.token_urlsafe(24),
            AUDITOR_TOKEN=secrets.token_urlsafe(24),
        )
        log = (lab / "artifacts" / "target.log").open("w")
        try:
            process = subprocess.Popen(
                [
                    str(python),
                    "-m",
                    "uvicorn",
                    "healthcare_qa.app:create_app",
                    "--factory",
                    "--fd",
                    str(sock.fileno()),
                    "--no-access-log",
                ],
                cwd=target,
                env=env,
                pass_fds=(sock.fileno(),),
                stdout=log,
                stderr=log,
            )
            try:
                deadline = time.monotonic() + 15
                while True:
                    try:
                        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1):
                            break
                    except (urllib.error.URLError, TimeoutError):
                        if process.poll() is not None or time.monotonic() > deadline:
                            raise RuntimeError(
                                "Healthcare target did not start; inspect target.log"
                            )
                        time.sleep(0.1)
                load_env = dict(
                    os.environ,
                    BASE_URL=f"http://127.0.0.1:{port}",
                    API_TOKEN=env["CLINICIAN_TOKEN"],
                    PROFILE="smoke",
                )
                return command([k6, "run", "scripts/healthcare.js"], lab, load_env)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        finally:
            log.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--python", type=Path, help="Optional shared verification interpreter")
    parser.add_argument("--k6", default="k6")
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    own = workspace / "continuous-quality-platform"
    policy = json.loads((own / "quality-policy.json").read_text())
    # Clear only the gate's known generated files so stale reports cannot satisfy this run.
    for check in policy["checks"]:
        path = (workspace / check["path"]).resolve()
        if not path.is_relative_to(workspace):
            raise ValueError("Policy path escapes workspace")
        path.unlink(missing_ok=True)
        path.parent.mkdir(parents=True, exist_ok=True)
    failures = []
    for name, package in PROJECTS.items():
        root = workspace / name
        python = python_interpreter(root, args.python)
        env = dict(os.environ, PYTHONPATH=str(root / "src"))
        if name == "ai-test-case-generator":
            if command(["npm", "run", "build"], root / "frontend"):
                failures.append(name + ": frontend build")
        lint = command([str(python), "-m", "ruff", "check", "."], root, env)
        formatting = command([str(python), "-m", "ruff", "format", "--check", "."], root, env)
        test_args = [str(python), "-m", "pytest", "--junitxml=artifacts/junit.xml"]
        if name != "enterprise-test-automation":
            test_args += [f"--cov={package}", "--cov-report=xml:artifacts/coverage.xml"]
        if command(test_args, root, env) or lint or formatting:
            failures.append(name + ": checks")
    lab = workspace / "performance-engineering-lab"
    if command(
        [
            "node",
            "--test",
            "--test-reporter=junit",
            "--test-reporter-destination=artifacts/junit.xml",
            "tests/config.test.js",
        ],
        lab,
    ):
        failures.append("performance unit tests")
    python = python_interpreter(workspace / "healthcare-qa-framework", args.python)
    try:
        if performance(workspace, python, args.k6):
            failures.append("k6 workload")
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        failures.append(f"k6 execution: {exc}")
    result = evaluate(workspace, policy)
    result["command_failures"] = failures
    result["passed"] = result["passed"] and not failures
    output = own / "artifacts/quality-summary.json"
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
