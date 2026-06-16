# ML Test Output Convention

Every test script in this sandbox writes outputs into a versioned `output/run_YYYY-MM-DD_NNN/` subdirectory.
Run directories are never overwritten — each execution gets a fresh one.

## Directory layout

```
<script_dir>/
└── output/
    ├── run_2026-06-11_001/   ← first run on 2026-06-11 (or migrated legacy files)
    ├── run_2026-06-11_002/
    └── run_2026-06-11_003/
```

No files are written directly into `output/`.

## Run-number resolution

Get today's date as `YYYY-MM-DD`. Scan `output/` for directories whose name starts with
`run_YYYY-MM-DD_` (today's date prefix) and whose suffix is all digits. Take the max numeric
suffix and increment by 1. If none exist for today, start at 1. Zero-pad to three digits.
Counter resets each day.

```python
def _next_run_dir(base_out_dir):
    base_out_dir.mkdir(exist_ok=True)
    today = datetime.date.today().isoformat()
    prefix = f"run_{today}_"
    existing = [
        d for d in base_out_dir.iterdir()
        if d.is_dir() and d.name.startswith(prefix) and d.name[len(prefix):].isdigit()
    ]
    next_n = max((int(d.name[len(prefix):]) for d in existing), default=0) + 1
    run_dir = base_out_dir / f"{prefix}{next_n:03d}"
    run_dir.mkdir()
    return run_dir
```

## Migration of legacy outputs

If a script previously wrote files directly into `output/` (before this convention), wrap them
into `run_YYYY-MM-DD_001/` (today's date) on the next run. Skip if any `run_*` directory
already exists.

```python
def _migrate_legacy_outputs(base_out_dir):
    if not base_out_dir.exists():
        return
    if any(d.is_dir() and d.name.startswith("run_") for d in base_out_dir.iterdir()):
        return
    loose_files = [f for f in base_out_dir.iterdir() if f.is_file()]
    if not loose_files:
        return
    today = datetime.date.today().isoformat()
    run_001 = base_out_dir / f"run_{today}_001"
    run_001.mkdir()
    for f in loose_files:
        f.rename(run_001 / f.name)
```

Call `_migrate_legacy_outputs` at program start, before `_next_run_dir`. Both functions require
`datetime.date` in addition to `pathlib.Path` — no additional imports beyond these two.

## When to create a run directory

| Execution type | Create run dir? |
|---|---|
| Batch evaluation | Always |
| Single-image with `--save` | Yes |
| Single-image without `--save` | No — no files produced |

## Worked example — output/ after three batch runs

```
output/
├── run_2026-06-11_001/
│   ├── eval_metrics.json
│   └── confusion_matrix.png
├── run_2026-06-11_002/
│   ├── eval_metrics.json
│   └── confusion_matrix.png
└── run_2026-06-11_003/
    ├── eval_metrics.json
    └── confusion_matrix.png
```
