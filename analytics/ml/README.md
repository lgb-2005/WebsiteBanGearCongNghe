# Offline purchase-intent pipeline

## Current handoff status

Khương's feature extraction and management command are implemented here.
Bảo's `config.py` and `preprocess.py` were pulled from origin/main at `ac9435c`.
Real preprocessing-to-features integration now passes, including sessions across
files/chunks. Features use the shared input/feature/event constants from config.
`report_stats.py` is still pending; the full command raises `CommandError` until
it exists, and only the full real E2E test is skipped. Test doubles verify
orchestration/report-dependent cache behavior, not full pipeline acceptance.

## Environment and verification (PowerShell)

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py check --settings=techgear.test_settings
.\.venv\Scripts\python.exe manage.py test analytics --settings=techgear.test_settings
```

The project requirements are the intended dependency versions. During initial
implementation the existing host Django was 6.0.4; a local `.venv` with access to
host packages was created and Django 6.0.6, pandas 3.1.0 and the existing
`google-genai` requirement installed. See the progress log for the
versions actually tested; do not infer a full requirements installation from it.

## Integration contract (preprocess received; reporting pending)

```python
# analytics/ml/preprocess.py
def run_preprocessing(input_paths, output_csv_path, meta_json_path,
                      chunk_size=500_000, max_chunks=None) -> dict:
    ...

# analytics/ml/report_stats.py
def run_report_stats(features_path, preprocess_meta, feature_meta,
                     output_json_path, output_md_path) -> dict:
    ...
```

Arguments carrying paths are `pathlib.Path` objects. Preprocess must concatenate
observations from all input files into the same filtered CSV; it must not split
or label sessions. `max_chunks` is a total budget across the ordered input files.
Return metadata dictionaries with JSON-serializable values. The command passes
`meta_json_path` explicitly to keep preprocessing metadata in the staging
directory, and passes `partial_run` into both metadata dictionaries before
reporting. The command rewrites artifact locations to their final destinations.

Preprocessing metadata includes `total_raw_rows`, `dropped_non_target_category`,
`dropped_invalid_rows`, `valid_filtered_rows`, `event_distribution`,
`chunks_processed`, `per_file_stats`, distinct-product/brand counts and timing.
Its row counts reconcile as raw = non-target + invalid + valid.

Filtered events must have exactly these columns in order:

```text
event_time,event_type,product_id,category_id,category_code,brand,price,user_id,user_session
```

- Timestamps: parseable UTC or timezone-aware values; naive values are treated as
  UTC. Website timezone settings do not affect these calculations.
- Event type: `view`, `cart`, `remove_from_cart`, `purchase`.
- Identifiers: non-negative int64, not floating point identifiers (large Kaggle
  category IDs must not lose precision).
- Price: finite and greater than zero. Session/category code: non-null and
  non-blank. Brand may be missing.
- Category filtering follows `TARGET_CATEGORY_CODES` and
  `TARGET_CATEGORY_PREFIXES` in `config.py`: `computers.` and
  `electronics.audio.` prefixes, plus the explicit codes. Categories, event types,
  brands and session whitespace are normalized; missing brands become `unknown`.
- If filtering leaves no rows, still write the header.
- Preserve all valid event histories across chunks/files. Do not silently remove
  duplicates without an agreed business rule.
- Reporting must write a JSON object and non-empty Markdown at the supplied paths,
  and identify partial runs. Report numbers must reconcile with feature metadata.
- Output paths supplied to stages are temporary staging paths. Do not embed them
  as persistent artifact locations in the final report. Use logical filenames or
  the final feature location provided by `feature_meta['output_features_path']`.

The command commits the final manifest only after all stages return and their
outputs have been validated. Failed runs have no reusable completion manifest.

Integration fixes in the received preprocessor keep IDs as decimal text while
reading, reject fractional/negative/out-of-range IDs and non-finite prices, and
preserve timestamp fractional seconds. These avoid precision loss and changes
to strict purchase cutoffs. Missing schema/invalid bounds and source/output path
collisions fail explicitly. No new deduplication rule was added.

## Verified real-data smoke (first two stages)

The local plan contains a rerunnable check:

```powershell
.\.venv\Scripts\python.exe .md_plan/smoke_preprocess_features.py
```

It reads only two 10,000-row chunks from October, writes to
`dataset_trainmodel/pipeline_output/preprocess_features_smoke/`, validates the
16-column feature schema and reconciles row/session counts. On 04/11/2026:
20,000 raw rows, 1,689 filtered rows, 535 retained sessions, 19 positive labels
and 27 cutoff events; 1.063 seconds, peak process working set 81.01 MiB on this
host. These measurements include the first two stages, not reporting, and are
not an estimate of full-data runtime/RAM. The local smoke script uses Windows
process memory counters. Its `validation_summary.json` is a check record, not
`pipeline_stats_report.json`, and no completed pipeline manifest is emitted.

The local plan and smoke script are intentionally ignored by Git. For tracked
code use the APIs above; the script is a local verification convenience.

## Features and semantics

`features.py` exposes `INPUT_COLUMNS`, `FEATURE_COLUMNS`, `OUTPUT_COLUMNS` and
the required two functions:

```python
from analytics.ml.features import (
    extract_session_features_from_df,
    run_feature_extraction,
)

features_df, metadata = extract_session_features_from_df(clean_events_df)
metadata = run_feature_extraction(
    "filtered_events.csv", "session_features.csv", "feature_meta.json",
    chunk_size=500_000,
)
```

There are **14 feature columns**, since the assignment's item 13 includes both
`day_of_week` and `is_weekend`. Together with `user_session` and `will_purchase`
the output has 16 columns. The complete ordered schema is `OUTPUT_COLUMNS`.

Labels are computed before removing events at or after the first purchase.
Positive sessions with zero earlier observations are dropped. `avg_price` is an
event-weighted average. Unique viewed products only include `view` events;
`unique_products` includes all retained events. Ratios use `max(view_count, 1)`;
cart/view may exceed 1. A one-event duration is 0 seconds. UTC determines the
calendar features, with Monday=0 and weekend in {5, 6}.

Input validation raises `ValueError` rather than silently cleaning invalid
preprocessed input. The DataFrame passed by the caller is never modified.

Metadata reconciles as follows:

```text
input_events = output_events + leakage_events_removed
input_sessions = output_sessions + dropped_no_history_sessions
output_sessions = positive_sessions + negative_sessions
```

The event removal count includes purchase events, same-time observations and
later events, even for sessions dropped due to missing pre-purchase history.

## Large files

CSV extraction uses stable hash partitioning of complete sessions on disk,
then aggregates each partition. Never aggregate arbitrary CSV chunks separately.
`chunk_size`, `partitions` and `max_partition_bytes` are keyword-only tuning
options on `run_feature_extraction`. Default partition budget: 32 MiB of CSV
bytes; this is **not** a hard RAM cap. Parsing, sorting and groupby require more
memory. Choose chunk size and partition budget after measuring the target host.

Oversized partitions are repartitioned up to eight times; an oversized single
session fails explicitly. Temporary directories are cleaned on success/failure.
Features are written to a staged file then replaced atomically; the metadata
file is replaced separately. Consumers needing multi-file consistency must use
the command's completed manifest. Output row order is partition order; compare
by `user_session` across different partition counts.

## Full command (after Bảo's integration)

```powershell
# Requires both 2019-Oct.csv and 2019-Nov.csv under dataset_trainmodel.
.\.venv\Scripts\python.exe manage.py run_data_pipeline

# Partial smoke run; automatically uses a separate smoke directory/report.
.\.venv\Scripts\python.exe manage.py run_data_pipeline --input dataset_trainmodel/2019-Oct.csv --chunk-size 10000 --max-chunks 2

# Test set is a separate invocation/destination, never appended to training.
.\.venv\Scripts\python.exe manage.py run_data_pipeline --input dataset_trainmodel/2019-Dec.csv --output-dir dataset_trainmodel/pipeline_output/test --report-md dataset_trainmodel/pipeline_output/test/rp_03_pipeline_stats.md
```

`--input` accepts multiple paths; absent it, both training months are required.
`--force` recomputes results. Cache reuse requires matching source size/mtime,
parameters, code fingerprints, report path and output file size/mtime. This does
not hash the entire multi-GB input. Keep input files immutable while running;
use `--force` if they may have changed without size/mtime changes. A leftover
`.pipeline.lock` after a killed process must be inspected before manually
removing it; normal failures clean it automatically.

Partial and full runs cannot reuse the same completed output directory, even
with `--force`. The partial report must not target the default full report.
Limited chunks may omit future purchases and truncate sessions, so partial
results are for smoke verification only. December data, cross-split session
overlap and observation-window censoring need validation before model training.
