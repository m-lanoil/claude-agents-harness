#!/usr/bin/env python3
"""Read-only checks to run at the start of a docs refresh.

Usage: python3 scripts/check_docs_state.py [PATH ...]
With no paths, checks README.md, docs/OPERATOR_GUIDE.md and STATUS.md.

1. Commit hashes that do not resolve, or resolve but are not ancestors of HEAD.
2. Lines that state current state (a checklist for the reviewer, not findings).
3. Cited repo paths whose newest commit is after the target's "Last reviewed" date.

Exit 0 when checks 1 and 3 find nothing, 1 when either does, 2 on usage or git errors.
Never edits a file.
"""
import argparse
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TARGETS = ["README.md", "docs/OPERATOR_GUIDE.md", "STATUS.md"]
REFRESH_LINE = (
    "To refresh the docs, ask Claude to refresh the README, operator guide or STATUS; "
    "it follows workers/DOCS_REFRESH_PROTOCOL.md."
)

WORD_SPLIT = r"[^0-9A-Za-z_]+"
HEX_TOKEN = r"[0-9a-f]{7,40}"


def word(pattern):
    """Match pattern only where it is not glued to letters, digits or underscores."""
    return rf"(?:^|[^0-9A-Za-z_])(?:{pattern})(?:[^0-9A-Za-z_]|$)"


NUMBER = r"[0-9][0-9,]*"

# Check 2 patterns: (label, regex), matched case-insensitively. Add new state-claim patterns here.
CLAIM_PATTERNS = [
    ("N passed", word(NUMBER + " passed")),
    ("N skipped", word(NUMBER + " skipped")),
    ("N commits", word(NUMBER + " commits?")),
    ("N entries", word(NUMBER + " entr(?:y|ies)")),
    ("N tests", word(NUMBER + " tests?")),
    ("as of", word("as of")),
    ("run live / ran live", word("(?:run|ran) live")),
    ("cron", word("cron(?:tab)?")),
    ("launchd", word("launchd")),
    ("last run", word("last run")),
]

DATE = r"[0-9]{4}-[0-9]{2}-[0-9]{2}"
SECTION = r"^##+[ \t]*last reviewed(?:[^A-Za-z]|$)"
HEADING = r"^#{1,6} "
INLINE = r"last reviewed:?[ \t]+(" + DATE + ")"
TICK = r"`([^`]+)`"
LINK = r"\[[^\]]*\]\(([^) \t]+)"
TEXT_WIDTH = 100


def hash_tokens(line):
    """Whole-word tokens of 7-40 lowercase hex characters with at least one digit and one letter."""
    return [
        token
        for token in re.split(WORD_SPLIT, line)
        if re.fullmatch(HEX_TOKEN, token) and re.search("[0-9]", token) and re.search("[a-f]", token)
    ]


class GitError(Exception):
    pass


def git(root, *args):
    try:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    except OSError as exc:
        raise GitError(f"could not run git: {exc}") from exc


def require_repo(root):
    result = git(root, "rev-parse", "--verify", "--quiet", "HEAD^{commit}")
    if result.returncode != 0:
        detail = result.stderr.strip()
        raise GitError(f"{root} is not a git repository with a HEAD commit" + (f": {detail}" if detail else ""))


def resolve_commit(root, token):
    result = git(root, "rev-parse", "--verify", "--quiet", f"{token}^{{commit}}")
    return result.stdout.strip() if result.returncode == 0 else None


def is_ancestor_of_head(root, sha):
    result = git(root, "merge-base", "--is-ancestor", sha, "HEAD")
    if result.returncode in (0, 1):
        return result.returncode == 0
    raise GitError(f"git merge-base --is-ancestor {sha} HEAD failed: {result.stderr.strip()}")


def newest_commit(root, rel):
    result = git(root, "log", "-1", "--format=%cs %h", "--", rel)
    if result.returncode != 0:
        raise GitError(f"git log on {rel} failed: {result.stderr.strip()}")
    out = result.stdout.strip()
    if not out:
        return None
    day, short = out.split(" ", 1)
    return date.fromisoformat(day), short


def display(path, root):
    return path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)


def shorten(text):
    text = text.strip()
    return text if len(text) <= TEXT_WIDTH else text[: TEXT_WIDTH - 3] + "..."


# ------------------------------------------------------------------ check 1


def check_hashes(root, targets):
    cache, flagged = {}, []
    for name, lines in targets:
        for number, line in enumerate(lines, 1):
            for token in hash_tokens(line):
                if token not in cache:
                    sha = resolve_commit(root, token)
                    if sha is None:
                        cache[token] = "unknown"
                    else:
                        cache[token] = None if is_ancestor_of_head(root, sha) else "not on HEAD"
                if cache[token]:
                    flagged.append((name, number, token, cache[token]))
    return flagged


# ------------------------------------------------------------------ check 2


def check_claims(targets):
    rows = []
    for name, lines in targets:
        for number, line in enumerate(lines, 1):
            labels = [label for label, pattern in CLAIM_PATTERNS if re.search(pattern, line, re.IGNORECASE)]
            if labels:
                rows.append((name, number, labels, re.findall(DATE, line), shorten(line)))
    return rows


# ------------------------------------------------------------------ check 3


def find_last_reviewed(lines):
    for index, line in enumerate(lines):
        if re.search(SECTION, line, re.IGNORECASE):
            for following in lines[index + 1:]:
                if re.search(HEADING, following):
                    break
                for found in re.findall(DATE, following):
                    try:
                        return date.fromisoformat(found), "section"
                    except ValueError:
                        continue
    for line in lines:
        for match in re.finditer(INLINE, line, re.IGNORECASE):
            try:
                return date.fromisoformat(match.group(1)), "inline"
            except ValueError:
                continue
    return None, None


def cited_paths(target, lines, root):
    """Repo-relative paths cited in backticks or Markdown links that exist in the repo."""
    found, candidates = [], []
    for line in lines:
        candidates += [(m.group(1), (root, target.parent)) for m in re.finditer(TICK, line)]
        candidates += [(m.group(1), (target.parent, root)) for m in re.finditer(LINK, line)]
    for raw, bases in candidates:
        value = raw.strip()
        if not value or "://" in value or value.startswith(("#", "mailto:")):
            continue
        value = value.split("#", 1)[0]
        if not value:
            continue
        for base in bases:
            path = (base / value).resolve()
            if path.exists() and path != root and path != target and path.is_relative_to(root):
                rel = path.relative_to(root).as_posix()
                if rel not in found:
                    found.append(rel)
                break
    return found


def check_reviewed(root, targets):
    results = []
    for name, path, lines in targets:
        reviewed, source = find_last_reviewed(lines)
        if reviewed is None:
            results.append((name, None, None, [], [], 0))
            continue
        changed, untracked = [], []
        paths = cited_paths(path, lines, root)
        for rel in paths:
            newest = newest_commit(root, rel)
            if newest is None:
                untracked.append(rel)
            elif newest[0] > reviewed:
                changed.append((rel, newest[0].isoformat(), newest[1]))
        results.append((name, reviewed, source, changed, untracked, len(paths)))
    return results


# ------------------------------------------------------------------ main


def resolve_targets(args, root):
    """Given paths are read relative to the working directory, then the repo root; defaults to the repo root."""
    targets = []
    for arg in args or DEFAULT_TARGETS:
        candidate = Path(arg) if args else root / arg
        if not candidate.is_absolute() and not candidate.exists():
            candidate = root / arg
        if not candidate.is_file():
            raise FileNotFoundError(arg)
        targets.append(candidate.resolve())
    return targets


def report(root, files):
    texts = [(display(p, root), p, p.read_text(encoding="utf-8", errors="replace").splitlines()) for p in files]
    hashes = check_hashes(root, [(n, lines) for n, _, lines in texts])
    claims = check_claims([(n, lines) for n, _, lines in texts])
    reviewed = check_reviewed(root, texts)

    out = ["Docs state check (read-only)", f"Targets: {', '.join(n for n, _, _ in texts)}", ""]

    out.append("== Check 1: commit hashes not reachable from HEAD ==")
    out += [f"{n}:{line}  {token}  {verdict}" for n, line, token, verdict in hashes] or ["None found."]
    out.append("")

    out.append("== Check 2: state claims (checklist for the reviewer, not a finding) ==")
    out.append("These lines make claims about current state. Re-check each one by hand; being listed does not mean it is wrong.")
    for n, line, labels, dates, text in claims:
        out.append(f"{n}:{line}  [{', '.join(labels)}]  dates: {', '.join(dates) or '-'}  | {text}")
    if not claims:
        out.append("No state-claim lines found.")
    out.append("")

    out.append('== Check 3: cited paths changed after "Last reviewed" ==')
    changed_total, skipped = 0, 0
    for n, day, source, changed, untracked, checked in reviewed:
        if day is None:
            skipped += 1
            out.append(f"{n}: no Last reviewed date; check 3 skipped")
            continue
        out.append(f"{n} (Last reviewed {day.isoformat()}, {source}; {checked} cited paths checked):")
        out += [f"  {rel}  {when}  {short}" for rel, when, short in changed] or ["  None changed after that date."]
        if untracked:
            out.append(f"  Not tracked by git, not checked: {', '.join(untracked)}")
        changed_total += len(changed)
    out.append("")

    not_on_head = sum(1 for *_, v in hashes if v == "not on HEAD")
    out.append(
        f"Summary: check 1: {len(hashes)} flagged ({not_on_head} not on HEAD, {len(hashes) - not_on_head} unknown); "
        f"check 2: {len(claims)} claim lines to review (not findings); "
        f"check 3: {changed_total} cited paths changed after Last reviewed, {skipped} targets skipped."
    )
    out.append(REFRESH_LINE)
    return "\n".join(out), bool(hashes or changed_total)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only docs state checks for a docs refresh.")
    parser.add_argument("paths", nargs="*", help="markdown files to check (default: README, operator guide, STATUS)")
    args = parser.parse_args(argv)
    root = PROJECT_ROOT.resolve()
    try:
        files = resolve_targets(args.paths, root)
    except FileNotFoundError as exc:
        print(f"error: target not found: {exc}", file=sys.stderr)
        sys.exit(2)
    try:
        require_repo(root)
        text, dirty = report(root, files)
    except GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)
    print(text)
    sys.exit(1 if dirty else 0)


if __name__ == "__main__":
    main()
