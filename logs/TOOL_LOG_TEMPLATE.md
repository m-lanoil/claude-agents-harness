# Tool Log

## Workers

| Timestamp | Worker | Tools | Mandate |
|-----------|--------|-------|---------|
| 2026-04-24 00:00:00 | `workers/developer` | `docs_fetcher`, `system_monitor` | Grounded code, sandbox scripts, ML tasks, system checks |
| 2026-04-24 00:00:00 | `workers/architect` | `docs_fetcher` | Technology selection, system architecture proposals, tradeoff analysis. No code output. |
| 2026-04-26 00:00:00 | `workers/content` | `docs_fetcher` | Research-grounded written deliverables: presentations, briefs, case studies, structured documents; document review/editing. No code output. No technology selection. |
| 2026-06-28 00:00:00 | `workers/researcher` | `docs_fetcher` | Pre-task research and planning. Produces structured planning docs: problem summary, constraints, prior art, open questions, recommended worker chain. No code output. No architecture proposals. |

## Servers

| Server | Registered | Last Audited | Log |
|--------|-----------|-------------|-----|
| `servers/docs_fetcher` | 2026-03-30 | 2026-04-30 | [logs/docs_fetcher.md](logs/docs_fetcher.md) |
| `servers/system_monitor` | 2026-04-01 | 2026-05-03 | [logs/system_monitor.md](logs/system_monitor.md) |

## Created

| Timestamp | Server | Tools | Description |
|-----------|--------|-------|-------------|
| 2026-03-30 20:56:03 | `servers/docs_fetcher` | `list_libraries`, `fetch_docs`, `fetch_url`, `add_library`, `list_clis`, `add_cli`, `list_other_sources`, `add_other_source`, `search_docs`, `crawl_docs`, `get_fetch_stats` | Fetches and caches ML/framework library docs. HTTPS-only, read-only, 8k char cap. |
| 2026-04-01 00:02:00 | `servers/system_monitor` | `get_cpu_stats`, `get_memory_stats`, `get_disk_stats`, `get_directory_size`, `scan_large_files` | Read-only Mac system monitoring via psutil. |

---

Full change history: [logs/docs_fetcher.md](logs/docs_fetcher.md) · [logs/system_monitor.md](logs/system_monitor.md) · [logs/worker_updates.md](logs/worker_updates.md)
