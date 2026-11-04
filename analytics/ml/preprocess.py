import json
import time
from pathlib import Path
from typing import Iterable

import pandas as pd

from analytics.ml.config import (
    DEFAULT_CHUNK_SIZE,
    FILTERED_TRAIN_EVENTS_PATH,
    KAGGLE_CSV_COLUMNS,
    PREPROCESS_META_PATH,
    TARGET_CATEGORY_CODES,
    TARGET_CATEGORY_PREFIXES,
    VALID_KAGGLE_EVENT_TYPES,
)


def is_target_category(series: pd.Series) -> pd.Series:
    if series.empty:
        return pd.Series(dtype=bool, index=series.index)
    normalized = series.fillna("").astype(str).str.strip().str.lower()
    mask = normalized.isin(TARGET_CATEGORY_CODES)
    for prefix in TARGET_CATEGORY_PREFIXES:
        mask = mask | normalized.str.startswith(prefix)
    return mask


def _identifier_values(series: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Validate int64 identifiers as decimal text, without a float round trip."""
    text = series.astype("string").str.strip()
    canonical = text.str.lstrip("0").replace("", "0")
    maximum = str(2**63 - 1)
    valid = (
        text.str.fullmatch(r"[0-9]+", na=False)
        & ((canonical.str.len() < len(maximum))
           | ((canonical.str.len() == len(maximum)) & (canonical <= maximum)))
    ).fillna(False)
    return canonical, valid


def clean_event_chunk(chunk: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    missing = sorted(set(KAGGLE_CSV_COLUMNS) - set(chunk.columns))
    if missing:
        raise ValueError(f"Missing event columns: {', '.join(missing)}")
    total_rows = int(len(chunk))
    if total_rows == 0:
        return chunk.copy(), {
            "total_raw_rows": 0,
            "dropped_non_target_category": 0,
            "dropped_invalid_rows": 0,
            "valid_filtered_rows": 0,
        }

    category_mask = is_target_category(chunk["category_code"])
    target_df = chunk.loc[category_mask].copy()
    dropped_non_target = total_rows - int(len(target_df))

    if target_df.empty:
        return target_df, {
            "total_raw_rows": total_rows,
            "dropped_non_target_category": dropped_non_target,
            "dropped_invalid_rows": 0,
            "valid_filtered_rows": 0,
        }

    target_df["price"] = pd.to_numeric(target_df["price"], errors="coerce")
    id_mask = pd.Series(True, index=target_df.index)
    for column in ("product_id", "category_id", "user_id"):
        values, valid = _identifier_values(target_df[column])
        target_df[column] = values
        id_mask &= valid

    session_str = target_df["user_session"].fillna("").astype(str).str.strip()
    event_time_str = target_df["event_time"].fillna("").astype(str).str.strip()
    event_type_str = target_df["event_type"].fillna("").astype(str).str.strip().str.lower()

    valid_mask = (
        (session_str != "")
        & (session_str.str.lower() != "nan")
        & (event_time_str != "")
        & event_type_str.isin(VALID_KAGGLE_EVENT_TYPES)
        & target_df["price"].notna()
        & (target_df["price"] > 0)
        & (target_df["price"] < float("inf"))
        & id_mask
    )

    before_clean_len = int(len(target_df))
    cleaned_df = target_df.loc[valid_mask].copy()

    parsed_time = pd.to_datetime(cleaned_df["event_time"], utc=True, format="mixed", errors="coerce")
    time_valid_mask = parsed_time.notna()
    cleaned_df = cleaned_df.loc[time_valid_mask].copy()
    parsed_time = parsed_time.loc[time_valid_mask]

    dropped_invalid = before_clean_len - int(len(cleaned_df))

    if not cleaned_df.empty:
        # Preserve fractional seconds: rounding here changes the strict cutoff.
        cleaned_df["event_time"] = parsed_time.astype("string")
        cleaned_df["event_type"] = cleaned_df["event_type"].astype(str).str.strip().str.lower()
        cleaned_df["product_id"] = cleaned_df["product_id"].astype("int64")
        cleaned_df["category_id"] = cleaned_df["category_id"].astype("int64")
        cleaned_df["category_code"] = cleaned_df["category_code"].astype(str).str.strip().str.lower()
        brand_series = cleaned_df["brand"].fillna("").astype(str).str.strip().str.lower()
        cleaned_df["brand"] = brand_series.replace({"": "unknown", "nan": "unknown"})
        cleaned_df["price"] = cleaned_df["price"].astype("float64")
        cleaned_df["user_id"] = cleaned_df["user_id"].astype("int64")
        cleaned_df["user_session"] = cleaned_df["user_session"].astype(str).str.strip()
        cleaned_df = cleaned_df[KAGGLE_CSV_COLUMNS]

    return cleaned_df, {
        "total_raw_rows": total_rows,
        "dropped_non_target_category": dropped_non_target,
        "dropped_invalid_rows": dropped_invalid,
        "valid_filtered_rows": int(len(cleaned_df)),
    }


def run_preprocessing(
    input_paths: Iterable[Path | str] | Path | str,
    output_csv_path: Path | str = FILTERED_TRAIN_EVENTS_PATH,
    meta_json_path: Path | str = PREPROCESS_META_PATH,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    max_chunks: int | None = None,
) -> dict:
    for name, value in (("chunk_size", chunk_size), ("max_chunks", max_chunks)):
        if name == "max_chunks" and value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be a positive integer")
    if isinstance(input_paths, (str, Path)):
        paths = [Path(input_paths)]
    else:
        paths = [Path(p) for p in input_paths]

    output_path = Path(output_csv_path)
    meta_path = Path(meta_json_path)
    resolved_paths = [path.resolve() for path in paths]
    if not paths or len(set(resolved_paths)) != len(resolved_paths):
        raise ValueError("Provide at least one distinct input CSV")
    if output_path.resolve() == meta_path.resolve() or any(
        path in (output_path.resolve(), meta_path.resolve()) for path in resolved_paths
    ):
        raise ValueError("Input, filtered CSV and metadata paths must be different")
    for csv_path in paths:
        if not csv_path.is_file():
            raise FileNotFoundError(f"Không tìm thấy file CSV đầu vào: {csv_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.parent.mkdir(parents=True, exist_ok=True)

    if output_path.exists():
        output_path.unlink()

    start_time = time.perf_counter()

    total_raw_rows = 0
    dropped_non_target_category = 0
    dropped_invalid_rows = 0
    valid_filtered_rows = 0
    chunks_processed = 0

    event_counts = {evt: 0 for evt in VALID_KAGGLE_EVENT_TYPES}
    category_counts: dict[str, int] = {}
    unique_products: set[int] = set()
    unique_brands: set[str] = set()
    per_file_stats: list[dict] = []

    wrote_header = False

    for csv_path in paths:
        if not csv_path.exists():
            raise FileNotFoundError(f"Không tìm thấy file CSV đầu vào: {csv_path}")

        file_start = time.perf_counter()
        file_raw = 0
        file_dropped_cat = 0
        file_dropped_invalid = 0
        file_valid = 0
        file_chunks = 0

        reader = pd.read_csv(
            csv_path,
            chunksize=chunk_size,
            dtype={
                "event_time": "string",
                "event_type": "string",
                "product_id": "string",
                "category_id": "string",
                "user_id": "string",
                "category_code": "string",
                "brand": "string",
                "user_session": "string",
            },
            low_memory=False,
        )

        for chunk in reader:
            cleaned_df, stats = clean_event_chunk(chunk)

            total_raw_rows += stats["total_raw_rows"]
            dropped_non_target_category += stats["dropped_non_target_category"]
            dropped_invalid_rows += stats["dropped_invalid_rows"]
            valid_filtered_rows += stats["valid_filtered_rows"]

            file_raw += stats["total_raw_rows"]
            file_dropped_cat += stats["dropped_non_target_category"]
            file_dropped_invalid += stats["dropped_invalid_rows"]
            file_valid += stats["valid_filtered_rows"]

            chunks_processed += 1
            file_chunks += 1

            if not cleaned_df.empty:
                cleaned_df.to_csv(
                    output_path,
                    mode="a",
                    index=False,
                    header=not wrote_header,
                )
                wrote_header = True

                vc_events = cleaned_df["event_type"].value_counts()
                for evt_name, count in vc_events.items():
                    event_counts[str(evt_name)] = event_counts.get(str(evt_name), 0) + int(count)

                vc_cats = cleaned_df["category_code"].value_counts()
                for cat_name, count in vc_cats.items():
                    category_counts[str(cat_name)] = category_counts.get(str(cat_name), 0) + int(count)

                unique_products.update(cleaned_df["product_id"].unique().tolist())
                unique_brands.update(cleaned_df["brand"].unique().tolist())

            if max_chunks is not None and chunks_processed >= max_chunks:
                break

        per_file_stats.append(
            {
                "file_name": csv_path.name,
                "file_size_mb": round(csv_path.stat().st_size / (1024 * 1024), 2),
                "chunks_processed": file_chunks,
                "total_raw_rows": file_raw,
                "dropped_non_target_category": file_dropped_cat,
                "dropped_invalid_rows": file_dropped_invalid,
                "valid_filtered_rows": file_valid,
                "elapsed_seconds": round(time.perf_counter() - file_start, 2),
            }
        )

        if max_chunks is not None and chunks_processed >= max_chunks:
            break

    if not wrote_header:
        pd.DataFrame(columns=KAGGLE_CSV_COLUMNS).to_csv(output_path, index=False)

    elapsed_seconds = round(time.perf_counter() - start_time, 2)
    output_size_mb = round(output_path.stat().st_size / (1024 * 1024), 2) if output_path.exists() else 0.0

    top_categories = dict(
        sorted(category_counts.items(), key=lambda item: item[1], reverse=True)[:15]
    )

    meta = {
        "input_files": [p.name for p in paths],
        "per_file_stats": per_file_stats,
        "chunk_size": chunk_size,
        "chunks_processed": chunks_processed,
        "total_raw_rows": total_raw_rows,
        "dropped_non_target_category": dropped_non_target_category,
        "dropped_invalid_rows": dropped_invalid_rows,
        "valid_filtered_rows": valid_filtered_rows,
        "retention_rate_pct": round(
            (valid_filtered_rows / total_raw_rows * 100.0) if total_raw_rows > 0 else 0.0,
            4,
        ),
        "event_distribution": event_counts,
        "unique_products": len(unique_products),
        "unique_brands": len(unique_brands - {"unknown"}),
        "top_categories": top_categories,
        "output_csv_path": str(output_path),
        "output_size_mb": output_size_mb,
        "elapsed_seconds": elapsed_seconds,
    }

    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return meta
