import json
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
claude_running = any(
    "claude" in (p.info.get("exe") or "").lower()
    for p in psutil.process_iter(["exe"])
)
if swap_mb > 1024:
    if claude_running:
        s, msg = "WARN", f"Swap at {swap_mb} MB — active Claude Code session, pressure is expected"
        tip = None
    else:
        s, msg = "STOP", f"Swap at {swap_mb} MB — RAM saturated"
        tip = "Close memory-heavy apps  |  Find hogs: ps aux | sort -rk 4 | head -10"
elif swap_mb >= 500:
    s, msg = "WARN", f"Swap at {swap_mb} MB — memory pressure"
    tip = "Close memory-heavy apps  |  Find hogs: ps aux | sort -rk 4 | head -10"
else:
    s, msg, tip = "GO", f"Swap at {swap_mb} MB — minimal", None
checks.append({"component": "Swap", "status": s, "detail": msg, "tip": tip})
verdict = _escalate(verdict, s)

for part in psutil.disk_partitions(all=False):
    if part.mountpoint != "/System/Volumes/Data":
        continue
    try:
        usage = psutil.disk_usage(part.mountpoint)
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
    if not plugged and pct <= 10:
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
