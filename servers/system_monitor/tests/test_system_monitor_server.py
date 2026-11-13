import subprocess
from datetime import datetime
from types import SimpleNamespace

import psutil
import pytest

from conftest import GB, MB, partition
from mcp_helpers import call_tool, list_tool_names


def test_server_exposes_the_five_documented_tools():
    assert sorted(list_tool_names()) == [
        "get_cpu_stats",
        "get_directory_size",
        "get_disk_stats",
        "get_memory_stats",
        "scan_large_files",
    ]


# ------------------------------------------------------------------------ cpu


def test_get_cpu_stats_reports_totals_per_core_and_frequency(monkeypatch):
    def fake_cpu_percent(interval=None, percpu=False):
        return [10.0, 30.0] if percpu else 20.0

    monkeypatch.setattr(psutil, "cpu_percent", fake_cpu_percent)
    monkeypatch.setattr(psutil, "cpu_count", lambda logical=True: 8 if logical else 4)
    monkeypatch.setattr(psutil, "cpu_freq", lambda percpu=False: SimpleNamespace(current=2400.0, min=800.0, max=3500.0))

    data = call_tool("get_cpu_stats").data

    assert data["cpu_percent"] == 20.0
    assert data["cpu_percent_per_core"] == [10.0, 30.0]
    assert data["logical_cores"] == 8
    assert data["physical_cores"] == 4
    assert data["cpu_freq_mhz"] == {"current": 2400.0, "min": 800.0, "max": 3500.0}


def test_get_cpu_stats_frequency_is_none_when_unavailable(monkeypatch):
    monkeypatch.setattr(psutil, "cpu_percent", lambda interval=None, percpu=False: [1.0] if percpu else 1.0)
    monkeypatch.setattr(psutil, "cpu_count", lambda logical=True: 2)
    monkeypatch.setattr(psutil, "cpu_freq", lambda percpu=False: None)

    assert call_tool("get_cpu_stats").data["cpu_freq_mhz"] is None


# --------------------------------------------------------------------- memory


def test_get_memory_stats_maps_ram_and_swap_fields(monkeypatch):
    monkeypatch.setattr(
        psutil,
        "virtual_memory",
        lambda: SimpleNamespace(total=16 * GB, available=6 * GB, used=9 * GB, free=1 * GB, percent=62.5),
    )
    monkeypatch.setattr(
        psutil, "swap_memory", lambda: SimpleNamespace(total=4 * GB, used=1 * GB, free=3 * GB, percent=25.0)
    )

    data = call_tool("get_memory_stats").data

    assert data["virtual_memory"] == {
        "total": 16 * GB,
        "available": 6 * GB,
        "used": 9 * GB,
        "free": 1 * GB,
        "percent": 62.5,
    }
    assert data["swap_memory"] == {"total": 4 * GB, "used": 1 * GB, "free": 3 * GB, "percent": 25.0}


# ----------------------------------------------------------------------- disk


def test_get_disk_stats_lists_partitions_and_skips_unreadable_ones(monkeypatch):
    parts = [partition("/"), partition("/Volumes/Gone"), partition("/Volumes/Backup")]
    usages = {
        "/": SimpleNamespace(total=100, used=40, free=60, percent=40.0),
        "/Volumes/Backup": SimpleNamespace(total=200, used=150, free=50, percent=75.0),
    }

    def fake_usage(path):
        if path not in usages:
            raise OSError("not mounted")
        return usages[path]

    monkeypatch.setattr(psutil, "disk_partitions", lambda all=False: parts)
    monkeypatch.setattr(psutil, "disk_usage", fake_usage)

    result = call_tool("get_disk_stats").data["partitions"]

    assert [p["mountpoint"] for p in result] == ["/", "/Volumes/Backup"]
    assert result[0] == {
        "device": "/dev/disk3s1",
        "mountpoint": "/",
        "fstype": "apfs",
        "total_bytes": 100,
        "used_bytes": 40,
        "free_bytes": 60,
        "percent_used": 40.0,
    }


def test_get_disk_stats_asks_for_physical_partitions_only(monkeypatch):
    asked = []

    def fake_partitions(all=False):
        asked.append(all)
        return []

    monkeypatch.setattr(psutil, "disk_partitions", fake_partitions)

    assert call_tool("get_disk_stats").data == {"partitions": []}
    assert asked == [False]


# ------------------------------------------------------------ scan_large_files


def write_bytes(path, size):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\0" * size)
    return path


def test_scan_large_files_sorts_descending_and_applies_size_floor(tmp_path):
    write_bytes(tmp_path / "small.bin", MB // 2)
    write_bytes(tmp_path / "two.bin", 2 * MB)
    write_bytes(tmp_path / "nested" / "deep" / "three.bin", 3 * MB)

    data = call_tool("scan_large_files", {"root_dir": str(tmp_path), "min_size_mb": 1}).data

    assert data["root_dir"] == str(tmp_path)
    assert data["min_size_mb"] == 1
    assert data["total_found"] == 2
    assert [r["size_bytes"] for r in data["results"]] == [3 * MB, 2 * MB]
    assert [r["size_mb"] for r in data["results"]] == [3.0, 2.0]
    assert data["results"][0]["path"] == str(tmp_path / "nested" / "deep" / "three.bin")


def test_scan_large_files_size_floor_is_inclusive(tmp_path):
    write_bytes(tmp_path / "exact.bin", MB)

    data = call_tool("scan_large_files", {"root_dir": str(tmp_path), "min_size_mb": 1}).data

    assert data["total_found"] == 1


def test_scan_large_files_top_n_truncates_results_but_not_the_total(tmp_path):
    for index in range(1, 5):
        write_bytes(tmp_path / f"f{index}.bin", index * MB)

    data = call_tool("scan_large_files", {"root_dir": str(tmp_path), "top_n": 2, "min_size_mb": 1}).data

    assert data["total_found"] == 4
    assert [r["size_bytes"] for r in data["results"]] == [4 * MB, 3 * MB]


def test_scan_large_files_skips_symlinked_files_and_directories(tmp_path):
    real = write_bytes(tmp_path / "real" / "big.bin", 2 * MB)
    (tmp_path / "file_link.bin").symlink_to(real)
    (tmp_path / "dir_link").symlink_to(tmp_path / "real", target_is_directory=True)

    data = call_tool("scan_large_files", {"root_dir": str(tmp_path), "min_size_mb": 1}).data

    assert data["total_found"] == 1
    assert data["results"][0]["path"] == str(real)


def test_scan_large_files_reports_iso_modification_time(tmp_path):
    write_bytes(tmp_path / "big.bin", 2 * MB)

    data = call_tool("scan_large_files", {"root_dir": str(tmp_path), "min_size_mb": 1}).data

    assert isinstance(datetime.fromisoformat(data["results"][0]["last_modified"]), datetime)


def test_scan_large_files_empty_or_missing_root_returns_no_results(tmp_path):
    empty = call_tool("scan_large_files", {"root_dir": str(tmp_path), "min_size_mb": 1}).data
    missing = call_tool("scan_large_files", {"root_dir": str(tmp_path / "missing"), "min_size_mb": 1}).data

    assert empty["total_found"] == 0 and empty["results"] == []
    assert missing["total_found"] == 0 and missing["results"] == []


# ---------------------------------------------------------- get_directory_size


def fake_run_factory(calls, returncode=0, stdout="", stderr=""):
    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    return fake_run


def test_get_directory_size_parses_du_output_in_kb_and_mb(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(subprocess, "run", fake_run_factory(calls, stdout=f"3072\t{tmp_path}\n"))

    data = call_tool("get_directory_size", {"path": str(tmp_path)}).data

    assert data == {"path": str(tmp_path), "size_kb": 3072, "size_mb": 3.0}
    assert calls[0][0] == ["du", "-sk", str(tmp_path)]


def test_get_directory_size_rounds_megabytes_to_two_places(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run", fake_run_factory([], stdout="1500\tx\n"))

    assert call_tool("get_directory_size", {"path": str(tmp_path)}).data["size_mb"] == 1.46


def test_get_directory_size_returns_error_key_when_du_fails(monkeypatch, tmp_path):
    message = "du: cannot access: No such file or directory"
    monkeypatch.setattr(subprocess, "run", fake_run_factory([], returncode=1, stderr=message + "\n"))

    data = call_tool("get_directory_size", {"path": str(tmp_path)}).data

    assert data == {"path": str(tmp_path), "error": message}


def test_get_directory_size_real_du_on_a_missing_path_reports_an_error(tmp_path):
    data = call_tool("get_directory_size", {"path": str(tmp_path / "missing")}).data

    assert "error" in data and "size_kb" not in data


def test_get_directory_size_real_du_on_a_real_directory_is_self_consistent(tmp_path):
    write_bytes(tmp_path / "a.bin", 64 * 1024)

    data = call_tool("get_directory_size", {"path": str(tmp_path)}).data

    assert isinstance(data["size_kb"], int) and data["size_kb"] >= 0
    assert data["size_mb"] == round(data["size_kb"] / 1024, 2)
