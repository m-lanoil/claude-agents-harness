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
PHASE_OF = {
    "task.md": 1, "research.md": 1, "plan.md": 2, "holdback/test_spec.md": 2,
    "implementation_notes.md": 3, "validation_report.md": 4, "publish_report.md": 5,
}
PHASE_NAMES = {1: "research", 2: "planning", 3: "coding", 4: "validation", 5: "publicizing"}
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

    # Backfill rule (PIPELINE.md): resume at the earliest gapped phase, not your current step
    missing = [a for a in ARTIFACTS if not present[a]]
    resume = PHASE_OF[missing[0]] if missing else None
    plan = run_dir / "plan.md"
    # Bracketed marker per the phase 2 template — bare word in prose is not a gap
    if present["plan.md"] and "[PROVISIONAL" in plan.read_text():
        print("PROVISIONAL   plan.md has unreconciled items — a phase 2 gap")
        resume = min(resume or 2, 2)
    if resume:
        print(f"RESUME AT: phase {resume} — {PHASE_NAMES[resume]}"
              + (f" (earliest gap: {missing[0]})" if missing and PHASE_OF[missing[0]] <= resume else ""))
    else:
        print("RUN COMPLETE: all artifacts present")

    sys.exit(1 if violations else 0)


if __name__ == "__main__":
    main()
