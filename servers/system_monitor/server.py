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


if __name__ == "__main__":
    mcp.run()
