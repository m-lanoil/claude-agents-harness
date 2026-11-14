## Summary
<!-- One or two sentences: what this changes and why. -->

## Changes
<!-- One row per commit or logical change. -->

| Commit | Area | Change |
|---|---|---|
|  |  |  |

## Tests
<!-- What was run and the result. Give counts per suite; say which suites you did not run. -->

- `uv run python scripts/run_tests.py`:
- New or changed tests:
- Removed tests, and why:

## Not verified
<!-- Anything you could not check, and why: live or paid calls, behaviour you could not observe, CI not yet run. Write "Nothing" only if true. -->

## Review notes
<!-- Behaviour changes a reviewer should look at first, changed return shapes or signatures, and anything left out of this PR on purpose. -->

## Checklist
- [ ] `scripts/run_tests.py` passes locally, or the failures are listed above
- [ ] Each fix is its own commit with a test that fails without it
- [ ] No client details, credentials or local paths in the description, commits or files
- [ ] `README.md`, `STATUS.md` and the Track-record log are changed only with the owner's explicit approval
- [ ] Local-only state (registries, logs, outputs) is not in the diff
