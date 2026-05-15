#!/usr/bin/env python3
import re
import sys
from datetime import date
from pathlib import Path
import subprocess

PROJECT_ROOT = Path(__file__).parent.parent
KB_LOG = PROJECT_ROOT / "KB_STALENESS_LOG.md"
STALE_DAYS = 30
TODAY = date.today()

KB_DIRS = {
    "developer": PROJECT_ROOT / "workers/developer/kb",
    "architect": PROJECT_ROOT / "workers/architect/kb",
    "content": PROJECT_ROOT / "workers/content/kb",
    "servers": PROJECT_ROOT / "servers/kb",
}


def get_fetched_date(kb_file):
    text = kb_file.read_text()
    m = re.search(r'^fetched:\s*(\d{4}-\d{2}-\d{2})', text, re.MULTILINE)
    if not m:
        return None
    try:
        return date.fromisoformat(m.group(1))
    except ValueError:
        return None


def scan():
    stale = []
    for worker, kb_dir in KB_DIRS.items():
        if not kb_dir.exists():
            continue
        for kb_file in sorted(kb_dir.glob("kb_*.md")):
            fetched = get_fetched_date(kb_file)
            if fetched is None:
                continue
            age = (TODAY - fetched).days
            if age > STALE_DAYS:
                stale.append((worker, kb_file.name, fetched, age))
    return stale


def ensure_header():
    if not KB_LOG.exists():
        KB_LOG.write_text("# KB Staleness Log\n")


def append_entry(stale):
    lines = [f"\n## {TODAY}\n"]
    if stale:
        lines += [
            "| Worker | File | Fetched | Age (days) |",
            "|--------|------|---------|------------|",
        ]
        for worker, filename, fetched, age in stale:
            lines.append(f"| {worker} | `{filename}` | {fetched} | {age} |")
    else:
        lines.append("Clean run: All kb files current — no stale entries.")
    lines.append("")
    with KB_LOG.open("a") as f:
        f.write("\n".join(lines) + "\n")


def notify(stale):
    oldest = max(stale, key=lambda x: x[3])
    msg = f"{len(stale)} stale kb file(s) — oldest: {oldest[1]}"
    if len(msg) > 100:
        msg = f"{len(stale)} stale kb file(s) — check KB_STALENESS_LOG.md"
    subprocess.run(
        ["osascript", "-e",
         f'display notification "{msg}" with title "KB Staleness Alert"'],
        check=False,
    )


def main():
    stale = scan()
    ensure_header()
    append_entry(stale)

    if stale:
        print(f"STALE: {len(stale)} kb file(s) flagged. Written to {KB_LOG.name}")
        notify(stale)
    else:
        print(f"All kb files current as of {TODAY}.")


if __name__ == "__main__":
    main()
