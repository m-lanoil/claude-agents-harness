import psutil
from fastmcp import FastMCP

mcp = FastMCP("system_monitor")


@mcp.tool()
def get_cpu_stats() -> dict:
    """
    Return current CPU utilization and hardware info.
    Includes system-wide percent, per-core percent, core counts, and frequency.
    Note: blocks for 1 second to get an accurate reading.
    """
    return {
        "cpu_percent": psutil.cpu_percent(interval=1),
        "cpu_percent_per_core": psutil.cpu_percent(interval=1, percpu=True),
        "logical_cores": psutil.cpu_count(logical=True),
        "physical_cores": psutil.cpu_count(logical=False),
        "cpu_freq_mhz": {
            "current": psutil.cpu_freq().current,
            "min": psutil.cpu_freq().min,
            "max": psutil.cpu_freq().max,
        } if psutil.cpu_freq() else None,
    }


@mcp.tool()
def get_memory_stats() -> dict:
    """
    Return current RAM and swap memory usage.
    All byte values are in bytes; percent values are 0-100.
    """
    vm = psutil.virtual_memory()
    swap = psutil.swap_memory()
    return {
        "virtual_memory": {
            "total": vm.total,
            "available": vm.available,
            "used": vm.used,
            "free": vm.free,
            "percent": vm.percent,
        },
        "swap_memory": {
            "total": swap.total,
            "used": swap.used,
            "free": swap.free,
            "percent": swap.percent,
        },
    }


@mcp.tool()
def get_disk_stats() -> dict:
    """
    Return disk usage for all physical partitions.
    Reports total, used, free (bytes) and percent used per partition.
    Uses disk_partitions(all=False) to skip pseudo/memory filesystems.
    """
    partitions = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
            partitions.append({
                "device": part.device,
                "mountpoint": part.mountpoint,
                "fstype": part.fstype,
                "total_bytes": usage.total,
                "used_bytes": usage.used,
                "free_bytes": usage.free,
                "percent_used": usage.percent,
            })
        except OSError:
            pass
    return {"partitions": partitions}


@mcp.tool()
def scan_large_files(root_dir: str = "/Users", top_n: int = 20, min_size_mb: float = 50.0) -> dict:
    """
    Scan a directory recursively and return the top N largest files.
    Skips symlinks, inaccessible paths, and files below min_size_mb.
    Returns results sorted by size descending.
    """
    import os
    from datetime import datetime

    min_bytes = min_size_mb * 1024 * 1024
    found = []

    for dirpath, dirnames, filenames in os.walk(root_dir):
        # Skip symlinked directories to avoid loops
        dirnames[:] = [d for d in dirnames if not os.path.islink(os.path.join(dirpath, d))]
        for filename in filenames:
            filepath = os.path.join(dirpath, filename)
            if os.path.islink(filepath):
                continue
            try:
                size = os.path.getsize(filepath)
                if size >= min_bytes:
                    mtime = os.path.getmtime(filepath)
                    found.append({
                        "path": filepath,
                        "size_bytes": size,
                        "size_mb": round(size / (1024 * 1024), 2),
                        "last_modified": datetime.fromtimestamp(mtime).isoformat(),
                    })
            except (OSError, PermissionError):
                continue

    found.sort(key=lambda x: x["size_bytes"], reverse=True)
    return {
        "root_dir": root_dir,
        "min_size_mb": min_size_mb,
        "total_found": len(found),
        "results": found[:top_n],
    }


def _escalate(current: str, new: str) -> str:
    order = {"GO": 0, "WARN": 1, "STOP": 2}
    return new if order.get(new, 0) > order.get(current, 0) else current


@mcp.tool()
def system_health_check() -> dict:
    """
    Run a consolidated pre-work system health check on macOS.
    Checks CPU, RAM, swap, disk (/System/Volumes/Data), and battery.
    Returns a verdict (GO / WARN / STOP), a plain-English summary, and
    per-component details with the threshold rationale.

    Caveats:
    - RAM % is an approximation of Apple's Memory Pressure (composite metric).
    - CPU % on Apple Silicon does not distinguish efficiency vs performance cores.
    - Battery returns GO if no battery is detected (e.g. Mac mini/Pro).
    """
    checks = []
    verdict = "GO"

    # CPU
    cpu_pct = psutil.cpu_percent(interval=1)
    if cpu_pct > 95:
        s, msg = "STOP", f"CPU at {cpu_pct:.1f}% — at or over capacity"
    elif cpu_pct >= 80:
        s, msg = "WARN", f"CPU at {cpu_pct:.1f}% — sustained high load, approaching bottleneck"
    else:
        s, msg = "GO", f"CPU at {cpu_pct:.1f}% — normal"
    checks.append({"component": "CPU", "status": s, "value_pct": round(cpu_pct, 1), "detail": msg})
    verdict = _escalate(verdict, s)

    # RAM
    vm = psutil.virtual_memory()
    avail_mb = round(vm.available / (1024 ** 2))
    if vm.percent > 90:
        s, msg = "STOP", f"RAM at {vm.percent:.1f}% used ({avail_mb} MB available) — likely red memory pressure"
    elif vm.percent >= 75:
        s, msg = "WARN", f"RAM at {vm.percent:.1f}% used ({avail_mb} MB available) — compression likely active"
    else:
        s, msg = "GO", f"RAM at {vm.percent:.1f}% used ({avail_mb} MB available) — healthy"
    checks.append({"component": "RAM", "status": s, "value_pct": round(vm.percent, 1), "detail": msg})
    verdict = _escalate(verdict, s)

    # Swap
    swap = psutil.swap_memory()
    swap_mb = round(swap.used / (1024 ** 2))
    claude_running = any(
        "claude" in (p.info.get("exe") or "").lower()
        for p in psutil.process_iter(["exe"])
    )
    if swap_mb > 1024:
        if claude_running:
            s, msg = "WARN", f"Swap at {swap_mb} MB — active Claude Code session, pressure is expected"
        else:
            s, msg = "STOP", f"Swap at {swap_mb} MB — RAM saturated, expect latency spikes"
    elif swap_mb >= 500:
        s, msg = "WARN", f"Swap at {swap_mb} MB — light but sustained memory pressure"
    else:
        s, msg = "GO", f"Swap at {swap_mb} MB — minimal"
    checks.append({"component": "Swap", "status": s, "value_mb": swap_mb, "detail": msg})
    verdict = _escalate(verdict, s)

    # Disk — only /System/Volumes/Data (main user volume)
    for part in psutil.disk_partitions(all=False):
        if part.mountpoint != "/System/Volumes/Data":
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
            free_pct = round(100 - usage.percent, 1)
            free_gb = round(usage.free / (1024 ** 3), 1)
            if free_pct < 10:
                s, msg = "STOP", f"Disk critically full — {free_gb} GB ({free_pct}%) free"
            elif free_pct < 20:
                s, msg = "WARN", f"Disk below recommended minimum — {free_gb} GB ({free_pct}%) free"
            else:
                s, msg = "GO", f"Disk healthy — {free_gb} GB ({free_pct}%) free"
            checks.append({"component": "Disk", "status": s, "free_pct": free_pct, "free_gb": free_gb, "detail": msg})
            verdict = _escalate(verdict, s)
        except OSError:
            pass

    # Battery
    battery = psutil.sensors_battery()
    if battery is None:
        checks.append({"component": "Battery", "status": "GO", "value_pct": None,
                        "detail": "No battery detected"})
    else:
        pct = round(battery.percent, 1)
        plugged = battery.power_plugged
        if not plugged and pct <= 10:
            s, msg = "STOP", f"Battery critically low at {pct}% — plug in immediately"
        elif not plugged and pct <= 20:
            s, msg = "WARN", f"Battery low at {pct}% and unplugged"
        else:
            state = "plugged in" if plugged else "unplugged"
            s, msg = "GO", f"Battery at {pct}%, {state}"
        checks.append({"component": "Battery", "status": s, "value_pct": pct, "detail": msg})
        verdict = _escalate(verdict, s)

    summaries = {
        "GO": "All systems healthy — good to go.",
        "WARN": "One or more systems need attention — proceed with caution.",
        "STOP": "Critical issue detected — resolve before starting work.",
    }
    return {"verdict": verdict, "summary": summaries[verdict], "checks": checks}


if __name__ == "__main__":
    mcp.run()
