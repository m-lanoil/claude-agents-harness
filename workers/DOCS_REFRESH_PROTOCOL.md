# Docs Refresh Protocol

Used by: Meta-Orchestrator
Triggered when: the owner asks to refresh, update or audit `README.md`, `docs/OPERATOR_GUIDE.md` and/or `STATUS.md`.

## Scope
Targets are `README.md`, `docs/OPERATOR_GUIDE.md` and `STATUS.md`. Other rule markdown (`CLAUDE.md`, `workers/`, `pipeline/`, `TASTE.md`) is not audited for its rules, but any file the two docs cite is checked for its claims about current state: counts, dates, schedules, run history, "has run" or "has not run". Logs are history and are not checked. If the owner asks for a sweep, grep all tracked rule markdown for such state claims too.

## Steps (in order)
1. **Open PRs.** Run `gh pr list`; for each open PR, diff its README, STATUS and cited-file changes against main. Settle merge order with the owner before editing, so the refresh does not collide with them.
2. **Facts.** Start by running `python3 scripts/check_docs_state.py`: it flags commit hashes not on HEAD and cited files changed after "Last reviewed", and lists state-claim lines to re-check (a checklist, not findings). Then re-derive every measurable claim: commit count and first and last hash, test counts (run `scripts/run_tests.py`), log entry counts, tool and script counts, line counts, scheduler state (`launchctl list`, `crontab -l`), alert and log dates. Mark each as re-run today or taken from a file.
3. **Prose.** Read every section against the rule files it cites, not only against its own numbers, and against its other sections. Look for contradictions, decisions shown as open that are settled, citations pointing at the wrong section, and cited rule files whose state claims disagree with the docs. Check that costs and gates describe the current rules. Then list the rule changes since "Last reviewed" (`git log` on `CLAUDE.md` and `workers/*.md` since that date) and ask of each whether `README.md` or `STATUS.md` should cover it; this catches omissions that a read of the docs alone does not.
4. **Flags.** For each "unverified" or "not evidenced" statement, check whether files or logs now settle it. Say whether it is settled on the owner's machine only or on a fresh clone.
5. **Report before editing.** Give findings with their source, then a list of what this pass did not check. Never call the findings complete without that list. End with an edit list covering every finding: file, current text, proposed text, and whether it is checked against a file or run, or the orchestrator's judgment. Do not ask the owner whether to detail a category.
6. **Edit.** Only with the owner's explicit approval (`CLAUDE.md`). Advance "Last reviewed" only if steps 1 to 4 all ran. Log fixes to other rule files in `logs/worker_updates.md`.
