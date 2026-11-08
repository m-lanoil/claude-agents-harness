import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "check_imports.py"
sys.path.insert(0, str(SCRIPT.parent))
import check_imports as ci  # noqa: E402

TODAY = "2026-11-07"


def w(path, text=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def kbfile(kb, name, lib, fetched=None):
    fm = ["---"]
    if lib is not None:
        fm.append(f"library: {lib}")
    if fetched is not None:
        fm.append(f"fetched: {fetched}")
    fm.append("---\nbody\n")
    w(kb / name, "\n".join(fm))


@pytest.fixture
def env(tmp_path):
    proj, kb = tmp_path / "proj", tmp_path / "kb"
    proj.mkdir()
    kb.mkdir()
    return proj, kb


def run(proj, kb, *extra, today=TODAY):
    return ci.main([str(proj), "--kb", str(kb), "--today", today, *extra])


def out_of(capsys, proj, kb, *extra):
    code = run(proj, kb, *extra)
    return code, capsys.readouterr().out


def test_all_ok_exit0(env, capsys):
    proj, kb = env
    w(proj / "a.py", "import numpy\n")
    kbfile(kb, "n.md", "numpy", "2026-11-01")
    code, out = out_of(capsys, proj, kb)
    assert code == 0
    assert "OK (1)" in out and "MISSING (0)" in out and "STALE (0)" in out
    assert out.strip().endswith(ci.NOT_CHECKED)


def test_missing_exit1(env, capsys):
    proj, kb = env
    w(proj / "a.py", "import requests\n")
    code, out = out_of(capsys, proj, kb)
    assert code == 1
    assert "MISSING (1)" in out and "requests  [a.py:1]" in out


def test_stale_boundary(env, capsys):
    proj, kb = env
    w(proj / "a.py", "import x1\nimport x2\n")
    kbfile(kb, "1.md", "x1", "2026-10-08")  # exactly 30 days -> fresh
    kbfile(kb, "2.md", "x2", "2026-10-07")  # 31 days -> stale
    code, out = out_of(capsys, proj, kb)
    assert code == 1
    assert "STALE (1)" in out and "OK (1)" in out
    assert out.index("STALE") < out.index("x2") < out.index("OK (1)") < out.index("x1")


def test_max_age_option(env, capsys):
    proj, kb = env
    w(proj / "a.py", "import x1\n")
    kbfile(kb, "1.md", "x1", "2026-10-30")
    assert run(proj, kb, "--max-age", "5") == 1
    capsys.readouterr()
    assert run(proj, kb, "--max-age", "10") == 0


@pytest.mark.parametrize("fetched", [None, "garbage", "2026-13-45"])
def test_missing_or_bad_date_is_stale(env, capsys, fetched):
    proj, kb = env
    w(proj / "a.py", "import x1\n")
    kbfile(kb, "1.md", "x1", fetched)
    code, out = out_of(capsys, proj, kb)
    assert code == 1 and "STALE (1)" in out and "no date" in out


def test_freshest_file_wins_and_all_listed(env, capsys):
    proj, kb = env
    w(proj / "a.py", "import PIL\n")
    kbfile(kb, "sub/old.md", "pillow", "2025-01-01")
    kbfile(kb, "new.md", "pillow 10.0", "2026-11-01")
    code, out = out_of(capsys, proj, kb, *[])  # no alias: PIL != pillow
    assert "MISSING (1)" in out
    a = kb.parent / "alias.txt"
    a.write_text("# c\n\nPIL=pillow\n")
    code, out = out_of(capsys, proj, kb, "--alias", str(a))
    assert code == 0
    assert "2025-01-01" in out and "2026-11-01" in out


def test_alias_dotted_import(env, capsys):
    proj, kb = env
    w(proj / "a.py", "from PIL.Image import open\n")
    kbfile(kb, "p.md", "pillow", "2026-11-01")
    a = kb.parent / "alias.txt"
    a.write_text("pil = Pillow\n")
    code, out = out_of(capsys, proj, kb, "--alias", str(a))
    assert code == 0 and "PIL.Image" in out


def test_longest_prefix_first(env, capsys):
    proj, kb = env
    w(proj / "a.py", "import torch.nn.functional\n")
    kbfile(kb, "t.md", "torch", "2026-11-01")
    kbfile(kb, "tnn.md", "torch.nn", "2020-01-01")
    code, out = out_of(capsys, proj, kb)
    assert "STALE (1)" in out and "tnn.md" in out and "t.md" not in out.replace("tnn.md", "")


def test_prefix_falls_back_to_shorter(env, capsys):
    proj, kb = env
    w(proj / "a.py", "import torch.nn.functional\n")
    kbfile(kb, "t.md", "torch", "2026-11-01")
    assert run(proj, kb) == 0


def test_normalisation_and_first_token(env, capsys):
    proj, kb = env
    w(proj / "a.py", "import Python_Docx\nimport pandapower\n")
    kbfile(kb, "d.md", "python-docx", "2026-11-01")
    kbfile(kb, "p.md", "pandapower 3.5.6", "2026-11-01")
    assert run(proj, kb) == 0


def test_alias_bs4(env, capsys):
    proj, kb = env
    w(proj / "a.py", "from bs4 import BeautifulSoup\n")
    kbfile(kb, "b.md", "beautifulsoup4", "2026-11-01")
    a = kb.parent / "al"
    a.write_text("bs4=beautifulsoup4\n")
    assert run(proj, kb, "--alias", str(a)) == 0


def test_imports_in_functions_try_and_relative_skipped(env, capsys):
    proj, kb = env
    w(proj / "a.py", "def f():\n    import inner\ntry:\n    import opt\nexcept ImportError:\n    pass\nfrom . import rel\nfrom .x import y\n")
    code, out = out_of(capsys, proj, kb)
    assert "inner  [a.py:2]" in out and "opt  [a.py:4]" in out
    assert "rel" not in out.split("NOT CHECKED")[0].replace("MISSING", "")


def test_local_module_and_folder_exempt(env, capsys):
    proj, kb = env
    w(proj / "a.py", "import helpers\nimport pkg.sub\nimport deepmod\nimport deepdir\n")
    w(proj / "x" / "helpers.py")
    w(proj / "x" / "pkg" / "sub.py")
    w(proj / "y" / "deepmod.py")
    (proj / "z" / "deepdir").mkdir(parents=True)
    code, out = out_of(capsys, proj, kb)
    assert code == 0 and "MISSING (0)" in out


def test_skip_hidden_and_pycache(env, capsys):
    proj, kb = env
    w(proj / ".venv" / "a.py", "import hidden\n")
    w(proj / "__pycache__" / "b.py", "import cached\n")
    w(proj / "ok.py", "x = 1\n")
    code, out = out_of(capsys, proj, kb)
    assert code == 0 and "hidden" not in out and "cached" not in out


def test_first_seen_location(env, capsys):
    proj, kb = env
    w(proj / "b.py", "x=1\nimport dup\n")
    w(proj / "a.py", "\n\nimport dup\n")
    code, out = out_of(capsys, proj, kb)
    assert "dup  [a.py:3]" in out


def test_kb_without_library_matches_nothing_and_recursive(env, capsys):
    proj, kb = env
    w(proj / "a.py", "import foo\n")
    kbfile(kb, "n.md", None, "2026-11-01")
    w(kb / "plain.md", "no frontmatter\nlibrary: foo\n")
    w(kb / "d" / "e" / "x.txt", "---\nlibrary: foo\n---\n")
    assert run(proj, kb) == 1
    capsys.readouterr()
    kbfile(kb, "deep/er/f.md", "foo", "2026-11-01")
    assert run(proj, kb) == 0


def test_syntax_error_reported_not_crash(env, capsys):
    proj, kb = env
    w(proj / "bad.py", "def (:\n")
    code, out = out_of(capsys, proj, kb)
    assert "UNPARSEABLE" in out and "bad.py" in out


def test_bad_invocations_exit2(env, tmp_path):
    proj, kb = env
    assert ci.main([str(tmp_path / "nope"), "--kb", str(kb)]) == 2
    assert ci.main([str(proj), "--kb", str(tmp_path / "nope")]) == 2
    assert ci.main([str(proj), "--kb", str(kb), "--today", "bad"]) == 2
    assert ci.main([str(proj), "--kb", str(kb), "--alias", str(tmp_path / "nope")]) == 2
    a = tmp_path / "al"
    a.write_text("noequals\n")
    assert ci.main([str(proj), "--kb", str(kb), "--alias", str(a)]) == 2
    with pytest.raises(SystemExit) as e:
        ci.main([str(proj)])  # --kb missing
    assert e.value.code == 2


def test_cli_subprocess_stdout_only(env):
    proj, kb = env
    w(proj / "a.py", "import numpy\n")
    kbfile(kb, "n.md", "numpy", "2026-11-01")
    r = subprocess.run([sys.executable, str(SCRIPT), str(proj), "--kb", str(kb), "--today", TODAY],
                       capture_output=True, text=True)
    assert r.returncode == 0 and r.stderr == "" and "OK (1)" in r.stdout
