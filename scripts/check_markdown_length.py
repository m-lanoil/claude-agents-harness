#!/usr/bin/env python3
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
ALERTS_FILE = PROJECT_ROOT / "MARKDOWN_LENGTH_ALERTS.md"
LIMIT = 100
PATTERNS = [
    "CLAUDE.md", "workers/*/CLAUDE.md", "workers/WORKER_STANDARDS.md",
    "workers/*_PROTOCOL.md", "workers/*_CONVENTION.md", "scripts/*.md",
    "pipeline/PIPELINE.md", "pipeline/phases/*.md", "TASTE.md",
]


def count_nonempty(path):
    return sum(1 for line in path.read_text().splitlines() if line.strip())


def main():
    seen, unique = set(), []
    for pattern in PATTERNS:
        for f in sorted(PROJECT_ROOT.glob(pattern)):
            if f not in seen:
                seen.add(f)
                unique.append(f)

    rows, over_limit = [], 0
    for path in unique:
        count = count_nonempty(path)
        status = "OVER_LIMIT" if count > LIMIT else "OK"
        over_limit += status == "OVER_LIMIT"
        rows.append((str(path.relative_to(PROJECT_ROOT)), count, status))

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    out = [
        "# Markdown Length Alerts",
        f"*Last checked: {now}*",
        "",
        "| File | Lines | Status |",
        "|------|-------|--------|",
    ] + [f"| {r} | {c} | {s} |" for r, c, s in rows]

    ALERTS_FILE.write_text("\n".join(out) + "\n")
    print(f"{len(rows)} files checked, {over_limit} OVER_LIMIT")
    sys.exit(1 if over_limit else 0)


if __name__ == "__main__":
    main()
