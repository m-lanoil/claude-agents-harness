from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent.parent
TODAY = "2026-11-07"


@pytest.fixture
def ci(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPT_DIR))
    import check_imports

    return check_imports


class Sink:
    def __init__(self):
        self.parts = []

    def write(self, text):
        self.parts.append(text)

    def text(self):
        return "".join(self.parts)


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def kb_file(kb, name, library, fetched="2026-11-01"):
    lines = ["---"]
    if library is not None:
        lines.append(f"library: {library}")
    if fetched is not None:
        lines.append(f"fetched: {fetched}")
    lines += ["---", "body"]
    return write(kb / name, "\n".join(lines) + "\n")


@pytest.fixture
def env(tmp_path):
    project = tmp_path / "project"
    kb = tmp_path / "kb"
    project.mkdir()
    kb.mkdir()
    return project, kb


def run(ci, project, kb, *extra, today=TODAY):
    sink = Sink()
    argv = [str(project), "--kb", str(kb), "--today", today, *extra]
    code = ci.main(argv, sink)
    return code, sink.text()


def section(text, name):
    """Lines listed under one heading (MISSING, STALE or OK)."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(name + " ("))
    block = []
    for line in lines[start + 1:]:
        if not line.startswith("  "):
            break
        block.append(line.strip())
    return block


def modules(text, name):
    return [line.split()[0] for line in section(text, name)]


# --- import extraction ----------------------------------------------------

def test_plain_import_listed_as_missing(ci, env):
    project, kb = env
    write(project / "a.py", "import numpy\n")
    code, text = run(ci, project, kb)
    assert code == 1
    assert modules(text, "MISSING") == ["numpy"]


def test_dotted_import_keeps_full_name(ci, env):
    project, kb = env
    write(project / "a.py", "import torch.nn.functional\n")
    _, text = run(ci, project, kb)
    assert modules(text, "MISSING") == ["torch.nn.functional"]


def test_from_import_uses_module_not_name(ci, env):
    project, kb = env
    write(project / "a.py", "from pkg_x.b import c\n")
    _, text = run(ci, project, kb)
    assert modules(text, "MISSING") == ["pkg_x.b"]


def test_import_as_uses_real_name(ci, env):
    project, kb = env
    write(project / "a.py", "import numpy as np\n")
    _, text = run(ci, project, kb)
    assert modules(text, "MISSING") == ["numpy"]


def test_one_statement_many_modules(ci, env):
    project, kb = env
    write(project / "a.py", "import numpy, pandas\n")
    _, text = run(ci, project, kb)
    assert modules(text, "MISSING") == ["numpy", "pandas"]


def test_import_inside_function_counted(ci, env):
    project, kb = env
    write(project / "a.py", "def f():\n    import numpy\n")
    _, text = run(ci, project, kb)
    assert modules(text, "MISSING") == ["numpy"]


def test_import_inside_try_counted(ci, env):
    project, kb = env
    write(project / "a.py", "try:\n    import numpy\nexcept ImportError:\n    import pandas\n")
    _, text = run(ci, project, kb)
    assert modules(text, "MISSING") == ["numpy", "pandas"]


def test_relative_imports_skipped(ci, env):
    project, kb = env
    write(project / "a.py", "from . import x\nfrom .y import z\nfrom .. import w\n")
    code, text = run(ci, project, kb)
    assert code == 0
    assert section(text, "MISSING") == []
    assert section(text, "OK") == []


def test_import_in_string_or_comment_ignored(ci, env):
    project, kb = env
    write(project / "a.py", '# import numpy\nx = "import pandas"\n')
    code, text = run(ci, project, kb)
    assert code == 0
    assert section(text, "MISSING") == []


def test_same_module_listed_once_with_earliest_location(ci, env):
    project, kb = env
    write(project / "b.py", "x = 1\nimport numpy\n")
    write(project / "a.py", "x = 1\nx = 2\nimport numpy\nimport numpy\n")
    _, text = run(ci, project, kb)
    lines = section(text, "MISSING")
    assert len(lines) == 1
    assert "first seen a.py:3" in lines[0]


def test_earlier_line_in_same_file_wins(ci, env):
    project, kb = env
    write(project / "a.py", "def f():\n    import numpy\n\nimport numpy\n")
    _, text = run(ci, project, kb)
    assert "first seen a.py:2" in section(text, "MISSING")[0]


def test_location_uses_relative_path(ci, env):
    project, kb = env
    write(project / "pkg" / "sub" / "m.py", "import numpy\n")
    _, text = run(ci, project, kb)
    assert "first seen pkg/sub/m.py:1" in section(text, "MISSING")[0]


# --- file selection -------------------------------------------------------

def test_recursive_scan(ci, env):
    project, kb = env
    write(project / "x" / "y" / "z.py", "import numpy\n")
    _, text = run(ci, project, kb)
    assert modules(text, "MISSING") == ["numpy"]


def test_pycache_skipped(ci, env):
    project, kb = env
    write(project / "__pycache__" / "a.py", "import numpy\n")
    code, text = run(ci, project, kb)
    assert code == 0
    assert section(text, "MISSING") == []


def test_hidden_folder_skipped(ci, env):
    project, kb = env
    write(project / ".venv" / "lib" / "a.py", "import numpy\n")
    code, _ = run(ci, project, kb)
    assert code == 0


def test_non_py_files_ignored(ci, env):
    project, kb = env
    write(project / "notes.md", "import numpy\n")
    write(project / "run.sh", "import numpy\n")
    code, _ = run(ci, project, kb)
    assert code == 0


def test_syntax_error_file_reported_not_fatal(ci, env):
    project, kb = env
    write(project / "bad.py", "def (:\n")
    write(project / "good.py", "import numpy\n")
    code, text = run(ci, project, kb)
    assert code == 1
    assert modules(text, "MISSING") == ["numpy"]
    assert "SKIPPED unparseable files (1): bad.py" in text


def test_empty_project_exit_zero(ci, env):
    project, kb = env
    code, text = run(ci, project, kb)
    assert code == 0
    assert "MISSING (0)" in text and "STALE (0)" in text and "OK (0)" in text


# --- local modules --------------------------------------------------------

def test_local_py_file_exempt(ci, env):
    project, kb = env
    write(project / "helpers.py", "x = 1\n")
    write(project / "main.py", "import helpers\n")
    code, text = run(ci, project, kb)
    assert code == 0
    assert "helpers" not in text.replace("helpers.py", "")


def test_local_folder_exempt(ci, env):
    project, kb = env
    write(project / "utils" / "__init__.py", "")
    write(project / "main.py", "from utils.sub import thing\n")
    code, _ = run(ci, project, kb)
    assert code == 0


def test_local_file_in_subfolder_exempt(ci, env):
    project, kb = env
    write(project / "pkg" / "helpers.py", "x = 1\n")
    write(project / "main.py", "import helpers\n")
    code, _ = run(ci, project, kb)
    assert code == 0


def test_library_named_folder_in_hidden_folder_is_not_local(ci, env):
    project, kb = env
    write(project / ".venv" / "lib" / "httpx" / "__init__.py", "")
    write(project / "main.py", "import httpx\n")
    code, text = run(ci, project, kb)
    assert code == 1
    assert modules(text, "MISSING") == ["httpx"]


def test_library_named_file_in_pycache_is_not_local(ci, env):
    project, kb = env
    write(project / "__pycache__" / "numpy.py", "x = 1\n")
    write(project / "main.py", "import numpy\n")
    _, text = run(ci, project, kb)
    assert modules(text, "MISSING") == ["numpy"]


def test_local_match_is_on_first_component(ci, env):
    project, kb = env
    write(project / "numpy_helpers.py", "x = 1\n")
    write(project / "main.py", "import numpy\n")
    _, text = run(ci, project, kb)
    assert modules(text, "MISSING") == ["numpy"]


# --- kb matching ----------------------------------------------------------

def test_covered_and_fresh_is_ok(ci, env):
    project, kb = env
    write(project / "a.py", "import numpy\n")
    kb_file(kb, "kb_numpy.md", "numpy")
    code, text = run(ci, project, kb)
    assert code == 0
    assert modules(text, "OK") == ["numpy"]
    assert "kb_numpy.md fetched 2026-11-01 (6 days)" in text


def test_submodule_matches_parent_library(ci, env):
    project, kb = env
    write(project / "a.py", "import torch.nn.functional\n")
    kb_file(kb, "kb_torch.md", "torch")
    _, text = run(ci, project, kb)
    assert modules(text, "OK") == ["torch.nn.functional"]


def test_longest_prefix_wins_over_parent(ci, env):
    project, kb = env
    write(project / "a.py", "import torch.nn.functional\n")
    kb_file(kb, "kb_torch.md", "torch", "2026-11-05")
    kb_file(kb, "kb_torch_nn.md", "torch.nn", "2026-01-01")
    _, text = run(ci, project, kb)
    assert modules(text, "STALE") == ["torch.nn.functional"]
    assert "kb_torch_nn.md" in text
    assert "kb_torch.md" not in text


def test_parent_used_when_longer_prefix_absent(ci, env):
    project, kb = env
    write(project / "a.py", "import torch.optim\n")
    kb_file(kb, "kb_torch_nn.md", "torch.nn")
    kb_file(kb, "kb_torch.md", "torch")
    _, text = run(ci, project, kb)
    assert modules(text, "OK") == ["torch.optim"]


def test_kb_library_for_submodule_does_not_cover_parent(ci, env):
    project, kb = env
    write(project / "a.py", "import torch\n")
    kb_file(kb, "kb_torch_nn.md", "torch.nn")
    _, text = run(ci, project, kb)
    assert modules(text, "MISSING") == ["torch"]


def test_case_insensitive_match(ci, env):
    project, kb = env
    write(project / "a.py", "import PIL\n")
    kb_file(kb, "kb_pillow.md", "pil")
    _, text = run(ci, project, kb)
    assert modules(text, "OK") == ["PIL"]


def test_hyphen_and_underscore_equivalent(ci, env):
    project, kb = env
    write(project / "a.py", "import claude_agent_sdk\n")
    kb_file(kb, "kb_sdk.md", "claude-agent-sdk")
    _, text = run(ci, project, kb)
    assert modules(text, "OK") == ["claude_agent_sdk"]


def test_only_first_token_of_library_used(ci, env):
    project, kb = env
    write(project / "a.py", "import pandapower\n")
    kb_file(kb, "kb_pp.md", "pandapower 3.5.6")
    _, text = run(ci, project, kb)
    assert modules(text, "OK") == ["pandapower"]


def test_second_token_does_not_match(ci, env):
    project, kb = env
    write(project / "a.py", "import installed\n")
    kb_file(kb, "kb_pp.md", "pandapower installed")
    _, text = run(ci, project, kb)
    assert modules(text, "MISSING") == ["installed"]


def test_kb_file_without_library_line_matches_nothing(ci, env):
    project, kb = env
    write(project / "a.py", "import numpy\n")
    kb_file(kb, "kb_numpy.md", None)
    _, text = run(ci, project, kb)
    assert modules(text, "MISSING") == ["numpy"]


def test_library_line_outside_frontmatter_ignored(ci, env):
    project, kb = env
    write(project / "a.py", "import numpy\n")
    write(kb / "kb_numpy.md", "# notes\nlibrary: numpy\nfetched: 2026-11-01\n")
    _, text = run(ci, project, kb)
    assert modules(text, "MISSING") == ["numpy"]


def test_kb_searched_recursively(ci, env):
    project, kb = env
    write(project / "a.py", "import numpy\n")
    kb_file(kb / "deep" / "er", "kb_numpy.md", "numpy")
    _, text = run(ci, project, kb)
    assert modules(text, "OK") == ["numpy"]


def test_non_md_kb_files_ignored(ci, env):
    project, kb = env
    write(project / "a.py", "import numpy\n")
    write(kb / "kb_numpy.txt", "---\nlibrary: numpy\nfetched: 2026-11-01\n---\n")
    _, text = run(ci, project, kb)
    assert modules(text, "MISSING") == ["numpy"]


def test_several_files_freshest_decides_and_all_listed(ci, env):
    project, kb = env
    write(project / "a.py", "import pytest\n")
    kb_file(kb, "kb_pytest_old.md", "pytest", "2026-01-01")
    kb_file(kb, "kb_pytest_new.md", "pytest", "2026-11-06")
    code, text = run(ci, project, kb)
    assert code == 0
    assert modules(text, "OK") == ["pytest"]
    assert "kb_pytest_old.md fetched 2026-01-01" in text
    assert "kb_pytest_new.md fetched 2026-11-06" in text


def test_several_files_all_old_is_stale(ci, env):
    project, kb = env
    write(project / "a.py", "import pytest\n")
    kb_file(kb, "kb_a.md", "pytest", "2026-01-01")
    kb_file(kb, "kb_b.md", "pytest", "2026-02-01")
    code, text = run(ci, project, kb)
    assert code == 1
    assert modules(text, "STALE") == ["pytest"]


def test_undated_file_does_not_hide_fresh_one(ci, env):
    project, kb = env
    write(project / "a.py", "import pytest\n")
    kb_file(kb, "kb_a.md", "pytest", None)
    kb_file(kb, "kb_b.md", "pytest", "2026-11-06")
    _, text = run(ci, project, kb)
    assert modules(text, "OK") == ["pytest"]


# --- alias file -----------------------------------------------------------

def test_alias_maps_import_name_to_library(ci, env):
    project, kb = env
    write(project / "a.py", "from bs4 import BeautifulSoup\n")
    kb_file(kb, "kb_bs.md", "beautifulsoup4")
    alias = write(project.parent / "alias.txt", "bs4=beautifulsoup4\n")
    code, text = run(ci, project, kb, "--alias", str(alias))
    assert code == 0
    assert modules(text, "OK") == ["bs4"]


def test_without_alias_bs4_is_missing(ci, env):
    project, kb = env
    write(project / "a.py", "import bs4\n")
    kb_file(kb, "kb_bs.md", "beautifulsoup4")
    _, text = run(ci, project, kb)
    assert modules(text, "MISSING") == ["bs4"]


def test_alias_applies_to_first_component_only(ci, env):
    project, kb = env
    write(project / "a.py", "import PIL.Image\n")
    kb_file(kb, "kb_pillow.md", "pillow")
    alias = write(project.parent / "alias.txt", "PIL=pillow\n")
    _, text = run(ci, project, kb, "--alias", str(alias))
    assert modules(text, "OK") == ["PIL.Image"]


def test_alias_target_can_use_longest_prefix(ci, env):
    project, kb = env
    write(project / "a.py", "import tv.models\n")
    kb_file(kb, "kb_tv.md", "torchvision", "2026-01-01")
    kb_file(kb, "kb_tvm.md", "torchvision.models", "2026-11-06")
    alias = write(project.parent / "alias.txt", "tv=torchvision\n")
    _, text = run(ci, project, kb, "--alias", str(alias))
    assert modules(text, "OK") == ["tv.models"]


def test_alias_blank_lines_and_comments_ignored(ci, env):
    project, kb = env
    write(project / "a.py", "import docx\n")
    kb_file(kb, "kb_docx.md", "python-docx")
    alias = write(project.parent / "alias.txt", "# note\n\n   \ndocx = python-docx\n")
    code, _ = run(ci, project, kb, "--alias", str(alias))
    assert code == 0


def test_alias_malformed_line_is_bad_invocation(ci, env):
    project, kb = env
    alias = write(project.parent / "alias.txt", "docx python-docx\n")
    code, _ = run(ci, project, kb, "--alias", str(alias))
    assert code == 2


def test_alias_file_missing_is_bad_invocation(ci, env):
    project, kb = env
    code, _ = run(ci, project, kb, "--alias", str(project.parent / "nope.txt"))
    assert code == 2


# --- freshness ------------------------------------------------------------

def test_exactly_thirty_days_is_fresh(ci, env):
    project, kb = env
    write(project / "a.py", "import numpy\n")
    kb_file(kb, "kb_numpy.md", "numpy", "2026-10-08")
    code, text = run(ci, project, kb)
    assert code == 0
    assert "(30 days)" in text


def test_thirty_one_days_is_stale(ci, env):
    project, kb = env
    write(project / "a.py", "import numpy\n")
    kb_file(kb, "kb_numpy.md", "numpy", "2026-10-07")
    code, text = run(ci, project, kb)
    assert code == 1
    assert modules(text, "STALE") == ["numpy"]
    assert "(31 days)" in text


def test_missing_date_is_stale(ci, env):
    project, kb = env
    write(project / "a.py", "import numpy\n")
    kb_file(kb, "kb_numpy.md", "numpy", None)
    code, text = run(ci, project, kb)
    assert code == 1
    assert modules(text, "STALE") == ["numpy"]
    assert "no valid fetched date" in text


def test_unparseable_date_is_stale(ci, env):
    project, kb = env
    write(project / "a.py", "import numpy\n")
    for bad in ("yesterday", "2026-13-40", "2026-11"):
        kb_file(kb, "kb_numpy.md", "numpy", bad)
        code, text = run(ci, project, kb)
        assert code == 1, bad
        assert modules(text, "STALE") == ["numpy"], bad


def test_max_age_override(ci, env):
    project, kb = env
    write(project / "a.py", "import numpy\n")
    kb_file(kb, "kb_numpy.md", "numpy", "2026-10-20")
    code, _ = run(ci, project, kb, "--max-age", "10")
    assert code == 1
    code, _ = run(ci, project, kb, "--max-age", "30")
    assert code == 0


def test_today_changes_result(ci, env):
    project, kb = env
    write(project / "a.py", "import numpy\n")
    kb_file(kb, "kb_numpy.md", "numpy", "2026-10-16")
    code, _ = run(ci, project, kb, today="2026-11-07")
    assert code == 0
    code, _ = run(ci, project, kb, today="2026-11-16")
    assert code == 1


def test_default_today_is_real_date(ci, env):
    project, kb = env
    write(project / "a.py", "import numpy\n")
    kb_file(kb, "kb_numpy.md", "numpy", "2000-01-01")
    sink = Sink()
    code = ci.main([str(project), "--kb", str(kb)], sink)
    assert code == 1
    assert modules(sink.text(), "STALE") == ["numpy"]


# --- output ---------------------------------------------------------------

def test_groups_counts_and_footer(ci, env):
    project, kb = env
    write(project / "a.py", "import missing_mod\nimport old_mod\nimport good_mod\nimport other_good\n")
    kb_file(kb, "kb_old.md", "old_mod", "2026-01-01")
    kb_file(kb, "kb_good.md", "good_mod")
    kb_file(kb, "kb_other.md", "other_good")
    code, text = run(ci, project, kb)
    assert code == 1
    lines = text.splitlines()
    headings = [line for line in lines if not line.startswith("  ")]
    assert headings[:3] == ["MISSING (1)", "STALE (1)", "OK (2)"]
    assert lines[-1] == (
        "NOT CHECKED: shell command strings, dynamic imports, imports in non-.py files"
    )
    assert modules(text, "MISSING") == ["missing_mod"]
    assert modules(text, "STALE") == ["old_mod"]
    assert modules(text, "OK") == ["good_mod", "other_good"]


def test_missing_line_shows_no_kb_file(ci, env):
    project, kb = env
    write(project / "a.py", "import numpy\n")
    _, text = run(ci, project, kb)
    assert "no kb file" in section(text, "MISSING")[0]


def test_nothing_written_to_project_or_kb(ci, env):
    project, kb = env
    write(project / "a.py", "import numpy\n")
    kb_file(kb, "kb_numpy.md", "numpy")
    before = sorted(str(p) for p in project.parent.rglob("*"))
    run(ci, project, kb)
    after = sorted(str(p) for p in project.parent.rglob("*"))
    assert before == after


# --- bad invocation -------------------------------------------------------

def test_project_dir_not_a_directory(ci, env):
    project, kb = env
    code, _ = run(ci, project.parent / "nope", kb)
    assert code == 2


def test_project_dir_is_a_file(ci, env):
    project, kb = env
    f = write(project / "a.py", "x = 1\n")
    code, _ = run(ci, f, kb)
    assert code == 2


def test_kb_not_a_directory(ci, env):
    project, kb = env
    code, _ = run(ci, project, kb.parent / "nope")
    assert code == 2


def test_kb_argument_required(ci, env):
    project, _ = env
    assert ci.main([str(project)], Sink()) == 2


def test_project_dir_argument_required(ci, env):
    _, kb = env
    assert ci.main(["--kb", str(kb)], Sink()) == 2


def test_bad_today_value(ci, env):
    project, kb = env
    for bad in ("11/07/2026", "2026-13-01", "today"):
        code, _ = run(ci, project, kb, today=bad)
        assert code == 2, bad


def test_non_integer_max_age(ci, env):
    project, kb = env
    code, _ = run(ci, project, kb, "--max-age", "soon")
    assert code == 2


def test_unknown_option(ci, env):
    project, kb = env
    code, _ = run(ci, project, kb, "--bogus")
    assert code == 2


# --- helpers --------------------------------------------------------------

def test_norm(ci):
    assert ci.norm(" Python-Docx ") == "python_docx"


def test_parse_date_strict(ci):
    assert ci.parse_date("2026-11-07").isoformat() == "2026-11-07"
    assert ci.parse_date(" 2026-11-07 ").isoformat() == "2026-11-07"
    assert ci.parse_date("20261107") is None
    assert ci.parse_date("2026-02-30") is None
    assert ci.parse_date("") is None
