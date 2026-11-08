#!/usr/bin/env python3
"""List imported modules of a project and whether a kb notes file covers them and is fresh.

Usage: python3 check_imports.py <project_dir> --kb <dir> [--alias <file>] [--max-age 30]
                                [--today YYYY-MM-DD]
Exit codes: 0 all covered and fresh, 1 any missing or stale, 2 bad invocation.

Matches each import against the `library:` line of the kb files; use an alias file
(`bs4=beautifulsoup4`) where the import name differs. Standard-library modules are not
filtered, so any without a kb file appear as MISSING. Shell command strings are not checked.
"""
import argparse
import ast
import datetime
import os
import sys

NOT_CHECKED = "NOT CHECKED: shell command strings, dynamic imports, imports in non-.py files"


def norm(s):
    return s.strip().lower().replace("-", "_")


def walk_visible(root):
    """Yield (dirpath, dirnames, filenames) skipping __pycache__ and hidden folders."""
    for dp, dns, fns in os.walk(root):
        dns[:] = sorted(d for d in dns if d != "__pycache__" and not d.startswith("."))
        yield dp, dns, sorted(fns)


def load_aliases(path):
    aliases = {}
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                raise ValueError(f"{path}:{n}: expected import_name=library")
            k, v = line.split("=", 1)
            if not k.strip() or not v.strip():
                raise ValueError(f"{path}:{n}: expected import_name=library")
            aliases[norm(k)] = norm(v)
    return aliases


def parse_frontmatter(text):
    """Return dict of frontmatter key -> value (first occurrence)."""
    lines = text.lstrip("﻿").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fm = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            k, v = line.split(":", 1)
            fm.setdefault(k.strip().lower(), v.strip())
    return fm


def load_kb(kb_dir):
    """Return {normalised library: [(relpath, date or None), ...]}."""
    kb = {}
    for dp, _, fns in os.walk(kb_dir):
        for fn in sorted(fns):
            if not fn.lower().endswith(".md"):
                continue
            p = os.path.join(dp, fn)
            try:
                with open(p, encoding="utf-8", errors="replace") as f:
                    fm = parse_frontmatter(f.read())
            except OSError:
                continue
            toks = fm.get("library", "").strip("'\" ").split()
            if not toks:
                continue
            lib = norm(toks[0].strip("'\""))
            d = None
            raw = fm.get("fetched", "").strip("'\" ")
            try:
                d = datetime.datetime.strptime(raw, "%Y-%m-%d").date()
            except ValueError:
                d = None
            kb.setdefault(lib, []).append((os.path.relpath(p, kb_dir), d))
    return kb


def find_imports(project):
    """Return ({module: (relfile, line)}, local_names, errors)."""
    py_files, local = [], set()
    for dp, dns, fns in walk_visible(project):
        local.update(norm(d) for d in dns)
        for fn in fns:
            if fn.endswith(".py"):
                py_files.append(os.path.join(dp, fn))
                local.add(norm(fn[:-3]))
    found, errors = {}, []
    for p in py_files:
        rel = os.path.relpath(p, project)
        try:
            with open(p, "rb") as f:
                tree = ast.parse(f.read(), filename=p)
        except (SyntaxError, ValueError, OSError) as e:
            errors.append(f"{rel}: {type(e).__name__}")
            continue
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            for nm in names:
                cur = found.get(nm)
                if cur is None or (rel, node.lineno) < cur:
                    found[nm] = (rel, node.lineno)
    return found, local, errors


def candidates(module, aliases):
    parts = module.split(".")
    first = norm(parts[0])
    parts = [aliases.get(first, first)] + [norm(x) for x in parts[1:]]
    return [".".join(parts[:i]) for i in range(len(parts), 0, -1)]


def classify(module, kb, aliases, today, max_age):
    for cand in candidates(module, aliases):
        if cand in kb:
            files = kb[cand]
            dates = [d for _, d in files if d is not None]
            if dates and (today - max(dates)).days <= max_age:
                return "OK", files
            return "STALE", files
    return "MISSING", []


def fmt_files(files):
    return ", ".join(f"{p} ({d.isoformat() if d else 'no date'})" for p, d in sorted(files))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("project_dir")
    ap.add_argument("--kb", required=True)
    ap.add_argument("--alias")
    ap.add_argument("--max-age", type=int, default=30)
    ap.add_argument("--today")
    args = ap.parse_args(argv)  # argparse exits 2 on bad usage

    def bad(msg):
        print(f"error: {msg}", file=sys.stderr)
        return 2

    if not os.path.isdir(args.project_dir):
        return bad(f"not a directory: {args.project_dir}")
    if not os.path.isdir(args.kb):
        return bad(f"not a directory: {args.kb}")
    today = datetime.date.today()
    if args.today:
        try:
            today = datetime.datetime.strptime(args.today, "%Y-%m-%d").date()
        except ValueError:
            return bad(f"bad --today: {args.today}")
    aliases = {}
    if args.alias:
        try:
            aliases = load_aliases(args.alias)
        except (OSError, ValueError) as e:
            return bad(str(e))

    kb = load_kb(args.kb)
    found, local, errors = find_imports(args.project_dir)
    groups = {"MISSING": [], "STALE": [], "OK": []}
    for mod in sorted(found):
        if norm(mod.split(".")[0]) in local:
            continue
        status, files = classify(mod, kb, aliases, today, args.max_age)
        rel, line = found[mod]
        text = f"  {mod}  [{rel}:{line}]"
        if files:
            text += f"  kb: {fmt_files(files)}"
        groups[status].append(text)

    for status in ("MISSING", "STALE", "OK"):
        print(f"{status} ({len(groups[status])})")
        for t in groups[status]:
            print(t)
        print()
    if errors:
        print(f"UNPARSEABLE FILES ({len(errors)})")
        for e in errors:
            print(f"  {e}")
        print()
    print(NOT_CHECKED)
    return 1 if groups["MISSING"] or groups["STALE"] else 0


if __name__ == "__main__":
    sys.exit(main())
