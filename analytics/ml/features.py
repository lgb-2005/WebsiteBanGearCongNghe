"""Session features using only observations strictly before the first purchase.

All calendar features use UTC, independently of Django's website timezone.
The CSV path partitions complete sessions on disk before aggregation: a CSV
chunk boundary must never become an observation or label boundary.
"""

import hashlib
import json
import math
import tempfile
from pathlib import Path
from time import perf_counter

import pandas as pd

from analytics.ml.config import (
    DEFAULT_CHUNK_SIZE,
    KAGGLE_CSV_COLUMNS,
    SESSION_FEATURE_COLUMNS,
    VALID_KAGGLE_EVENT_TYPES,
)

SCHEMA_VERSION = 1
INPUT_COLUMNS = KAGGLE_CSV_COLUMNS.copy()
FEATURE_COLUMNS = SESSION_FEATURE_COLUMNS.copy()
OUTPUT_COLUMNS = ["user_session", *FEATURE_COLUMNS, "will_purchase"]
INTEGER_COLUMNS = [
    "view_count", "unique_products", "unique_categories", "cart_count",
    "remove_cart_count", "hour", "day_of_week", "is_weekend", "will_purchase",
]
FLOAT_COLUMNS = [name for name in FEATURE_COLUMNS if name not in INTEGER_COLUMNS]
EVENT_TYPES = set(VALID_KAGGLE_EVENT_TYPES)
COUNT_FIELDS = [
    "input_events", "input_sessions", "input_positive_sessions",
    "input_negative_sessions", "output_events", "output_sessions",
    "positive_sessions", "negative_sessions", "dropped_no_history_sessions",
    "leakage_events_removed",
]
CSV_DTYPES = {name: "string" for name in INPUT_COLUMNS}
# Budget applies to partition file bytes, not actual resident memory. Leave
# ample headroom for pandas datetime/groupby/copy allocations (see README).
DEFAULT_PARTITION_BYTES = 32 * 1024 * 1024


def _empty_features():
    return pd.DataFrame({
        column: pd.Series(dtype=("string" if column == "user_session" else
                                "int64" if column in INTEGER_COLUMNS else "float64"))
        for column in OUTPUT_COLUMNS
    })


def _metadata():
    return {
        **dict.fromkeys(COUNT_FIELDS, 0),
        "feature_columns": FEATURE_COLUMNS.copy(),
        "schema_version": SCHEMA_VERSION,
        "timezone": "UTC",
    }


def _validate_events(events_df):
    missing = sorted(set(INPUT_COLUMNS) - set(events_df.columns))
    if missing:
        raise ValueError(f"Missing event columns: {', '.join(missing)}")
    if not events_df.columns.is_unique:
        raise ValueError("Event columns must be unique")
    events = events_df[INPUT_COLUMNS].copy()
    if events.empty:
        return events
    for name in ("user_session", "category_code"):
        values = events[name].astype("string")
        if values.isna().any() or values.str.strip().eq("").any():
            raise ValueError(f"{name} must be non-empty")
        events[name] = values
    if not events["event_type"].isin(EVENT_TYPES).all():
        raise ValueError("event_type must be view, cart, remove_from_cart or purchase")
    for name in ("product_id", "category_id", "user_id"):
        # Parse decimal identifiers directly as int64, never via float: Kaggle
        # category IDs exceed float64's exact integer range.
        text = events[name].astype("string")
        if text.isna().any() or not text.str.fullmatch(r"[0-9]+").all():
            raise ValueError(f"{name} must contain non-negative int64 identifiers")
        try:
            events[name] = text.astype("int64")
        except (ValueError, OverflowError) as exc:
            raise ValueError(f"{name} is outside int64 range") from exc
    events["price"] = pd.to_numeric(events["price"], errors="coerce").astype("float64")
    if not events["price"].map(lambda value: math.isfinite(value) and value > 0).all():
        raise ValueError("price must be finite and greater than zero")
    try:
        events["event_time"] = pd.to_datetime(
            events["event_time"], utc=True, format="mixed", errors="raise",
        )
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("event_time must contain valid UTC timestamps") from exc
    if events["event_time"].isna().any():
        raise ValueError("event_time must not be missing")
    return events.sort_values(["user_session", "event_time"], kind="stable")


def extract_session_features_from_df(events_df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Return 14 features, session key and original purchase label, plus counts.

    Invalid preprocessed input raises ValueError. A positive session with no
    strictly earlier observations is dropped; its removed events still count.
    """
    started = perf_counter()
    events = _validate_events(events_df)
    meta = _metadata()
    meta["input_events"] = len(events)
    if events.empty:
        meta["duration_seconds"] = perf_counter() - started
        return _empty_features(), meta

    sessions = events.groupby("user_session", sort=True)
    purchases = events.loc[events["event_type"].eq("purchase")]
    first_purchase = purchases.groupby("user_session")["event_time"].min()
    meta["input_sessions"] = sessions.ngroups
    meta["input_positive_sessions"] = len(first_purchase)
    meta["input_negative_sessions"] = sessions.ngroups - len(first_purchase)
    # Reindex preserves the datetime dtype even when there are no purchases.
    cutoff = first_purchase.reindex(events["user_session"]).set_axis(events.index)
    keep = cutoff.isna() | events["event_time"].lt(cutoff)
    observed = events.loc[keep].copy()
    meta["leakage_events_removed"] = int((~keep).sum())
    meta["output_events"] = len(observed)
    meta["output_sessions"] = observed["user_session"].nunique()
    meta["dropped_no_history_sessions"] = meta["input_sessions"] - meta["output_sessions"]
    if observed.empty:
        meta["duration_seconds"] = perf_counter() - started
        return _empty_features(), meta

    for name, event_type in (
        ("view_count", "view"), ("cart_count", "cart"),
        ("remove_cart_count", "remove_from_cart"),
    ):
        observed[name] = observed["event_type"].eq(event_type).astype("int64")
    grouped = observed.groupby("user_session", sort=True)
    result = grouped.agg(
        view_count=("view_count", "sum"),
        unique_products=("product_id", "nunique"),
        unique_categories=("category_code", "nunique"),
        cart_count=("cart_count", "sum"),
        remove_cart_count=("remove_cart_count", "sum"),
        first_time=("event_time", "min"), last_time=("event_time", "max"),
        avg_price=("price", "mean"), max_price=("price", "max"),
        min_price=("price", "min"),
    )
    unique_views = observed.loc[observed["event_type"].eq("view")].groupby(
        "user_session",
    )["product_id"].nunique()
    denominator = result["view_count"].clip(lower=1)
    result["repeat_view_ratio"] = (
        (result["view_count"] - unique_views.reindex(result.index, fill_value=0)) / denominator
    ).clip(lower=0)
    result["cart_to_view_ratio"] = result["cart_count"] / denominator
    result["session_duration_sec"] = (result["last_time"] - result["first_time"]).dt.total_seconds()
    result["hour"] = result["first_time"].dt.hour
    result["day_of_week"] = result["first_time"].dt.dayofweek
    result["is_weekend"] = result["day_of_week"].isin([5, 6]).astype("int64")
    result["will_purchase"] = result.index.isin(first_purchase.index).astype("int64")
    result = result.reset_index()[OUTPUT_COLUMNS]
    result = result.astype({**dict.fromkeys(INTEGER_COLUMNS, "int64"),
                            **dict.fromkeys(FLOAT_COLUMNS, "float64"), "user_session": "string"})
    if result.isna().any().any() or not all(
        result[column].map(math.isfinite).all() for column in FLOAT_COLUMNS
    ):
        raise ValueError("Feature aggregation produced non-finite values")
    meta["positive_sessions"] = int(result["will_purchase"].sum())
    meta["negative_sessions"] = len(result) - meta["positive_sessions"]
    meta["duration_seconds"] = perf_counter() - started
    return result, meta


def _bucket(session, depth, partitions):
    digest = hashlib.blake2b(f"{depth}:{session}".encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % partitions


def _partition_csv(source, destination, chunk_size, partitions, depth):
    paths = {}
    with pd.read_csv(source, dtype=CSV_DTYPES, chunksize=chunk_size) as reader:
        for chunk in reader:
            missing = set(INPUT_COLUMNS) - set(chunk.columns)
            if missing:
                raise ValueError(f"Missing event columns: {', '.join(sorted(missing))}")
            session = chunk["user_session"]
            if session.isna().any() or session.str.strip().eq("").any():
                raise ValueError("user_session must be non-empty")
            buckets = session.map(lambda value: _bucket(value, depth, partitions))
            for number, rows in chunk.groupby(buckets, sort=True):
                path = destination / f"part-{number}.csv"
                rows[INPUT_COLUMNS].to_csv(path, mode="a", header=number not in paths, index=False)
                paths[number] = path
    return list(paths.values())


def _aggregate_partition(path, workspace, output_path, total_meta, chunk_size,
                         max_partition_bytes, depth=1):
    if path.stat().st_size > max_partition_bytes:
        if depth > 8:
            raise ValueError(
                "A session/partition exceeds the memory budget; increase "
                "max_partition_bytes only if enough RAM is available"
            )
        with tempfile.TemporaryDirectory(dir=workspace) as nested:
            subpaths = _partition_csv(path, Path(nested), chunk_size, 16, depth)
            for subpath in subpaths:
                _aggregate_partition(subpath, workspace, output_path, total_meta,
                                     chunk_size, max_partition_bytes, depth + 1)
        return
    frame, meta = extract_session_features_from_df(pd.read_csv(path, dtype=CSV_DTYPES))
    frame.to_csv(output_path, mode="a", header=False, index=False)
    for key in COUNT_FIELDS:
        total_meta[key] += meta[key]


def run_feature_extraction(input_csv_path, output_features_path, output_meta_path=None, *,
                           chunk_size=DEFAULT_CHUNK_SIZE, partitions=32,
                           max_partition_bytes=DEFAULT_PARTITION_BYTES) -> dict:
    """Extract an arbitrarily chunked CSV without splitting session histories.

    Output order follows stable hash partitions. Compare by user_session when
    changing partition counts. Atomic replacement is per file; orchestration
    must mark the complete run only after *all* outputs have been committed.
    """
    started = perf_counter()
    for name, value in (("chunk_size", chunk_size), ("partitions", partitions),
                        ("max_partition_bytes", max_partition_bytes)):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be a positive integer")
    source = Path(input_csv_path).resolve()
    output = Path(output_features_path).resolve()
    metadata_path = Path(output_meta_path).resolve() if output_meta_path is not None else None
    paths = [source, output] + ([metadata_path] if metadata_path else [])
    if len(set(paths)) != len(paths):
        raise ValueError("Input, features and metadata paths must be different")
    if output.suffix.lower() != ".csv":
        raise ValueError("Only CSV feature output is supported")
    if not source.is_file():
        raise FileNotFoundError(f"Input CSV not found: {source}")
    output.parent.mkdir(parents=True, exist_ok=True)
    if metadata_path:
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
    meta = _metadata()
    with tempfile.TemporaryDirectory(prefix="features-", dir=output.parent) as temporary:
        workspace = Path(temporary)
        staged_output = workspace / "features.csv"
        _empty_features().to_csv(staged_output, index=False)
        for path in _partition_csv(source, workspace, chunk_size, partitions, 0):
            _aggregate_partition(path, workspace, staged_output, meta, chunk_size,
                                 max_partition_bytes)
        meta.update({
            "input_csv_path": str(source), "output_features_path": str(output),
            "chunk_size": chunk_size, "partitions": partitions,
            "max_partition_bytes": max_partition_bytes,
            "duration_seconds": perf_counter() - started,
        })
        staged_output.replace(output)
        if metadata_path:
            # Create next to destination for atomic replacement on the same volume.
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".tmp",
                                             dir=metadata_path.parent, delete=False) as handle:
                staged_meta = Path(handle.name)
                try:
                    json.dump(meta, handle, indent=2, ensure_ascii=False, allow_nan=False)
                    handle.write("\n")
                except BaseException:
                    handle.close()
                    staged_meta.unlink(missing_ok=True)
                    raise
            try:
                staged_meta.replace(metadata_path)
            finally:
                staged_meta.unlink(missing_ok=True)
    return meta
