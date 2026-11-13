import json
from pathlib import PurePath

import psutil


def _escalate(current, new):
    order = {"GO": 0, "WARN": 1, "STOP": 2}
    return new if order.get(new, 0) > order.get(current, 0) else current


checks = []
verdict = "GO"

cpu_pct = psutil.cpu_percent(interval=1)
if cpu_pct > 95:
    s, msg = "STOP", f"CPU at {cpu_pct:.1f}% — at or over capacity"
    tip = "Kill runaway processes: ps aux | sort -rk 3 | head -10"
elif cpu_pct >= 80:
    s, msg = "WARN", f"CPU at {cpu_pct:.1f}% — sustained high load"
    tip = "Find top CPU users: ps aux | sort -rk 3 | head -10"
else:
    s, msg, tip = "GO", f"CPU at {cpu_pct:.1f}% — normal", None
checks.append({"component": "CPU", "status": s, "detail": msg, "tip": tip})
verdict = _escalate(verdict, s)

swap = psutil.swap_memory()
swap_mb = round(swap.used / (1024 ** 2))

_HEAVY_APPS = {
    "Google Chrome": "Chrome",
    "Slack": "Slack",
    "Messages": "Messages",
    "Microsoft Word": "Word",
    "Microsoft Excel": "Excel",
    "Microsoft Teams": "Teams",
    "Spotify": "Spotify",
    "zoom.us": "Zoom",
    "Discord": "Discord",
}
running_heavy = []
claude_running = False
for p in psutil.process_iter(["name", "exe"]):
    name = p.info.get("name") or ""
    exe = p.info.get("exe") or ""
    exe_path = PurePath(exe) if exe else None
    if (
        name.lower() == "claude"
        or (exe_path is not None and exe_path.name.lower() == "claude")
        or (exe_path is not None and any(d.lower() == "claude" for d in exe_path.parts[:-1]))
    ):
        claude_running = True
    for proc_name, label in _HEAVY_APPS.items():
        app = proc_name.lower()
        if label not in running_heavy and (
            name.lower() == app
            or name.lower().startswith(app + " ")
            or f"/{app}.app/" in exe.lower()
        ):
            running_heavy.append(label)

if swap_mb > 1024:
    if claude_running:
        s, msg = "WARN", f"Swap at {swap_mb} MB — active Claude Code session, pressure is expected"
    else:
        s, msg = "STOP", f"Swap at {swap_mb} MB — RAM saturated"
elif swap_mb >= 500:
    s, msg = "WARN", f"Swap at {swap_mb} MB — memory pressure"
else:
    s, msg = "GO", f"Swap at {swap_mb} MB — minimal"

if swap_mb >= 500 and running_heavy:
    tip = "Close if not in use: " + ", ".join(running_heavy)
elif swap_mb > 1024 and not claude_running:
    tip = "Find hogs: ps aux -m | head -10"
else:
    tip = None

checks.append({"component": "Swap", "status": s, "detail": msg, "tip": tip})
verdict = _escalate(verdict, s)

_mountpoints = [part.mountpoint for part in psutil.disk_partitions(all=False)]
_disk_mount = next((m for m in ("/System/Volumes/Data", "/") if m in _mountpoints), None)
if _disk_mount is not None:
    try:
        usage = psutil.disk_usage(_disk_mount)
        free_pct = round(100 - usage.percent, 1)
        free_gb = round(usage.free / (1024 ** 3), 1)
        if free_pct < 10:
            s, msg = "STOP", f"Disk critically full — {free_gb} GB ({free_pct}%) free"
            tip = "Find large files: du -sh ~/* | sort -rh | head -10  |  Empty Trash"
        elif free_pct < 20:
            s, msg = "WARN", f"Disk low — {free_gb} GB ({free_pct}%) free"
            tip = "Find large dirs: du -sh ~/* | sort -rh | head -10"
        else:
            s, msg, tip = "GO", f"Disk healthy — {free_gb} GB ({free_pct}%) free", None
        checks.append({"component": "Disk", "status": s, "detail": msg, "tip": tip})
        verdict = _escalate(verdict, s)
    except OSError:
        pass

battery = psutil.sensors_battery()
if battery is None:
    checks.append({"component": "Battery", "status": "GO", "detail": "No battery detected", "tip": None})
else:
    pct = round(battery.percent, 1)
    plugged = battery.power_plugged
    if plugged is None:
        msg = f"Battery at {pct}%, power state unknown"
        if pct <= 20:
            s, tip = "WARN", "Connect charger soon"
        else:
            s, tip = "GO", None
    elif not plugged and pct <= 10:
        s, msg = "STOP", f"Battery critically low at {pct}%"
        tip = "Plug in charger immediately"
    elif not plugged and pct <= 20:
        s, msg = "WARN", f"Battery low at {pct}%, unplugged"
        tip = "Connect charger soon"
    else:
        state = "plugged in" if plugged else "unplugged"
        s, msg, tip = "GO", f"Battery at {pct}%, {state}", None
    checks.append({"component": "Battery", "status": s, "detail": msg, "tip": tip})
    verdict = _escalate(verdict, s)

summaries = {
    "GO": "All systems healthy — good to go.",
    "WARN": "One or more systems need attention — proceed with caution.",
    "STOP": "Critical issue detected — resolve before starting work.",
}

lines = [f"System Health: {verdict} — {summaries[verdict]}"]
for c in checks:
    lines.append(f"  [{c['status']}] {c['component']}: {c['detail']}")
    if c["tip"]:
        lines.append(f"         Fix: {c['tip']}")

summary = "\n".join(lines)
print(json.dumps({
    "systemMessage": summary,
    "hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": summary
    }
}))
