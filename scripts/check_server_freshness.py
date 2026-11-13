#!/usr/bin/env python3
import re
import sys
from datetime import date, datetime
from pathlib import Path
import subprocess

PROJECT_ROOT = Path(__file__).parent.parent
TOOL_LOG = PROJECT_ROOT / "logs/TOOL_LOG.md"
ALERTS_FILE = PROJECT_ROOT / "logs/SERVER_FRESHNESS_ALERTS.md"
STALE_DAYS = 30
TODAY = date.today()


def parse_sections(text):
    sections = {}
    current = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    return sections


def extract_table_rows(lines):
    rows = []
    for line in lines:
        if not line.startswith("|") or "---" in line:
            continue
        cols = [c.strip() for c in line.split("|") if c.strip()]
        if len(cols) >= 2:
            rows.append(cols)
    return rows


def parse_server_dates(sections):
    audited = {}
    for row in extract_table_rows(sections.get("Audited", [])):
        try:
            ts_date = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S").date()
        except ValueError:
            continue
        m = re.search(r'`([^`]+)`', row[1])
        if m:
            audited[m.group(1)] = ts_date  # last entry wins (most recent audit)

    created = {}
    for row in extract_table_rows(sections.get("Created", [])):
        try:
            ts_date = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S").date()
        except ValueError:
            continue
        m = re.search(r'`([^`]+)`', row[1])
        if m and m.group(1) not in created:
            created[m.group(1)] = ts_date  # first (only) creation entry

    return audited, created


def ensure_header():
    if not ALERTS_FILE.exists():
        ALERTS_FILE.write_text("# Server Freshness Alerts\n")


def notify(message):
    escaped = message.replace("\\", "\\\\").replace('"', '\\"')
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{escaped}" with title "Server Freshness Alert"'],
            check=False,
        )
    except OSError as exc:
        print(f"notification skipped: {exc}", file=sys.stderr)


def resolve_open_alert():
    headings = [line for line in ALERTS_FILE.read_text().splitlines() if line.startswith("## ")]
    if not headings or not re.search(r"—\s*STALE\b", headings[-1]):
        return
    with ALERTS_FILE.open("a") as f:
        f.write(f"\n## {TODAY} — RESOLVED\n\nAll servers are current (none older than {STALE_DAYS} days).\n")


def main():
    if not TOOL_LOG.exists():
        print(f"ERROR: {TOOL_LOG} not found", file=sys.stderr)
        sys.exit(1)

    sections = parse_sections(TOOL_LOG.read_text())
    audited, created = parse_server_dates(sections)

    all_servers = sorted(set(audited) | set(created))
    stale = []
    for server in all_servers:
        if server in audited:
            basis, ref = "Audited", audited[server]
        else:
            basis, ref = "Created", created[server]
        age = (TODAY - ref).days
        if age > STALE_DAYS:
            stale.append((server, basis, ref, age))

    ensure_header()

    if not stale:
        print(f"All servers current as of {TODAY}. No action required.")
        resolve_open_alert()
        return

    lines = [
        f"\n## {TODAY} — STALE\n",
        "| Server | Basis | Last Audit/Creation | Age (days) |",
        "|--------|-------|---------------------|------------|",
    ]
    for server, basis, ref, age in stale:
        lines.append(f"| `{server}` | {basis} | {ref} | {age} |")
    lines.append("")

    with ALERTS_FILE.open("a") as f:
        f.write("\n".join(lines) + "\n")

    print(f"STALE: {len(stale)} server(s) flagged. Written to {ALERTS_FILE.name}")

    names = ", ".join(s[0].split("/")[-1] for s in stale)
    msg = f"{len(stale)} stale server(s): {names}"
    if len(msg) > 100:
        msg = f"{len(stale)} stale server(s) — see SERVER_FRESHNESS_ALERTS.md"
    notify(msg)


if __name__ == "__main__":
    main()
