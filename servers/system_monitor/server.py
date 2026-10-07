import psutil
from fastmcp import FastMCP

mcp = FastMCP("system_monitor")


@mcp.tool(annotations={"readOnlyHint": True})
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


@mcp.tool(annotations={"readOnlyHint": True})
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


@mcp.tool(annotations={"readOnlyHint": True})
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


@mcp.tool(annotations={"readOnlyHint": True})
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


@mcp.tool(annotations={"readOnlyHint": True})
def get_directory_size(path: str) -> dict:
    """
    Run du -sk on a directory and return its disk usage.
    Reports size in kilobytes (1024-byte blocks) and megabytes.
    Read-only. Returns an error key if the path is inaccessible.
    """
    import subprocess

    result = subprocess.run(
        ["du", "-sk", path],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return {"path": path, "error": result.stderr.strip()}

    line = result.stdout.strip()
    size_kb = int(line.split("\t", 1)[0])
    return {
        "path": path,
        "size_kb": size_kb,
        "size_mb": round(size_kb / 1024, 2),
    }


if __name__ == "__main__":
    mcp.run()
