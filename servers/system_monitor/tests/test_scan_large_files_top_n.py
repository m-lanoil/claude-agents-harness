from mcp_helpers import call_tool

MB = 1024 ** 2


def make_three_files(tmp_path):
    for index in range(1, 4):
        (tmp_path / f"f{index}.bin").write_bytes(b"\0" * (index * MB))


def test_negative_top_n_is_rejected_with_an_error_key(tmp_path):
    make_three_files(tmp_path)
    data = call_tool("scan_large_files", {"root_dir": str(tmp_path), "top_n": -1, "min_size_mb": 1}).data
    assert data["root_dir"] == str(tmp_path)
    assert "top_n" in data["error"]
    assert "results" not in data and "total_found" not in data


def test_zero_top_n_keeps_returning_no_results_with_the_total(tmp_path):
    make_three_files(tmp_path)
    data = call_tool("scan_large_files", {"root_dir": str(tmp_path), "top_n": 0, "min_size_mb": 1}).data
    assert data["total_found"] == 3
    assert data["results"] == []
