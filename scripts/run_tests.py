"""Run PrivyFlow test suites, linting and security scans.

    uv run scripts/run_tests.py <command>

Commands: unit, integration, security, evaluation, e2e, all, lint, scan.
Reports are written to reports/ (JUnit XML, coverage XML).
"""

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
SUITES = ("unit", "integration", "security", "evaluation", "e2e")
COVERAGE_MINIMUM = 80


def run(*cmd: str) -> int:
    print("+", " ".join(cmd), flush=True)
    return subprocess.call(cmd, cwd=ROOT)


def has_service_code() -> bool:
    return any((ROOT / "services").rglob("*.py")) if (ROOT / "services").is_dir() else False


def pytest_args(suite: str) -> list[str]:
    REPORTS.mkdir(exist_ok=True)
    args = [sys.executable, "-m", "pytest", f"--junitxml={REPORTS / f'junit-{suite}.xml'}"]
    args.append("tests" if suite == "all" else f"tests/{suite}")
    # Coverage applies once service code exists, so an empty tree cannot pass or fail on it.
    if suite in ("all", "unit", "integration") and has_service_code():
        args += [
            "--cov",
            "--cov-report=term-missing",
            f"--cov-report=xml:{REPORTS / 'coverage.xml'}",
            f"--cov-fail-under={COVERAGE_MINIMUM}",
        ]
    return args


def lint() -> int:
    return run("ruff", "check", ".") or run("ruff", "format", "--check", ".")


def scan() -> int:
    status = 0
    if has_service_code():
        status |= run("bandit", "-q", "-r", "services")
    else:
        print("bandit: skipped, no service code yet")
    return status | run("pip-audit")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=[*SUITES, "all", "lint", "scan"])
    command = parser.parse_args().command
    if command == "lint":
        return lint()
    if command == "scan":
        return scan()
    return run(*pytest_args(command))


if __name__ == "__main__":
    sys.exit(main())
