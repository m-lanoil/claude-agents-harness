# STATUS

> Orientation: [`README.md`](README.md). Only signals visible in tracked files and commits appear here.

## Components and maturity

| Component | Path | What it is | Maturity signal |
|---|---|---|---|
| Meta-Orchestrator rules | `CLAUDE.md` | Routing, checklist, output and security rules for the main session | Edited across the history (`git log`); length-checked by `scripts/check_markdown_length.py`; no tracked check that its rules are followed |
| Shared worker standards | `workers/WORKER_STANDARDS.md`, `workers/*_PROTOCOL.md`, `workers/WORKER_BUILDING_LOOP.md` | Security baseline and process rules every worker reads | Extracted into one file in 3da531f (per commit message); gap-fix procedure defined in `WORKER_GAP_PROTOCOL.md` |
| Developer worker | `workers/developer/` | Grounded code, sandbox scripts, ML, system checks, technical docs | Has `CLAUDE.md` plus bug-fix protocol and ML output convention |
| Architect worker | `workers/architect/CLAUDE.md` | Technology and architecture proposals, no code | `CLAUDE.md` only |
| Content worker | `workers/content/CLAUDE.md` | Research-grounded written deliverables, review | `CLAUDE.md` only; `.gitignore` reserves `workers/content/memory/` |
| Researcher worker | `workers/researcher/CLAUDE.md` | Pre-task planning docs | `CLAUDE.md` only |
| docs_fetcher server | `servers/docs_fetcher/` | 11 MCP tools: source registries, fetch, search, crawl, stats | 436-line `server.py`, `pyproject.toml`, `uv.lock`; fix commits 3d96d6b, 5247a95 (per commit messages); no tracked tests |
| system_monitor server | `servers/system_monitor/` | 5 read-only MCP tools plus 2 SessionStart hook scripts | 146-line `server.py`, `pyproject.toml`, `uv.lock`; no tracked tests |
| Coordinator | `coordinator/` | Agent SDK loop: hop sequencing, 3-part acceptance check, Validator, HITL gates | Five modules, README with flags; **disabled by standing override** in `workers/MODE_SELECTION_PROTOCOL.md`; no tracked tests |
| Pipeline | `pipeline/` | Five phase files and a run-contract spec | Phase files and `scripts/check_pipeline_run.py` exist; backfill rule added in 71b9b42 (per commit message) |
| Maintenance scripts | `scripts/` | KB staleness, server freshness, markdown length, pipeline run checks | Four scripts; weekly schedule stated in `CLAUDE.md`, cron entry not tracked |
| Onboarding templates | `*_TEMPLATE.*`, `*.template.json`, `logs/*TEMPLATE*` | Blank versions of gitignored runtime files | Present; the only tracked onboarding path (`.gitignore`) |
| Taste config | `TASTE.md` | Standing preferences read by every pipeline phase | Some items marked *(default)* = unconfirmed assumptions |

## Proven (evidence)

| Claim | Evidence |
|---|---|
| Both MCP servers exist with the tools named in the docs | `servers/docs_fetcher/server.py` (11 tools), `servers/system_monitor/server.py` (5 tools) |
| Servers are reproducibly pinned | `servers/*/uv.lock`, `servers/*/pyproject.toml` (`fastmcp>=3.2.0`) |
| A coordinator implementation exists with an automated acceptance check (file exists, required sections, self-critique present) and a read-only Validator | `coordinator/acceptance.py`, `coordinator/orchestrator.py`, `coordinator/worker_registry.py` |
| Coordinator mode is currently disabled | `workers/MODE_SELECTION_PROTOCOL.md` ("Standing override (active since 2026-09-28)") |
| All five pipeline phase files exist and define their outputs | `pipeline/phases/01_research.md` to `05_publicize.md` |
| A checker can verify a pipeline run's artifacts, ordering and the human gate | `scripts/check_pipeline_run.py` |
| Four workers are defined | `workers/{developer,architect,content,researcher}/CLAUDE.md` |
| Runtime state is excluded from version control; templates are tracked | `.gitignore`, `*_TEMPLATE.*`, `*.template.json` |
| Build-out history: 52 commits, 2026-03-30 to 2026-09-28 | `git log` (e1ed54c to 5247a95) |

## Not yet evidenced

- Outcomes of real tasks routed through any worker (no outputs, logs or run artifacts are tracked).
- Success, rejection or correction-retry rates for any worker or mode.
- Cost, token use or elapsed time per task, and the overhead of the checklist and grounding rules.
- Any end-to-end pipeline run (phases 1 to 5) completing with `Human Verdict: APPROVED`.
- That the coordinator or its Validator work on a real task (the code exists; no tracked tests or results).
- That the grounding, staleness and sandbox rules are followed: no tracked script checks compliance.
- That the weekly cron jobs are installed and running.
- Fresh-clone setup success: the setup steps in `README.md` have not been run on a fresh clone.

## Known limits

- Coordinator mode is disabled; every routed task needs a manual session in the worker directory (`workers/MODE_SELECTION_PROTOCOL.md`, `CLAUDE.md`).
- The five-phase pipeline is built but unused: `pipeline/runs/` has no runs, so its phases, run-contract checker and human-verdict gate have no evidence from real use. Kept for future buildouts (`pipeline/PIPELINE.md`, `scripts/check_pipeline_run.py`).
- Enforcement is instruction-level. Test isolation in the pipeline is a rule unless the owner adds a `Read(pipeline/runs/**/holdback/**)` deny rule (`pipeline/PIPELINE.md`).
- Workers can fetch only registered or briefed URLs; a failed fetch stops the task for a human decision (`workers/WORKER_STANDARDS.md`).
- Developer does not self-execute scripts unless the brief says so, and writes only under `sandbox/`, `kb/`, `human-retrieved-sources/` and `../../output/` (`workers/developer/CLAUDE.md`).
- Runtime state is local-only: a fresh clone has no kb, logs, outputs, registries, MCP config or hooks until set up from templates (`.gitignore`).
- Rule markdown is capped at 100 non-empty lines per file (`TASTE.md`, `scripts/check_markdown_length.py`).
- `coordinator/README.md` refers to `output/intermediate_outputs/coordinator-dev/coordinator_loop_architecture.md`, a local gitignored design doc that a fresh clone does not have (the README now says so).

## Track-record log

| Date | Task type | Worker chain | Outcome | What worked / what didn't |
|---|---|---|---|---|
| | | | | |

Entries are added only by the repo owner and must be sanitized of client details. A hop-close step should prompt adding an entry.

## Last reviewed

2026-10-06
