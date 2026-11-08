#!/usr/bin/env python3
"""List the modules a project imports and whether a kb file covers each one.

Usage: python3 check_imports.py <project_dir> --kb <dir> [--alias <file>]
                                [--max-age 30] [--today YYYY-MM-DD]
Exit codes: 0 all covered and fresh, 1 any missing or stale, 2 bad invocation.
The output is a list for human judgement; it writes only to stdout.
Use an alias file (`bs4=beautifulsoup4`) where the import name differs from the kb library
name. Standard-library modules are not filtered, so any without a kb file appear as MISSING.
Shell command strings are not checked.
"""
import argparse
import ast
import datetime as dt
import re
from pathlib import Path

DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
NOT_CHECKED = "NOT CHECKED: shell command strings, dynamic imports, imports in non-.py files"


def norm(name):
    """Normalise a module or library name for comparison."""
    return name.strip().lower().replace("-", "_")


def parse_date(text):
    """Return a date for a strict YYYY-MM-DD string, else None."""
    text = text.strip()
    if not DATE_RE.fullmatch(text):
        return None
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        return None


def parse_frontmatter(text):
    """Return (library_key, fetched_date) from a kb file's leading --- block.

    library_key is the normalised first token of the library: value, or None.
    fetched_date is a date or None when missing or unparseable.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, None
    library = None
    fetched = None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line.startswith("library:"):
            tokens = line[len("library:"):].split()
            if tokens:
                library = norm(tokens[0])
        elif line.startswith("fetched:"):
            fetched = parse_date(line[len("fetched:"):])
    return library, fetched


def load_kb(kb_dir):
    """Map normalised library key -> list of (path, fetched_date)."""
    kb = {}
    for path in sorted(kb_dir.rglob("*.md")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except ValueError:
            continue
        library, fetched = parse_frontmatter(text)
        if library:
            kb.setdefault(library, []).append((path, fetched))
    return kb


def load_alias(alias_path):
    """Parse import_name=library lines. Raise ValueError on a malformed line."""
    alias = {}
    for number, raw in enumerate(alias_path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, library = line.partition("=")
        if not sep or not name.strip() or not library.strip():
            raise ValueError(f"{alias_path}:{number}: expected import_name=library")
        alias[norm(name)] = norm(library)
    return alias


def rel_parts(path, root):
    return path.parts[len(root.parts):]


def python_files(root):
    """Every .py under root, skipping __pycache__ and hidden folders."""
    files = []
    for path in root.rglob("*.py"):
        if not path.is_file():
            continue
        folders = rel_parts(path, root)[:-1]
        if any(part == "__pycache__" or part.startswith(".") for part in folders):
            continue
        files.append(path)
    return sorted(files, key=lambda p: "/".join(rel_parts(p, root)))


def local_names(root):
    """Normalised names of every <name>.py file and <name>/ folder under root, skipping __pycache__ and hidden folders."""
    names = set()
    for path in root.rglob("*"):
        if any(part == "__pycache__" or part.startswith(".") for part in rel_parts(path, root)):
            continue
        if path.is_dir():
            names.add(norm(path.name))
        elif path.suffix == ".py":
            names.add(norm(path.stem))
    return names


def collect_imports(root):
    """Return (first_seen, skipped).

    first_seen maps dotted module -> (relative file, line) of its earliest sighting.
    skipped lists relative paths of files that could not be read or parsed.
    """
    first_seen = {}
    skipped = []
    for path in python_files(root):
        rel = "/".join(rel_parts(path, root))
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        except (SyntaxError, ValueError):
            skipped.append(rel)
            continue
        for node in ast.walk(tree):
            found = []
            if isinstance(node, ast.Import):
                found = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                found = [node.module]
            for module in found:
                seen = (rel, node.lineno)
                if module not in first_seen or seen < first_seen[module]:
                    first_seen[module] = seen
    return first_seen, skipped


def match_files(module, kb, alias):
    """kb entries for the longest dotted prefix of module that has any, else []."""
    parts = module.split(".")
    head = norm(parts[0])
    if head in alias:
        parts = [alias[head]] + parts[1:]
    for size in range(len(parts), 0, -1):
        key = norm(".".join(parts[:size]))
        if key in kb:
            return kb[key]
    return []


def classify(entries, today, max_age):
    """Return (status, details) for one module's matching kb entries."""
    if not entries:
        return "MISSING", "no kb file"
    dated = [d for _, d in entries if d is not None]
    details = []
    for path, fetched in entries:
        if fetched is None:
            details.append(f"{path.name} (no valid fetched date)")
        else:
            details.append(f"{path.name} fetched {fetched.isoformat()} ({(today - fetched).days} days)")
    if dated and (today - max(dated)).days <= max_age:
        return "OK", "; ".join(details)
    return "STALE", "; ".join(details)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="check_imports.py",
        description="List imported modules and whether a fresh kb file covers each.",
    )
    parser.add_argument("project_dir")
    parser.add_argument("--kb", dest="kb", required=True)
    parser.add_argument("--alias", dest="alias", default=None)
    parser.add_argument("--max-age", dest="max_age", type=int, default=30)
    parser.add_argument("--today", dest="today", default=None)
    return parser


def main(argv=None, out=None):
    """Run the check and return the exit code. out defaults to stdout."""
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        root = Path(args.project_dir)
        kb_dir = Path(args.kb)
        if not root.is_dir():
            parser.error(f"project_dir is not a directory: {root}")
        if not kb_dir.is_dir():
            parser.error(f"--kb is not a directory: {kb_dir}")
        today = dt.date.today()
        if args.today is not None:
            today = parse_date(args.today)
            if today is None:
                parser.error(f"--today must be YYYY-MM-DD: {args.today}")
        alias = {}
        if args.alias is not None:
            alias_path = Path(args.alias)
            if not alias_path.is_file():
                parser.error(f"--alias is not a file: {alias_path}")
            try:
                alias = load_alias(alias_path)
            except ValueError as exc:
                parser.error(str(exc))
    except SystemExit as exc:
        return exc.code

    kb = load_kb(kb_dir)
    local = local_names(root)
    first_seen, skipped = collect_imports(root)

    groups = {"MISSING": [], "STALE": [], "OK": []}
    for module in sorted(first_seen):
        if norm(module.split(".")[0]) in local:
            continue
        status, details = classify(match_files(module, kb, alias), today, args.max_age)
        where = f"{first_seen[module][0]}:{first_seen[module][1]}"
        groups[status].append(f"  {module}  (first seen {where})  {details}")

    for status in ("MISSING", "STALE", "OK"):
        print(f"{status} ({len(groups[status])})", file=out)
        for line in groups[status]:
            print(line, file=out)
    if skipped:
        print(f"SKIPPED unparseable files ({len(skipped)}): " + ", ".join(skipped), file=out)
    print(NOT_CHECKED, file=out)

    return 1 if groups["MISSING"] or groups["STALE"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
