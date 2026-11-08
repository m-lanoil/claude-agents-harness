#!/usr/bin/env python3
"""List quoted strings in a deliverable that do not appear in the saved sources.

Usage: python3 check_grounding.py <deliverable.md> --kb <dir> [--also <path> ...]
                                  [--ignore <file>] [--min-len 8]
Exit codes: 0 nothing unmatched, 1 unmatched quotes, 2 bad invocation.

The output is a list for human judgement, not a pass/fail verdict.
Pass only the sources the deliverable cites: a quote counts as matched if any file under
--kb contains it, so a whole kb folder lets short phrases match unrelated files. To check
against named files, point --kb at an empty directory and give each file with --also.
Not checked: attribution (who said it, or which source it came from),
paraphrase, and numbers.
"""
import argparse
import re
from pathlib import Path

DOUBLE_QUOTED = re.compile(r'"([^"]*)"')
ELLIPSIS = re.compile(r"\[\.\.\.\]|\[…\]|\.\.\.|…")
MIN_FRAGMENT = 4

# Replacements are one character for one character so line numbers survive.
QUOTE_FOLD = {"“": '"', "”": '"', "‘": "'", "’": "'", "`": "'"}

NOT_CHECKED = "attribution, paraphrase, numbers"


def fold_quotes(text):
    for old, new in QUOTE_FOLD.items():
        text = text.replace(old, new)
    return text


def collapse(text):
    return " ".join(text.split())


def normalise(text):
    return collapse(fold_quotes(text))


def blockquote_content(line):
    """Return the text after the leading '>' markers, or None if not a blockquote."""
    content = line.lstrip()
    if not content.startswith(">"):
        return None
    while content.startswith(">"):
        content = content[1:].lstrip()
    return content


def extract_quotes(text, min_len):
    """Return a list of (line_number, kind, normalised_quote), ordered by line."""
    lines = fold_quotes(text).split("\n")
    found = []
    segment, segment_start = [], 0

    def flush():
        if not segment:
            return
        joined = "\n".join(segment)
        for m in DOUBLE_QUOTED.finditer(joined):
            quote = collapse(m.group(1))
            if len(quote) >= min_len:
                line_no = segment_start + joined.count("\n", 0, m.start())
                found.append((line_no, "quote", quote))
        segment.clear()

    for number, line in enumerate(lines, start=1):
        content = blockquote_content(line)
        if content is not None:
            flush()
            quote = collapse(content)
            if quote:
                found.append((number, "blockquote", quote))
        elif line.strip():
            if not segment:
                segment_start = number
            segment.append(line)
        else:
            flush()
    flush()
    found.sort(key=lambda item: item[0])
    return found


def split_fragments(quote):
    """Split on ellipses; keep fragments of MIN_FRAGMENT or more characters."""
    parts = (collapse(p) for p in ELLIPSIS.split(quote))
    return [p for p in parts if len(p) >= MIN_FRAGMENT]


def classify(quote, sources, lowered, ignored):
    """Return (status, detail). Status: matched, case, unmatched, ignored, skipped."""
    if quote in ignored:
        return "ignored", []
    fragments = split_fragments(quote)
    if not fragments:
        return "skipped", []
    missing, case_only = [], []
    for fragment in fragments:
        if any(fragment in source for source in sources):
            continue
        low = fragment.lower()
        if any(low in source for source in lowered):
            case_only.append(fragment)
        else:
            missing.append(fragment)
    if missing:
        return "unmatched", missing
    if case_only:
        return "case", case_only
    return "matched", []


def load_sources(kb_dir, also):
    paths = sorted(kb_dir.rglob("*.md")) + list(also)
    return [normalise(p.read_text(encoding="utf-8", errors="replace")) for p in paths]


def load_ignore(path):
    text = path.read_text(encoding="utf-8", errors="replace")
    ignored = set()
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            ignored.add(normalise(stripped))
    return ignored


def check(deliverable_text, sources, ignored, min_len):
    """Return a dict of status -> list of (line, kind, quote, detail)."""
    lowered = [s.lower() for s in sources]
    results = {"matched": [], "case": [], "unmatched": [], "ignored": [], "skipped": []}
    for line_no, kind, quote in extract_quotes(deliverable_text, min_len):
        status, detail = classify(quote, sources, lowered, ignored)
        results[status].append((line_no, kind, quote, detail))
    return results


def build_report(results, source_count):
    total = sum(len(v) for v in results.values())
    out = [f"Sources read: {source_count}"]
    out.append(f"UNMATCHED ({len(results['unmatched'])})")
    for line_no, kind, quote, detail in results["unmatched"]:
        out.append(f"  line {line_no} [{kind}]: {quote}")
        if len(detail) != 1 or detail[0] != quote:
            out.extend(f"    not found: {fragment}" for fragment in detail)
    out.append(f"CASE DIFFERS ({len(results['case'])})")
    for line_no, kind, quote, detail in results["case"]:
        out.append(f"  line {line_no} [{kind}]: {quote}")
    out.append(
        f"COUNTS: {total} quotes, {len(results['matched'])} matched, "
        f"{len(results['case'])} case differs, {len(results['unmatched'])} unmatched, "
        f"{len(results['ignored'])} ignored, {len(results['skipped'])} skipped "
        f"(no fragment of {MIN_FRAGMENT}+ characters)"
    )
    out.append(f"NOT CHECKED: {NOT_CHECKED}")
    return out


def build_parser():
    parser = argparse.ArgumentParser(
        prog="check_grounding.py",
        description="List quoted strings in a deliverable that are not in the saved sources.",
    )
    parser.add_argument("deliverable", help="markdown file to check")
    parser.add_argument("--kb", required=True, help="directory searched recursively for .md sources")
    parser.add_argument("--also", action="append", default=[], help="extra source file (repeatable)")
    parser.add_argument("--ignore", help="file of exact strings to skip, one per line")
    parser.add_argument("--min-len", type=int, default=8, help="minimum quote length (default 8)")
    return parser


def main(argv=None):
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2

    deliverable = Path(args.deliverable)
    kb_dir = Path(args.kb)
    also = [Path(p) for p in args.also]
    ignore_path = Path(args.ignore) if args.ignore else None

    problems = []
    if not deliverable.is_file():
        problems.append(f"deliverable not found: {deliverable}")
    if not kb_dir.is_dir():
        problems.append(f"--kb is not a directory: {kb_dir}")
    problems.extend(f"--also is not a file: {p}" for p in also if not p.is_file())
    if ignore_path is not None and not ignore_path.is_file():
        problems.append(f"--ignore is not a file: {ignore_path}")
    if args.min_len < 1:
        problems.append("--min-len must be at least 1")
    if not problems:
        sources = load_sources(kb_dir, also)
        if not sources:
            problems.append(f"no .md sources under {kb_dir} and no --also files")
    if problems:
        for problem in problems:
            print(f"error: {problem}")
        return 2

    ignored = load_ignore(ignore_path) if ignore_path else set()
    text = deliverable.read_text(encoding="utf-8", errors="replace")
    results = check(text, sources, ignored, args.min_len)
    for line in build_report(results, len(sources)):
        print(line)
    return 1 if results["unmatched"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
