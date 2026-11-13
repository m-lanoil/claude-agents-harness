#!/usr/bin/env python3
"""Run every test suite in its own environment and summarise the results.

Usage: uv run python scripts/run_tests.py
Exits non-zero if any suite failed. A failing suite does not stop the later ones.
"""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVERS = ROOT / "servers"


def server_suite(name, with_pytest):
    project = SERVERS / name
    command = ["uv", "run", "--project", str(project)]
    if with_pytest:
        command += ["--with", "pytest"]
    return (f"server: {name}", project, command + ["pytest"])


SUITES = [
    (
        "coordinator",
        ROOT,
        ["uv", "run", "--with", "claude-agent-sdk", "--with", "pytest", "pytest", "coordinator/tests"],
    ),
    ("scripts", ROOT, ["uv", "run", "--with", "pytest", "pytest", "scripts/tests"]),
    ("templates", ROOT, ["uv", "run", "--with", "pytest", "pytest", "tests"]),
    server_suite("docs_fetcher", with_pytest=False),
    server_suite("system_monitor", with_pytest=True),
    server_suite("web_search", with_pytest=True),
]


def run_suite(name, cwd, command):
    print(f"\n=== {name} ===\n$ {' '.join(command)}\n(cwd: {cwd})", flush=True)
    try:
        return subprocess.run(command, cwd=cwd).returncode
    except OSError as error:
        print(f"could not start {command[0]}: {error}", flush=True)
        return 127


def main():
    results = [(name, run_suite(name, cwd, command)) for name, cwd, command in SUITES]

    print("\n=== summary ===")
    for name, code in results:
        print(f"{'PASS' if code == 0 else 'FAIL'}  {name}" + ("" if code == 0 else f"  (exit {code})"))
    failed = [name for name, code in results if code != 0]
    print(f"\n{len(results) - len(failed)} of {len(results)} suites passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
