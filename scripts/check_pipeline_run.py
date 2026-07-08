#!/usr/bin/env python3
"""Check one pipeline run directory against the artifact contract in pipeline/PIPELINE.md.

Usage: python scripts/check_pipeline_run.py pipeline/runs/<task_slug>
Exit codes: 0 ok, 1 contract violation, 2 bad invocation.
"""
import re
import sys
from pathlib import Path

# Phase order per the PIPELINE.md contract table
ARTIFACTS = [
    "task.md",
    "research.md",
    "plan.md",
    "holdback/test_spec.md",
    "implementation_notes.md",
    "validation_report.md",
    "publish_report.md",
]
VERDICT_RE = re.compile(r"^#*\s*Human Verdict:\s*APPROVED\b", re.MULTILINE)


def main():
    if len(sys.argv) != 2 or not Path(sys.argv[1]).is_dir():
        print(f"usage: {sys.argv[0]} pipeline/runs/<task_slug>")
        sys.exit(2)
    run_dir = Path(sys.argv[1])

    present = {a: (run_dir / a).is_file() for a in ARTIFACTS}
    violations = []
    missing_earlier = False
    for a in ARTIFACTS:
        status = "PRESENT" if present[a] else "MISSING"
        if present[a] and missing_earlier:
            status = "OUT_OF_ORDER"
            violations.append(f"{a} exists but an earlier-phase artifact is missing")
        print(f"{status:12} {a}")
        missing_earlier = missing_earlier or not present[a]

    if present["publish_report.md"]:
        report = run_dir / "validation_report.md"
        approved = report.is_file() and VERDICT_RE.search(report.read_text())
        if not approved:
            print("GATE_VIOLATION publish_report.md exists without 'Human Verdict: APPROVED'")
            violations.append("human gate")

    sys.exit(1 if violations else 0)


if __name__ == "__main__":
    main()
