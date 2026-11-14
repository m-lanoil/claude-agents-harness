import subprocess

from mcp_helpers import call_tool
from test_system_monitor_server import fake_run_factory

NO_OUTPUT = "du produced no usable output"


def run_tool(monkeypatch, path, **run_kwargs):
    monkeypatch.setattr(subprocess, "run", fake_run_factory([], **run_kwargs))
    return call_tool("get_directory_size", {"path": str(path)}).data


def test_nonzero_exit_with_parseable_stdout_returns_partial_total_and_warning(monkeypatch, tmp_path):
    warning = f"du: {tmp_path}/locked: Permission denied"

    data = run_tool(monkeypatch, tmp_path, returncode=1, stdout=f"2932\t{tmp_path}\n", stderr=warning + "\n")

    assert data == {
        "path": str(tmp_path),
        "size_kb": 2932,
        "size_mb": round(2932 / 1024, 2),
        "partial": True,
        "warning": warning,
    }


def test_nonzero_exit_with_unparseable_stdout_returns_the_stderr_as_error(monkeypatch, tmp_path):
    data = run_tool(monkeypatch, tmp_path, returncode=1, stdout="not a number\tx\n", stderr="du: boom\n")

    assert data == {"path": str(tmp_path), "error": "du: boom"}


def test_zero_exit_with_garbage_stdout_returns_error_instead_of_raising(monkeypatch, tmp_path):
    data = run_tool(monkeypatch, tmp_path, returncode=0, stdout="garbage\tx\n", stderr="")

    assert data == {"path": str(tmp_path), "error": NO_OUTPUT}


def test_zero_exit_with_empty_stdout_returns_the_fixed_message(monkeypatch, tmp_path):
    data = run_tool(monkeypatch, tmp_path, returncode=0, stdout="", stderr="")

    assert data == {"path": str(tmp_path), "error": NO_OUTPUT}


def test_nonzero_exit_with_empty_stdout_and_empty_stderr_returns_the_fixed_message(monkeypatch, tmp_path):
    data = run_tool(monkeypatch, tmp_path, returncode=1, stdout="", stderr="")

    assert data == {"path": str(tmp_path), "error": NO_OUTPUT}


def test_successful_run_has_no_partial_or_warning_key(monkeypatch, tmp_path):
    data = run_tool(monkeypatch, tmp_path, returncode=0, stdout=f"3072\t{tmp_path}\n", stderr="")

    assert data == {"path": str(tmp_path), "size_kb": 3072, "size_mb": 3.0}
    assert "partial" not in data and "warning" not in data
