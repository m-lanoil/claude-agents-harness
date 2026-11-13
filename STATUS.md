# STATUS

> Orientation: [`README.md`](README.md). Only signals visible in tracked files and commits appear here.

## Components and maturity

| Component | Path | What it is | Maturity signal |
|---|---|---|---|
| Meta-Orchestrator rules | `CLAUDE.md` | Routing, checklist, output and security rules for the main session | Edited across the history (`git log`); length-checked by `scripts/check_markdown_length.py`; no tracked check that its rules are followed |
| Shared worker standards | `workers/WORKER_STANDARDS.md`, `workers/*_PROTOCOL.md`, `workers/WORKER_BUILDING_LOOP.md` | Security baseline and process rules every worker reads | Extracted into one file in 3da531f (per commit message); gap-fix procedure defined in `WORKER_GAP_PROTOCOL.md` |
| Developer worker | `workers/developer/` | Grounded code, sandbox scripts, ML, system checks, technical docs | Has `CLAUDE.md` plus bug-fix protocol and ML output convention; settings template with write-path denies and sandboxed Bash (verified live 2026-11-07) |
| Architect worker | `workers/architect/CLAUDE.md` | Technology and architecture proposals, no code | `CLAUDE.md` only; settings template with write-path denies and sandboxed Bash (verified live 2026-11-07) |
| Content worker | `workers/content/CLAUDE.md` | Research-grounded written deliverables, review | `CLAUDE.md` only; `.gitignore` reserves `workers/content/memory/`; settings template with write-path denies and sandboxed Bash (verified live 2026-11-07) |
| Researcher worker | `workers/researcher/CLAUDE.md`, `workers/RESEARCH_REPORT_PROTOCOL.md` | Pre-task planning docs; research reports from owner-approved sources (report mode) | `CLAUDE.md` plus report protocol; report mode has never run on a real task; settings template with write-path denies and sandboxed Bash (verified live 2026-11-07) |
| Scout worker | `workers/scout/CLAUDE.md` | Source discovery by web search for owner approval; no fetching | `CLAUDE.md` only; ran live in the 2026-10-22 Track-record task; whole-tool denies (WebFetch, WebSearch, Bash) and protected-path write denies verified live 2026-11-07 |
| docs_fetcher server | `servers/docs_fetcher/` | 11 MCP tools: source registries, fetch, search, crawl, stats | 538-line `server.py`, `pyproject.toml`, `uv.lock`; 9 offline test files in `tests/` (174 passed on 2026-11-07); fetch cap via `DOCS_FETCHER_MAX_URLS` (06e33f9) and the Markdown/plain-text fix (24b9a39); fix commits 3d96d6b, 5247a95 (per commit messages) |
| system_monitor server | `servers/system_monitor/` | 5 read-only MCP tools plus 2 SessionStart hook scripts | 146-line `server.py`, `pyproject.toml`, `uv.lock`; tracked offline tests for the server tools and both hook scripts (`servers/system_monitor/tests/`, 48 test functions, first run 2026-11-12: pass) |
| web_search server | `servers/web_search/` | 1 read-only MCP tool (Brave Search API), scout only | 94-line `server.py`, `pyproject.toml`, `uv.lock` (`fastmcp>=3.2.0,<4`); 29 offline checks and stdio startup without a key (per build log); no live Brave call; tracked offline tests (`servers/web_search/tests/`, 22 test functions, first run 2026-11-12: pass) |
| Coordinator | `coordinator/` | Agent SDK loop: hop sequencing, 3-part acceptance check, Validator, HITL gates | Five modules, README with flags; manual is the default, coordinator chosen per task by the owner (`workers/MODE_SELECTION_PROTOCOL.md`); 180 offline tests with a stubbed `query` (`coordinator/tests/`, 2026-11-12): blocked-fetch path, acceptance, prompts, Validator flow, multi-hop chain, registry and CLI; three live single-hop runs on 2026-11-12 (see Evidence) |
| Pipeline | `pipeline/` | Five phase files and a run-contract spec | Phase files and `scripts/check_pipeline_run.py` exist; backfill rule added in 71b9b42 (per commit message) |
| Maintenance scripts | `scripts/` | KB staleness, server freshness, markdown length, pipeline run checks, grounding quote checker, import-versus-kb checker | Six scripts; tests for the grounding, import, server-freshness and markdown-length checkers in `scripts/tests/`; no tests for `check_kb_staleness.py` or `check_pipeline_run.py`; weekly schedule stated in `CLAUDE.md`, cron entry not tracked |
| Test runner and CI | `scripts/run_tests.py`, `.github/workflows/tests.yml`, `tests/test_templates.py` | One command runs all six suites, each in its own `uv` environment; a workflow runs it on push and pull request; template tests check that config templates parse and agree with the Workers table | All six suites passed on the first owner run on 2026-11-12. The workflow passed on GitHub on 2026-11-12 (push and pull request runs on PR #3). No check that the new tests catch real bugs |
| Onboarding templates | `*_TEMPLATE.*`, `*.template.json`, `logs/*TEMPLATE*` | Blank versions of gitignored runtime files | Present; the only tracked onboarding path (`.gitignore`) |
| Taste config | `TASTE.md` | Standing preferences read by every pipeline phase | Some items marked *(default)* = unconfirmed assumptions |

## Proven (evidence)

| Claim | Evidence |
|---|---|
| The three MCP servers exist with the tools named in the docs | `servers/docs_fetcher/server.py` (11 tools), `servers/system_monitor/server.py` (5 tools), `servers/web_search/server.py` (1 tool) |
| Servers are reproducibly pinned | `servers/*/uv.lock`, `servers/*/pyproject.toml` (`fastmcp>=3.2.0,<4` in all three) |
| A coordinator implementation exists with an automated acceptance check (file exists, required sections, self-critique present) and a read-only Validator | `coordinator/acceptance.py`, `coordinator/orchestrator.py`, `coordinator/worker_registry.py` |
| Coordinator mode is available per task but lightly proven: standing override lifted 2026-11-09; 180 offline tests (stubbed `query`) pass; three live single-hop Developer runs on 2026-11-12 on internal tasks (two accepted, one wrongly failed by the acceptance check because of a path-base defect, since fixed); the blocked-fetch resume has not run live | `workers/MODE_SELECTION_PROTOCOL.md` ("Default"), `coordinator/tests/`, `logs/worker_updates.md` (2026-11-12 entries) |
| All five pipeline phase files exist and define their outputs | `pipeline/phases/01_research.md` to `05_publicize.md` |
| A checker can verify a pipeline run's artifacts, ordering and the human gate | `scripts/check_pipeline_run.py` |
| Five workers are defined | `workers/{developer,architect,content,researcher,scout}/CLAUDE.md` |
| Runtime state is excluded from version control; templates are tracked | `.gitignore`, `*_TEMPLATE.*`, `*.template.json` |
| Build-out history: 99 commits, 2026-03-30 to 2026-11-07 | `git log` (e1ed54c to 6b9261d) |
| `docs_fetcher` has offline tests | 174 passed, `servers/docs_fetcher/tests/` |
| Quote and import checkers exist with tests | `scripts/check_grounding.py`, `scripts/check_imports.py`, `scripts/tests/` |
| Write denies and sandboxed Bash blocked test writes from the worker folders | Track-record entries dated 2026-11-07 |
| Fetch cap refuses over-budget fetches | Owner-run live check, Track-record entry dated 2026-11-07 |
| Owner-reported, sanitized task outcomes | Owner's local Track-record log (not tracked) |

## Not yet evidenced

- Outcomes beyond the owner-reported Track-record entries; no outputs, logs or run artifacts are tracked, so entries cannot be re-checked from the repo.
- Success, rejection or correction-retry rates for any worker or mode.
- Cost, token use or elapsed time per task, and the overhead of the checklist and grounding rules. Owner minutes are recorded only from 2026-11-07.
- Any end-to-end pipeline run (phases 1 to 5) completing with `Human Verdict: APPROVED`.
- That the coordinator or its Validator work beyond three internal single-hop runs (2026-11-12); the Validator's behaviour on those runs was not reviewed, and the offline tests use a stubbed `query`.
- That grounding and staleness rules are followed on every task: `check_grounding.py` and `check_imports.py` run only when invoked at acceptance. Write denies, the sandbox and the fetch cap are enforced; see Known limits.
- That the weekly cron jobs are installed and running.
- Fresh-clone setup success: the setup steps in `README.md` have not been run on a fresh clone.

## Known limits

- Manual mode is the default; the coordinator is available per task and has run live on three internal single-hop tasks (2026-11-12), but its blocked-fetch resume (session ID on resume, resume prompt) is unconfirmed live (`workers/MODE_SELECTION_PROTOCOL.md`, `coordinator/README.md`).
- The five-phase pipeline is built but unused: `pipeline/runs/` has no runs, so its phases, run-contract checker and human-verdict gate have no evidence from real use. Kept for future buildouts (`pipeline/PIPELINE.md`, `scripts/check_pipeline_run.py`).
- Enforcement is mostly instruction-level. Three exceptions: write denials for protected repo paths in each worker's settings (templates tracked, live files local; verified from all five worker folders on 2026-11-07); sandboxed Bash for the four workers that have Bash (same files; verified from all four folders on 2026-11-07); and the fetch cap in `docs_fetcher`, which applies only to sessions launched with `DOCS_FETCHER_MAX_URLS`. Test isolation in the pipeline is a rule unless the owner adds a `Read(pipeline/runs/**/holdback/**)` deny rule (`pipeline/PIPELINE.md`).
- The write denials alone do not cover a Python or other subprocess write; the sandbox does (sessions in all four folders had such writes blocked with `Operation not permitted`). The sandbox does not cover the built-in file tools, MCP tools or hooks. `uv run` and network access from worker Bash are blocked unless a task adds them (the `uv` cache is outside the working folder). The escape-hatch setting (`allowUnsandboxedCommands: false`) is unproven, because the auto-mode classifier refused the retry first. `blockWritesOutsideWorkingDirectories` is not used: under Claude Code 2.1.319 it was not reopened by `additionalDirectories`.
- Workers can fetch only registered or briefed URLs; a failed fetch stops the task for a human decision (`workers/WORKER_STANDARDS.md`).
- `docs_fetcher` returns cleaned text without link targets (Track-record entries dated 2026-10-19, 2026-10-26 and 2026-11-02). A live comparison on 2026-11-07 (Claude Code 2.1.319, one fetch per URL, owner-run, local notes not tracked) found built-in WebFetch kept link URLs on a Markdown-serving page; HTML-only pages were not tested. The owner kept `docs_fetcher` as is.
- Developer does not self-execute scripts unless the brief says so, and writes only under `sandbox/`, `kb/`, `human-retrieved-sources/` and `../../output/` (`workers/developer/CLAUDE.md`).
- The scout and `web_search` chain ran live on 2026-10-22 (the search key failed first and was then fixed), and the scout's deny rules on built-in tools were verified live on 2026-11-07; key delivery in coordinator mode is unverified, and the Researcher's report mode has no real run (`workers/scout/CLAUDE.md`, `workers/RESEARCH_REPORT_PROTOCOL.md`).
- Runtime state is local-only: a fresh clone has no kb, logs, outputs, registries, MCP config or hooks until set up from templates (`.gitignore`).
- Rule markdown is capped at 100 non-empty lines per file (`TASTE.md`, `scripts/check_markdown_length.py`).

## Track-record log

Task outcomes are recorded in a local, gitignored log, `logs/TRACK_RECORD.md`. To start one, copy [`logs/TRACK_RECORD_TEMPLATE.md`](logs/TRACK_RECORD_TEMPLATE.md), which defines the columns, the field values and the rule for adding entries. Because the log is not tracked, nothing in it can be re-checked from the repo.

Maintainer's log, as of 2026-11-07: 16 sanitized, self-reported entries and 1 baseline eval. The "Evidenced" rows above that cite Track-record entries rest on this log.

Revisit: the first revisit, at 10 entries, ran on 2026-11-07 and nothing from it is open (changes are in the commit history). The next one is due when 5 baseline evals have run or the log reaches 20 entries, whichever comes first.

## Last reviewed

2026-11-07
