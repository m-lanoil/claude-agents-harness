#!/usr/bin/env python3
import re
import sys
from datetime import date
from pathlib import Path
import subprocess

PROJECT_ROOT = Path(__file__).parent.parent
KB_LOG = PROJECT_ROOT / "logs/KB_STALENESS_LOG.md"
STALE_DAYS = 30
REFRESHED_RE = re.compile(r'\s+-\s+"(.+)":\s*(\d{4}-\d{2}-\d{2})\s*')
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


def get_refreshed(kb_file):
    """Return [(heading, date)] from the refreshed: list in the leading --- block.

    Entries are indented `- "heading": YYYY-MM-DD` lines after an unindented `refreshed:`
    line, up to the next unindented line or the closing ---. Malformed entries are skipped.
    """
    lines = kb_file.read_text().splitlines()
    if not lines or lines[0].strip() != "---":
        return []
    entries = []
    in_list = False
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if not line.strip():
            continue
        if not line[0].isspace():
            in_list = line.rstrip() == "refreshed:"
            continue
        m = REFRESHED_RE.fullmatch(line) if in_list else None
        if not m:
            continue
        try:
            entries.append((m.group(1), date.fromisoformat(m.group(2))))
        except ValueError:
            continue
    return entries


def recent_sections(kb_file):
    """Refreshed sections of kb_file dated within STALE_DAYS of TODAY."""
    return [(heading, day) for heading, day in get_refreshed(kb_file)
            if (TODAY - day).days <= STALE_DAYS]


def sections_cell(sections):
    if not sections:
        return "none"
    cells = [f'"{heading}" ({day})' for heading, day in sections]
    return ", ".join(cells).replace("|", "\\|")


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
                stale.append((worker, kb_file.name, fetched, age, recent_sections(kb_file)))
    return stale


def ensure_header():
    if not KB_LOG.exists():
        KB_LOG.write_text("# KB Staleness Log\n")


def append_entry(stale):
    lines = [f"\n## {TODAY}\n"]
    if stale:
        lines += [
            f"| Worker | File | Fetched | Age (days) | Sections refreshed <={STALE_DAYS} days |",
            "|--------|------|---------|------------|------------------------------|",
        ]
        for worker, filename, fetched, age, sections in stale:
            lines.append(f"| {worker} | `{filename}` | {fetched} | {age} | {sections_cell(sections)} |")
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
    escaped = msg.replace("\\", "\\\\").replace('"', '\\"')
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{escaped}" with title "KB Staleness Alert"'],
            check=False,
        )
    except OSError as exc:
        print(f"notification skipped: {exc}", file=sys.stderr)


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
