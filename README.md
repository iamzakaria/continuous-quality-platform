# Continuous Quality Engineering Platform

**Project 05 · Repository: `continuous-quality-platform` · Python package: `quality_platform`**

A local and CI quality orchestration platform for all five portfolio repositories. It executes lint/build/tests and a bounded performance workload, then evaluates fresh JUnit, coverage, and k6 evidence. The gate returns a nonzero exit code for failed, missing, empty, stale, malformed, or insufficient evidence.

## Architecture

`quality_platform.run` orchestrates sibling repositories and starts/stops an isolated healthcare target for k6. It clears only policy-listed evidence files before a run so older passes cannot satisfy new work. `quality_platform.gate` evaluates reports; `quality-policy.json` declares required tests and coverage budgets. Each repository remains independently runnable.

The gate requires zero failures, zero skipped tests, minimum suite sizes, at least 70% Python line coverage for Projects 02/03/05, and the four performance thresholds. Evidence must be less than one hour old by default. XML parsing uses defusedxml, and report paths cannot escape the workspace.

The orchestrator is validated end-to-end; its subprocess launcher is excluded from the unit line-coverage percentage in `.coveragerc`. Gate decision logic is covered by unit tests. React and k6 JavaScript coverage are not represented as Python coverage.

## macOS setup

```bash
/opt/homebrew/bin/python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.lock
python -m pip install --no-deps -e .
```

Use native ARM64 Python 3.12 on Apple Silicon. Install it with `brew install python@3.12` if needed. Runtime dependencies are pinned in `requirements.lock`; test/development dependencies are pinned in `requirements-dev.lock`. The lock files were resolved universally with uv. Updating dependency versions requires rerunning the verification suite.

```bash
python -m pytest --junitxml=artifacts/junit.xml --cov=quality_platform --cov-report=xml:artifacts/coverage.xml
```

For all-project execution, set up each repository's `.venv`, install Chromium, install frontend packages with `npm ci`, and make `k6` available on PATH. Keep these exact sibling names:

```text
portfolio/
  enterprise-test-automation/
  ai-test-case-generator/
  healthcare-qa-framework/
  performance-engineering-lab/
  continuous-quality-platform/
```

From this repository:

```bash
python -m quality_platform.run --workspace ..
```

The default uses each Python repository's own `.venv/bin/python`. If you intentionally provision one shared verification environment with all four repositories' test dependencies, pass `--python /absolute/path/to/venv/bin/python`. Pass `--k6 /absolute/path/to/k6` for a workspace-local binary. The local runner uses inherited file descriptors for its ephemeral server and targets macOS/Linux.

Inspect `artifacts/quality-summary.json`. To evaluate already-produced evidence without rerunning tests:

```bash
python -m quality_platform.gate --workspace .. --policy quality-policy.json
```

A missing k6 executable or target-start failure fails the integrated run. No missing component is relabeled as a successful check. This gate assumes reports originate from a trusted local/CI job; file timestamps and report content are not cryptographic attestations or commit-provenance guarantees.

## GitHub Actions

- `quality.yml`: repository unit tests, coverage, lint, and Docker image build on pushes/PRs.
- `portfolio.yml`: manually triggered integration pipeline; checks out all five exact repository names under the same owner, executes them, and uploads evidence.
- `sonarqube.yml`: manually triggered analysis on a trusted self-hosted runner that can reach your SonarQube server.

Publish all five repositories before dispatching the portfolio workflow. Public sibling repositories work with normal read access; private repositories need an appropriately scoped read-only checkout token. Configure branch protection in GitHub after the check names have run. Workflows are provided but have not been dispatched here.

## Docker evidence gate

```bash
docker build -t continuous-quality-platform:local .
docker run --rm -v /absolute/path/to/portfolio:/workspace:ro continuous-quality-platform:local
```

The non-root container evaluates mounted reports and prints the result. It does not run the entire portfolio inside the gate container. Its JSON output lives in the container unless a writable `/app/artifacts` volume is supplied.

## SonarQube

Use `.env.example` to create an ignored `.env` with a generated `SONAR_DB_PASSWORD`, then:

```bash
docker compose up -d
```

Open `http://127.0.0.1:9000`, complete initial admin setup, create a project with the repository slug as key, and generate an analysis token. Install SonarScanner on the machine that runs analysis. Generate the project's coverage report first, then export `SONAR_TOKEN` and `SONAR_HOST_URL` and run:

```bash
bash scripts/sonar-scan.sh /absolute/path/to/project
```

The script waits for the actual server quality-gate result; it does not infer success from upload completion. Each repository includes `sonar-project.properties`. The local Sonar Compose recipe uses PostgreSQL and named persistent volumes. Its `sonarqube:community` and `postgres:17` tags are moving tags; pin verified image digests before adopting the stack beyond this lab. Docker Desktop needs enough memory for SonarQube; Linux hosts must satisfy the official Elasticsearch kernel limits. No kernel settings are changed by this project.

The SonarQube server gate is a separate check from the local report gate. All five projects were analyzed against a local SonarQube server; see VALIDATION.md and the portfolio validation record for results. References: [SonarQube Docker/Apple Silicon support](https://docs.sonarsource.com/sonarqube-community-build/server-installation/from-docker-image/installation-overview), [quality-gate waiting](https://docs.sonarsource.com/sonarqube-community-build/analyzing-source-code/ci-integration/overview).

## Next increment

Add commit-bound evidence manifests, dependency/security scanning, trend storage, centrally managed quality policies, and pinned CI action/image digests. See [VALIDATION.md](VALIDATION.md) for actual execution results.
