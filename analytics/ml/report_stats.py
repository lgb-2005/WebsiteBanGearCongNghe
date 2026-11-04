import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from analytics.ml.config import (
    ARTIFACTS_DIR,
    FEATURE_META_PATH,
    MARKDOWN_REPORT_PATH,
    PIPELINE_STATS_REPORT_PATH,
    PREPROCESS_META_PATH,
    PREPROCESS_TEST_META_PATH,
    SESSION_FEATURE_COLUMNS,
    SESSION_FEATURES_PATH,
    SESSION_TEST_FEATURES_PATH,
    TARGET_LABEL_COLUMN,
    VALID_KAGGLE_EVENT_TYPES,
)

FEATURE_TEST_META_PATH = ARTIFACTS_DIR / "feature_test_meta.json"


def _compute_feature_summary(features_df: pd.DataFrame) -> dict[str, dict[str, dict[str, float]]]:
    summary: dict[str, dict[str, dict[str, float]]] = {}
    if features_df.empty or TARGET_LABEL_COLUMN not in features_df.columns:
        return summary

    groups = {
        "all": features_df,
        "non_purchase_0": features_df.loc[features_df[TARGET_LABEL_COLUMN] == 0],
        "purchase_1": features_df.loc[features_df[TARGET_LABEL_COLUMN] == 1],
    }

    for col in SESSION_FEATURE_COLUMNS:
        if col not in features_df.columns:
            continue
        col_stats: dict[str, dict[str, float]] = {}
        for group_name, sub_df in groups.items():
            series = pd.to_numeric(sub_df[col], errors="coerce").dropna()
            if series.empty:
                col_stats[group_name] = {
                    "mean": 0.0,
                    "std": 0.0,
                    "median": 0.0,
                    "p95": 0.0,
                    "max": 0.0,
                }
            else:
                col_stats[group_name] = {
                    "mean": round(float(series.mean()), 4),
                    "std": round(float(series.std(ddof=0)), 4),
                    "median": round(float(series.median()), 4),
                    "p95": round(float(np.percentile(series, 95)), 4),
                    "max": round(float(series.max()), 4),
                }
        summary[col] = col_stats

    return summary


def _build_report_dict(
    preprocess_meta: dict,
    features_df: pd.DataFrame | None = None,
    feature_meta: dict | None = None,
) -> dict:
    feat_meta_data = feature_meta or {}

    total_raw = int(preprocess_meta.get("total_raw_rows", 0))
    dropped_cat = int(preprocess_meta.get("dropped_non_target_category", 0))
    dropped_inv = int(preprocess_meta.get("dropped_invalid_rows", 0))
    valid_rows = int(preprocess_meta.get("valid_filtered_rows", 0))
    partial_run = bool(preprocess_meta.get("partial_run", feat_meta_data.get("partial_run", False)))

    funnel_table = {
        "total_raw_rows": total_raw,
        "dropped_non_target_category": dropped_cat,
        "dropped_non_target_pct": round((dropped_cat / total_raw * 100.0) if total_raw > 0 else 0.0, 4),
        "dropped_invalid_rows": dropped_inv,
        "dropped_invalid_pct": round((dropped_inv / total_raw * 100.0) if total_raw > 0 else 0.0, 4),
        "valid_filtered_rows": valid_rows,
        "retention_rate_pct": round((valid_rows / total_raw * 100.0) if total_raw > 0 else 0.0, 4),
        "output_size_mb": preprocess_meta.get("output_size_mb", 0.0),
        "elapsed_seconds": preprocess_meta.get("elapsed_seconds", 0.0),
        "input_files": preprocess_meta.get("input_files", []),
        "per_file_stats": preprocess_meta.get("per_file_stats", []),
        "partial_run": partial_run,
    }

    raw_event_dist = preprocess_meta.get("event_distribution", {})
    event_distribution = {}
    for evt in VALID_KAGGLE_EVENT_TYPES:
        cnt = int(raw_event_dist.get(evt, 0))
        event_distribution[evt] = {
            "count": cnt,
            "pct": round((cnt / valid_rows * 100.0) if valid_rows > 0 else 0.0, 4),
        }

    dropped_no_hist = int(
        feat_meta_data.get(
            "dropped_no_history_sessions",
            feat_meta_data.get("dropped_purchase_only_sessions", 0),
        )
    )

    session_stats = {
        "available": False,
        "total_sessions": 0,
        "input_sessions": int(feat_meta_data.get("input_sessions", 0)),
        "purchase_sessions": 0,
        "non_purchase_sessions": 0,
        "conversion_rate_pct": 0.0,
        "imbalance_ratio_text": "N/A",
        "leakage_events_removed": int(feat_meta_data.get("leakage_events_removed", 0)),
        "dropped_purchase_only_sessions": dropped_no_hist,
        "dropped_no_history_sessions": dropped_no_hist,
        "duration_seconds": round(float(feat_meta_data.get("duration_seconds", 0.0)), 2),
    }
    feature_summary: dict[str, dict[str, dict[str, float]]] = {}

    if features_df is not None and TARGET_LABEL_COLUMN in features_df.columns:
        total_sessions = int(len(features_df))
        purchase_sessions = int((features_df[TARGET_LABEL_COLUMN] == 1).sum())
        non_purchase_sessions = total_sessions - purchase_sessions
        conv_rate = round(
            (purchase_sessions / total_sessions * 100.0) if total_sessions > 0 else 0.0,
            4,
        )
        ratio_str = (
            f"1 : {round(non_purchase_sessions / purchase_sessions, 2)}"
            if purchase_sessions > 0
            else "N/A"
        )
        session_stats = {
            "available": True,
            "total_sessions": total_sessions,
            "input_sessions": int(feat_meta_data.get("input_sessions", total_sessions + dropped_no_hist)),
            "purchase_sessions": purchase_sessions,
            "non_purchase_sessions": non_purchase_sessions,
            "conversion_rate_pct": conv_rate,
            "imbalance_ratio_text": ratio_str,
            "leakage_events_removed": int(feat_meta_data.get("leakage_events_removed", 0)),
            "dropped_purchase_only_sessions": dropped_no_hist,
            "dropped_no_history_sessions": dropped_no_hist,
            "duration_seconds": round(float(feat_meta_data.get("duration_seconds", 0.0)), 2),
        }
        if not features_df.empty:
            feature_summary = _compute_feature_summary(features_df)

    return {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "partial_run": partial_run,
        "data_filtering_funnel": funnel_table,
        "event_distribution": event_distribution,
        "unique_products": int(preprocess_meta.get("unique_products", 0)),
        "unique_brands": int(preprocess_meta.get("unique_brands", 0)),
        "top_categories": preprocess_meta.get("top_categories", {}),
        "session_class_imbalance": session_stats,
        "feature_summary": feature_summary,
    }


def run_report_stats(
    features_path: Path | str,
    preprocess_meta: dict,
    feature_meta: dict,
    output_json_path: Path | str = PIPELINE_STATS_REPORT_PATH,
    output_md_path: Path | str = MARKDOWN_REPORT_PATH,
) -> dict:
    if not isinstance(preprocess_meta, dict):
        raise ValueError("preprocess_meta must be a dict")
    if not isinstance(feature_meta, dict):
        raise ValueError("feature_meta must be a dict")

    feat_csv = Path(features_path)
    if not feat_csv.is_file():
        raise FileNotFoundError(f"Không tìm thấy file session_features.csv tại: {feat_csv}")

    features_df = pd.read_csv(feat_csv)
    report = _build_report_dict(
        preprocess_meta=preprocess_meta,
        features_df=features_df,
        feature_meta=feature_meta,
    )

    out_json = Path(output_json_path)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )

    if output_md_path is not None:
        md_content = render_markdown_report(report)
        out_md = Path(output_md_path)
        out_md.parent.mkdir(parents=True, exist_ok=True)
        out_md.write_text(md_content, encoding="utf-8")

    return report


def build_pipeline_stats_report(
    preprocess_meta_path: Path | str = PREPROCESS_META_PATH,
    features_csv_path: Path | str | None = SESSION_FEATURES_PATH,
    feature_meta_path: Path | str | None = FEATURE_META_PATH,
    test_preprocess_meta_path: Path | str | None = PREPROCESS_TEST_META_PATH,
    test_features_csv_path: Path | str | None = SESSION_TEST_FEATURES_PATH,
    test_feature_meta_path: Path | str | None = FEATURE_TEST_META_PATH,
    output_json_path: Path | str = PIPELINE_STATS_REPORT_PATH,
    output_markdown_path: Path | str = MARKDOWN_REPORT_PATH,
) -> dict:
    pre_meta_file = Path(preprocess_meta_path)
    if not pre_meta_file.exists():
        raise FileNotFoundError(f"Không tìm thấy file preprocess_meta.json tại: {pre_meta_file}")

    preprocess_meta = json.loads(pre_meta_file.read_text(encoding="utf-8"))

    feat_meta_data = {}
    if feature_meta_path is not None and Path(feature_meta_path).exists():
        feat_meta_data = json.loads(Path(feature_meta_path).read_text(encoding="utf-8"))

    features_df = None
    if features_csv_path is not None and Path(features_csv_path).exists():
        features_df = pd.read_csv(features_csv_path)

    report = _build_report_dict(
        preprocess_meta=preprocess_meta,
        features_df=features_df,
        feature_meta=feat_meta_data,
    )

    if test_preprocess_meta_path is not None and Path(test_preprocess_meta_path).exists():
        test_pre_meta = json.loads(Path(test_preprocess_meta_path).read_text(encoding="utf-8"))
        test_feat_meta = {}
        if test_feature_meta_path is not None and Path(test_feature_meta_path).exists():
            test_feat_meta = json.loads(Path(test_feature_meta_path).read_text(encoding="utf-8"))
        test_feat_df = None
        if test_features_csv_path is not None and Path(test_features_csv_path).exists():
            test_feat_df = pd.read_csv(test_features_csv_path)

        report["independent_test_set"] = _build_report_dict(
            preprocess_meta=test_pre_meta,
            features_df=test_feat_df,
            feature_meta=test_feat_meta,
        )

    out_json = Path(output_json_path)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )

    if output_markdown_path is not None:
        md_content = render_markdown_report(report)
        out_md = Path(output_markdown_path)
        out_md.parent.mkdir(parents=True, exist_ok=True)
        out_md.write_text(md_content, encoding="utf-8")

    return report


def _render_dataset_section_lines(section_report: dict, prefix_title: str = "") -> list[str]:
    funnel = section_report["data_filtering_funnel"]
    evt_dist = section_report["event_distribution"]
    sess = section_report["session_class_imbalance"]
    feat_sum = section_report["feature_summary"]
    top_cats = section_report.get("top_categories", {})
    title_suffix = f" — {prefix_title}" if prefix_title else ""

    lines = [
        f"## 1. Bảng 1 — Thống kê Phễu lọc dữ liệu (`Data Filtering Funnel`){title_suffix}",
        "",
        "| Chỉ số thống kê | Giá trị thực tế | Tỷ lệ (%) |",
        "| --- | ---: | ---: |",
        f"| **Tổng số dòng sự kiện gốc (`total_raw_rows`)** | `{funnel['total_raw_rows']:,}` | `100.00%` |",
        f"| **Số dòng loại do khác ngành hàng Gear/Computer/Audio** | `{funnel['dropped_non_target_category']:,}` | `{funnel['dropped_non_target_pct']:.4f}%` |",
        f"| **Số dòng loại do thiếu `user_session`, `price <= 0` hoặc lỗi** | `{funnel['dropped_invalid_rows']:,}` | `{funnel['dropped_invalid_pct']:.4f}%` |",
        f"| **Tổng số dòng sự kiện hợp lệ còn lại (`valid_filtered_rows`)** | **`{funnel['valid_filtered_rows']:,}`** | **`{funnel['retention_rate_pct']:.4f}%`** |",
        f"| **Dung lượng file sau khi lọc** | `{funnel['output_size_mb']} MB` | - |",
        f"| **Tổng thời gian chạy bước lọc (`preprocess.py`)** | `{funnel['elapsed_seconds']} giây` | - |",
        "",
    ]

    per_file = funnel.get("per_file_stats", [])
    if per_file:
        lines.extend(
            [
                "### Chi tiết theo từng file CSV đầu vào",
                "",
                "| Tên file | Dung lượng (MB) | Số chunk | Tổng dòng gốc | Dòng hợp lệ sau lọc | Thời gian (giây) |",
                "| --- | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for pf in per_file:
            lines.append(
                f"| `{pf['file_name']}` | `{pf['file_size_mb']:,}` | `{pf['chunks_processed']}` | "
                f"`{pf['total_raw_rows']:,}` | **`{pf['valid_filtered_rows']:,}`** | `{pf['elapsed_seconds']}` |"
            )
        lines.append("")

    lines.extend(
        [
            "---",
            "",
            f"## 2. Bảng 2 — Phân bố sự kiện & Độ đa dạng sản phẩm (`Event Distribution`){title_suffix}",
            "",
            f"- **Tổng số sản phẩm duy nhất (`unique_products`):** `{section_report['unique_products']:,}` sản phẩm",
            f"- **Tổng số thương hiệu duy nhất (`unique_brands`):** `{section_report['unique_brands']:,}` thương hiệu",
            "",
            "| Loại sự kiện (`event_type`) | Số lượng sự kiện | Tỷ lệ (%) |",
            "| --- | ---: | ---: |",
        ]
    )
    for evt in VALID_KAGGLE_EVENT_TYPES:
        info = evt_dist.get(evt, {"count": 0, "pct": 0.0})
        lines.append(f"| `{evt}` | `{info['count']:,}` | `{info['pct']:.4f}%` |")

    if top_cats:
        lines.extend(
            [
                "",
                "### Top danh mục ngành hàng Gear / Computer / Audio chiếm tỷ trọng cao nhất",
                "",
                "| Danh mục (`category_code`) | Số lượng sự kiện |",
                "| --- | ---: |",
            ]
        )
        for cat_code, cnt in top_cats.items():
            lines.append(f"| `{cat_code}` | `{cnt:,}` |")

    lines.extend(
        [
            "",
            "---",
            "",
            f"## 3. Bảng 3 — Thống kê cấp độ phiên & Tỷ lệ mất cân bằng nhãn (`Session-level & Class Imbalance`){title_suffix}",
            "",
        ]
    )

    if sess.get("available"):
        lines.extend(
            [
                "| Chỉ số cấp phiên (`user_session`) | Giá trị thực tế |",
                "| --- | ---: |",
                f"| **Tổng số phiên truy cập hợp lệ (`total_sessions`)** | **`{sess['total_sessions']:,}`** |",
                f"| **Số phiên có mua hàng (`will_purchase = 1`)** | `{sess['purchase_sessions']:,}` |",
                f"| **Số phiên không mua hàng (`will_purchase = 0`)** | `{sess['non_purchase_sessions']:,}` |",
                f"| **Tỷ lệ chuyển đổi (`Conversion Rate %`)** | **`{sess['conversion_rate_pct']:.4f}%`** |",
                f"| **Tỷ lệ mất cân bằng lớp (`Class Imbalance Ratio`)** | **`{sess['imbalance_ratio_text']}`** |",
                f"| **Số sự kiện tại & sau thời điểm mua đầu tiên đã cắt bỏ (`Anti-Leakage Cutoff`)** | `{sess['leakage_events_removed']:,}` |",
                f"| **Số phiên dương tính không có lịch sử trước thời điểm mua bị loại bỏ** | `{sess['dropped_purchase_only_sessions']:,}` |",
            ]
        )
    else:
        lines.append(
            "> *Chưa có file `session_features.csv` từ bước `features.py` (phần của Nguyễn Hùng Khương). "
            "Sau khi chạy `features.py`, chạy lại `report_stats.py` để tự động điền Bảng 3 và Bảng 4.*"
        )

    lines.extend(
        [
            "",
            "---",
            "",
            f"## 4. Bảng 4 — Thống kê mô tả các đặc trưng hành vi (`Feature Summary Table`){title_suffix}",
            "",
        ]
    )

    if feat_sum:
        lines.extend(
            [
                "| Đặc trưng (`Feature`) | Nhóm `will_purchase = 0` (Mean ± Std / Median / P95) | Nhóm `will_purchase = 1` (Mean ± Std / Median / P95) | Toàn tập (Max) |",
                "| --- | --- | --- | ---: |",
            ]
        )
        for col, grp in feat_sum.items():
            g0 = grp["non_purchase_0"]
            g1 = grp["purchase_1"]
            gall = grp["all"]
            lines.append(
                f"| `{col}` | "
                f"`{g0['mean']} ± {g0['std']}` (Med: `{g0['median']}`, P95: `{g0['p95']}`) | "
                f"**`{g1['mean']} ± {g1['std']}`** (Med: `{g1['median']}`, P95: `{g1['p95']}`) | "
                f"`{gall['max']}` |"
            )
    else:
        lines.append(
            "> *Bảng thống kê chi tiết các đặc trưng sẽ được tự động điền ngay khi có đầu ra từ `features.py`.*"
        )

    lines.append("")
    return lines


def render_markdown_report(report: dict) -> str:
    funnel = report["data_filtering_funnel"]
    test_rep = report.get("independent_test_set")

    lines = [
        "# BÁO CÁO SỐ LIỆU THỰC NGHIỆM DATA PIPELINE TRÊN DATASET KAGGLE (EDA & REAL METRICS)",
        "",
        f"- **Thời điểm xuất báo cáo:** `{report['generated_at_utc']}`",
        f"- **Tập dữ liệu Train (`Train Set`):** `{', '.join(funnel.get('input_files', []))}`",
    ]
    if test_rep:
        test_files = test_rep.get("data_filtering_funnel", {}).get("input_files", [])
        lines.append(f"- **Tập dữ liệu Test độc lập (`Out-of-Time Test Set`):** `{', '.join(test_files)}`")
    lines.extend(["", "---", ""])

    if test_rep:
        lines.extend(["# PHẦN I — TẬP DỮ LIỆU HUẤN LUYỆN (`TRAIN SET`: `2019-Oct.csv` + `2019-Nov.csv`)", ""])
        lines.extend(_render_dataset_section_lines(report, prefix_title="Tập Train (`2019-Oct` + `2019-Nov`)"))
        lines.extend(
            [
                "---",
                "",
                "# PHẦN II — TẬP DỮ LIỆU KIỂM THỬ ĐỘC LẬP (`OUT-OF-TIME TEST SET`: `2019-Dec.csv`)",
                "",
            ]
        )
        lines.extend(_render_dataset_section_lines(test_rep, prefix_title="Tập Test độc lập (`2019-Dec`)"))
    else:
        lines.extend(_render_dataset_section_lines(report))

    return "\n".join(lines)
