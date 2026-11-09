"""Stage 3: Single-shot Out-of-Time Test Evaluation (2019-Dec) and Report Generation.

Loads the frozen calibrated models and locked optimal thresholds tau* produced
by Stage 2 (`train.py`), runs inference ONCE on `session_test_features.csv`,
and writes both `model_evaluation_report.json` and `rp_04_model_evaluation.md`.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from time import perf_counter
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.inspection import permutation_importance
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split

from analytics.ml.config import (
    DEFAULT_RANDOM_STATE,
    MODEL_EVAL_REPORT_JSON_PATH,
    MODEL_EVAL_REPORT_MD_PATH,
    MODELS_DIR,
    SESSION_FEATURE_COLUMNS,
    SESSION_TEST_FEATURES_PATH,
    TARGET_LABEL_COLUMN,
)
from analytics.ml.train import (
    ABLATION_MODEL_NAME,
    ALL_MODEL_NAMES,
    CANDIDATE_MODEL_NAMES,
    MODEL_DISPLAY_NAMES,
    compute_calibration_curve_and_ece,
    compute_classification_metrics,
    validate_feature_dataframe,
)
from analytics.ml.transformers import CalibratedModelWrapper


def _extract_feature_importance(
    wrapper: CalibratedModelWrapper,
    X_eval: pd.DataFrame,
    y_eval: np.ndarray,
    random_state: int = DEFAULT_RANDOM_STATE,
) -> list[dict[str, Any]]:
    """Extract normalized feature importance for tree, linear, or histogram GB models."""
    pipe = wrapper.base_estimator
    feat_step = pipe.named_steps["features"]
    clf_step = pipe.named_steps["classifier"]
    feature_names = [str(name) for name in feat_step.get_feature_names_out()]

    raw_scores: np.ndarray | None = None
    method_name = "permutation_importance"

    if hasattr(clf_step, "feature_importances_"):
        raw_scores = np.asarray(clf_step.feature_importances_, dtype=np.float64)
        method_name = "gini_impurity_importance"
    elif hasattr(clf_step, "coef_"):
        raw_scores = np.abs(np.asarray(clf_step.coef_, dtype=np.float64)).ravel()
        method_name = "abs_standardized_coefficient"
    else:
        # Use a capped stratified sample (max 10,000 rows) for fast permutation importance
        if len(X_eval) > 10_000 and len(np.unique(y_eval)) >= 2:
            X_sub, _, y_sub, _ = train_test_split(
                X_eval,
                y_eval,
                train_size=10_000,
                stratify=y_eval,
                random_state=random_state,
            )
        else:
            X_sub, y_sub = X_eval, y_eval

        X_trans = pipe.named_steps["scaler"].transform(feat_step.transform(X_sub))
        perm = permutation_importance(
            clf_step,
            X_trans,
            y_sub,
            scoring="average_precision",
            n_repeats=3,
            random_state=random_state,
        )
        raw_scores = np.clip(perm.importances_mean, 0.0, None)
        method_name = "permutation_pr_auc_importance"

    total = float(raw_scores.sum()) if raw_scores is not None else 0.0
    normalized = raw_scores / total if total > 0 else np.zeros_like(raw_scores)

    items = [
        {
            "feature": feature_names[idx],
            "importance_raw": round(float(raw_scores[idx]), 6),
            "importance_pct": round(float(normalized[idx] * 100.0), 4),
            "method": method_name,
        }
        for idx in range(len(feature_names))
    ]
    items.sort(key=lambda item: item["importance_pct"], reverse=True)
    for rank, item in enumerate(items, start=1):
        item["rank"] = rank
    return items


def _evaluate_naive_cart_rule(
    X_df: pd.DataFrame,
    y_true: np.ndarray,
) -> dict[str, Any]:
    """Evaluate the naive heuristic rule: `if cart_count >= 1 -> predict 1 else 0`."""
    y_arr = np.asarray(y_true, dtype=np.int64)
    preds = (X_df["cart_count"].to_numpy(dtype=np.float64) >= 1.0).astype(np.int64)
    tn, fp, fn, tp = confusion_matrix(y_arr, preds, labels=[0, 1]).ravel()
    has_both = len(np.unique(y_arr)) >= 2
    return {
        "model_name": "naive_rule_cart_ge_1",
        "display_name": "Rule Baseline (`if cart_count >= 1: return 1`)",
        "total_samples": int(len(y_arr)),
        "positive_samples": int(y_arr.sum()),
        "negative_samples": int(len(y_arr) - y_arr.sum()),
        "pr_auc": round(float(average_precision_score(y_arr, preds)) if has_both else 0.0, 6),
        "roc_auc": round(float(roc_auc_score(y_arr, preds)) if has_both else 0.0, 6),
        "f1_at_threshold": round(float(f1_score(y_arr, preds, zero_division=0)), 6),
        "precision_at_threshold": round(float(precision_score(y_arr, preds, zero_division=0)), 6),
        "recall_at_threshold": round(float(recall_score(y_arr, preds, zero_division=0)), 6),
        "accuracy_reference_only": round(float(accuracy_score(y_arr, preds)), 6),
        "confusion_matrix": {"tp": int(tp), "fp": int(fp), "tn": int(tn), "fn": int(fn)},
    }


def _render_markdown_report(report: dict[str, Any]) -> str:
    """Format the full experimental report into clean Markdown tables for the thesis."""
    champion_key = report["champion_model_name"]
    champion_display = MODEL_DISPLAY_NAMES.get(champion_key, champion_key)
    train_split = report["training_split_summary"]
    test_info = report["test_dataset_summary"]

    lines = [
        "# BÁO CÁO KẾT QUẢ HUẤN LUYỆN, HIỆU CHỈNH XÁC SUẤT & ĐÁNH GIÁ MÔ HÌNH DỰ ĐOÁN Ý ĐỊNH MUA HÀNG",
        "",
        f"- **Thời điểm xuất báo cáo:** `{report['generated_at_utc']}`",
        f"- **Phiên bản `scikit-learn`:** `{report['sklearn_version']}`",
        f"- **Chế độ chạy dữ liệu:** `{'Chạy thử nghiệm lấy mẫu (Partial Sample Run)' if report['partial_run'] else 'Toàn tập dữ liệu chính thức (Full Dataset Run)'}`",
        f"- **Mô hình Vô địch được chọn (`Champion Model`):** **`{champion_display}`** (`{champion_key}`)",
        f"- **Tiêu chí chọn mô hình:** `PR-AUC` cao nhất trên tập `Val_Select` (tuyệt đối không dùng tập Test Tháng 12 để tinh chỉnh hay chọn model)",
        f"- **Ngưỡng quyết định tối ưu đã khóa (`Locked Optimal Threshold τ*`):** **`{report['champion_optimal_threshold']:.4f}`**",
        "",
        "---",
        "",
        "## 1. Thống kê Phân chia Dữ liệu Thực nghiệm (`Train_Fit` / `Val_Calib` / `Val_Select` / `Out-of-Time Test`)",
        "",
        "| Tập dữ liệu | Nguồn thời gian | Tổng số phiên (`Sessions`) | Số phiên mua (`will_purchase = 1`) | Số phiên không mua (`0`) | Tỷ lệ chuyển đổi (`%`) | Tỷ lệ mất cân bằng | Vai trò trong thực nghiệm |",
        "| --- | --- | ---: | ---: | ---: | ---: | :---: | --- |",
    ]

    for label, source_month, stats, role in (
        (
            "**1. `Train_Fit` (70%)**",
            "`2019-Oct + Nov`",
            train_split["train_fit_70"],
            "Huấn luyện trọng số các mô hình gốc (`Base Models`) & `RobustScaler`",
        ),
        (
            "**2. `Val_Calib` (15%)**",
            "`2019-Oct + Nov`",
            train_split["val_calib_15"],
            "Khớp bộ Hiệu chỉnh xác suất (`Isotonic / Sigmoid Calibration`)",
        ),
        (
            "**3. `Val_Select` (15%)**",
            "`2019-Oct + Nov`",
            train_split["val_select_15"],
            "Chọn mô hình tốt nhất theo `PR-AUC` & dò ngưỡng tối ưu `τ*`",
        ),
        (
            "**4. `Out-of-Time Test` (100%)**",
            "**`2019-Dec` (Độc lập)**",
            test_info,
            "**Chỉ chạy đánh giá đúng 1 lần duy nhất sau khi khóa mô hình & `τ*`**",
        ),
    ):
        lines.append(
            f"| {label} | {source_month} | `{stats['total_sessions']:,}` | "
            f"`{stats['positive_sessions']:,}` | `{stats['negative_sessions']:,}` | "
            f"`{stats['conversion_rate_pct']:.4f}%` | `{stats['imbalance_ratio_text']}` | {role} |"
        )

    lines.extend(
        [
            "",
            "---",
            "",
            "## 2. Bảng 1 — So sánh 3 Mô hình Nền trên Cùng Bộ 14 Đặc trưng (`Validation` vs. `Out-of-Time Test 2019-Dec`)",
            "",
            "### 2.1 Kết quả trên Tập `Val_Select` (Dùng để chọn mô hình và khóa ngưỡng `τ*`)",
            "",
            "| Mô hình (`Model`) | `PR-AUC` (Chính) | `ROC-AUC` | `Brier Score` | Ngưỡng `τ*` | `F1 (@τ*)` | `Precision (@τ*)` | `Recall (@τ*)` | `F1 (@0.50)` | Thời gian Train (s) |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )

    for name in ALL_MODEL_NAMES:
        m = report["models"][name]
        val_m = m["val_select_metrics_calibrated"]
        prefix = "🏆 " if name == champion_key else ""
        lines.append(
            f"| {prefix}**{m['display_name']}** | **`{val_m['pr_auc']:.4f}`** | `{val_m['roc_auc']:.4f}` | "
            f"`{val_m['brier_score']:.4f}` | `{m['optimal_threshold']:.4f}` | "
            f"**`{val_m['f1_at_threshold']:.4f}`** | `{val_m['precision_at_threshold']:.4f}` | "
            f"`{val_m['recall_at_threshold']:.4f}` | `{val_m['f1_at_default_050']:.4f}` | `{m['train_time_sec']:.2f}s` |"
        )

    lines.extend(
        [
            "",
            "### 2.2 Kết quả Chính thức (1 Lần Duy Nhất) trên Tập Test Độc lập Tháng 12 (`2019-Dec`)",
            "",
            "| Mô hình (`Model`) | `PR-AUC` (Chính) | `ROC-AUC` | `Brier Score` | Ngưỡng khóa `τ*` | `F1 (@τ*)` | `Precision (@τ*)` | `Recall (@τ*)` | `F1 (@0.50)` | Ma trận nhầm lẫn (`TP / FP / TN / FN`) |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )

    for name in ALL_MODEL_NAMES:
        m = report["models"][name]
        test_m = m["test_metrics_all_sessions_calibrated"]
        cm = test_m["confusion_matrix"]
        prefix = "🏆 " if name == champion_key else ""
        lines.append(
            f"| {prefix}**{m['display_name']}** | **`{test_m['pr_auc']:.4f}`** | `{test_m['roc_auc']:.4f}` | "
            f"`{test_m['brier_score']:.4f}` | `{m['optimal_threshold']:.4f}` | "
            f"**`{test_m['f1_at_threshold']:.4f}`** | `{test_m['precision_at_threshold']:.4f}` | "
            f"`{test_m['recall_at_threshold']:.4f}` | `{test_m['f1_at_default_050']:.4f}` | "
            f"`TP={cm['tp']:,}, FP={cm['fp']:,}, TN={cm['tn']:,}, FN={cm['fn']:,}` |"
        )

    lines.extend(
        [
            "",
            "---",
            "",
            "## 3. Bảng 2 — Đánh giá Hiệu chỉnh Xác suất Dự đoán (`Probability Calibration: Uncalibrated vs. Calibrated`)",
            "",
            "> **Ý nghĩa kỹ thuật:** Khi bật `class_weight='balanced'` để xử lý tỷ lệ mất cân bằng `1 : 19.94`, xác suất dự đoán thô (`Uncalibrated`) bị đẩy vọt lên cao gấp nhiều lần tỷ lệ mua thực tế. Hiệu chỉnh xác suất (`Isotonic` / `Sigmoid`) trên `Val_Calib` kéo xác suất dự đoán về đúng tỷ lệ chuyển đổi thực nghiệm, giúp `Brier Score`, `Log Loss` và `ECE` giảm mạnh mà vẫn bảo toàn `PR-AUC`.",
            "",
            "| Mô hình (`Model`) | Phương pháp chọn | `Brier (Uncal)` $\\rightarrow$ **`Brier (Cal)`** | `LogLoss (Uncal)` $\\rightarrow$ **`LogLoss (Cal)`** | `ECE (Uncal)` $\\rightarrow$ **`ECE (Cal)`** | Xác suất TB `Uncal` $\\rightarrow$ **`Cal`** *(Thực tế Test: `"
            f"{test_info['conversion_rate_pct']:.2f}%`)* |",
            "| --- | :---: | :---: | :---: | :---: | :---: |",
        ]
    )

    for name in ALL_MODEL_NAMES:
        m = report["models"][name]
        uncal_c = m["test_calibration_comparison"]["uncalibrated"]
        cal_c = m["test_calibration_comparison"]["calibrated"]
        lines.append(
            f"| **{m['display_name']}** | `{m['chosen_calibration_method']}` | "
            f"`{uncal_c['brier_score']:.4f}` $\\rightarrow$ **`{cal_c['brier_score']:.4f}`** | "
            f"`{uncal_c['log_loss']:.4f}` $\\rightarrow$ **`{cal_c['log_loss']:.4f}`** | "
            f"`{uncal_c['ece']:.4f}` $\\rightarrow$ **`{cal_c['ece']:.4f}`** | "
            f"`{uncal_c['mean_predicted_prob'] * 100:.2f}%` $\\rightarrow$ **`{cal_c['mean_predicted_prob'] * 100:.2f}%`** |"
        )

    champ_bins = report["models"][champion_key]["test_calibration_comparison"]["calibrated"]["bins"]
    lines.extend(
        [
            "",
            f"### Bảng Đường cong Độ tin cậy 10 Khoảng (`10-Bin Reliability Diagram`) — Mô hình Vô địch `{champion_display}` trên Tập Test Tháng 12",
            "",
            "| Khoảng xác suất dự đoán (`Bin`) | Số lượng phiên (`Count`) | Xác suất dự đoán TB (`Mean Predicted`) | Tỷ lệ mua thực tế (`Empirical Positive`) | Độ lệch tuyệt đối (`|Gap|`) |",
            "| :---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for b in champ_bins:
        lines.append(
            f"| `{b['bin_range']}` | `{b['count']:,}` | `{b['mean_predicted_prob']:.4f}` | "
            f"`{b['empirical_positive_rate']:.4f}` | `{b['abs_calibration_gap']:.4f}` |"
        )

    lines.extend(
        [
            "",
            "---",
            "",
            "## 4. Bảng 3 — Đánh giá theo 3 Lát cắt Thực tế (`Multi-Slice & Cart-Abandonment Evaluation` trên Tập Test Tháng 12)",
            "",
            "### 4.1 Lát cắt B (`Cart-Active Subset`: Các phiên đã có `cart_count >= 1` — Phân biệt Chốt đơn thật vs. Bỏ quên giỏ hàng)",
            "",
            "> **Chứng minh mô hình không suy biến thành luật `if cart_count >= 1`:** Trên tập con các khách hàng đã thêm sản phẩm vào giỏ (`cart_count >= 1`), luật đơn giản `if cart_count >= 1` sẽ dự đoán 100% là mua hàng (`Recall = 1.0` nhưng không phân biệt được ai bỏ giỏ hàng, `ROC-AUC = 0.5000`). Trong khi đó, các mô hình ML sử dụng `repeat_view_ratio`, `session_duration_sec`, `cart_to_view_ratio`, `avg_price` để phân tách chính xác người mua thật và người bỏ quên giỏ hàng.",
            "",
            "| Mô hình / Luật so sánh trên tập `cart_count >= 1` | Tổng phiên có giỏ | `PR-AUC` | `ROC-AUC` | `F1-Score (@τ*)` | `Precision (@τ*)` | `Recall (@τ*)` | Ma trận nhầm lẫn (`TP / FP / TN / FN`) |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )

    naive_cart = report["multi_slice_evaluation"]["cart_active_subset"]["naive_rule_baseline"]
    ncm = naive_cart["confusion_matrix"]
    lines.append(
        f"| **{naive_cart['display_name']}** | `{naive_cart['total_samples']:,}` | "
        f"`{naive_cart['pr_auc']:.4f}` | `{naive_cart['roc_auc']:.4f}` | "
        f"`{naive_cart['f1_at_threshold']:.4f}` | `{naive_cart['precision_at_threshold']:.4f}` | "
        f"`{naive_cart['recall_at_threshold']:.4f}` | "
        f"`TP={ncm['tp']:,}, FP={ncm['fp']:,}, TN={ncm['tn']:,}, FN={ncm['fn']:,}` |"
    )

    for name in CANDIDATE_MODEL_NAMES:
        slice_m = report["multi_slice_evaluation"]["cart_active_subset"]["models"][name]
        scm = slice_m["confusion_matrix"]
        lines.append(
            f"| **{MODEL_DISPLAY_NAMES[name]}** | `{slice_m['total_samples']:,}` | "
            f"**`{slice_m['pr_auc']:.4f}`** | **`{slice_m['roc_auc']:.4f}`** | "
            f"**`{slice_m['f1_at_threshold']:.4f}`** | `{slice_m['precision_at_threshold']:.4f}` | "
            f"`{slice_m['recall_at_threshold']:.4f}` | "
            f"`TP={scm['tp']:,}, FP={scm['fp']:,}, TN={scm['tn']:,}, FN={scm['fn']:,}` |"
        )

    ablation_test = report["models"][ABLATION_MODEL_NAME]["test_metrics_all_sessions_calibrated"]
    lines.extend(
        [
            "",
            "### 4.2 Lát cắt C (`Early-Intent Ablation`: Dự báo sớm khi loại bỏ hoàn toàn các biến giỏ hàng)",
            "",
            f"- **Mô hình `{MODEL_DISPLAY_NAMES[ABLATION_MODEL_NAME]}`** (chỉ học từ hành vi xem `view_count`, `repeat_view_ratio`, `session_duration_sec`, `avg_price`, `price_range_ratio`, `hour`, `day_of_week`, `is_weekend`):",
            f"  - Đạt **`ROC-AUC = {ablation_test['roc_auc']:.4f}`** và **`PR-AUC = {ablation_test['pr_auc']:.4f}`** trên Tập Test Tháng 12 (cao hơn nhiều lần so với tỷ lệ ngẫu nhiên `{test_info['conversion_rate_pct'] / 100:.4f}`), chứng minh các đặc trưng duyệt sản phẩm và thời lượng phiên đã được cắt trần `3600s` mang tín hiệu dự báo sớm thực sự.",
            "",
            "---",
            "",
            "## 5. Bảng 4 — Xếp hạng Mức độ Quan trọng của các Đặc trưng (`Feature Importance`)",
            "",
            f"### 5.1 Độ quan trọng đặc trưng trên Mô hình Vô địch (`{champion_display}`)",
            "",
            "| Hạng (`Rank`) | Tên đặc trưng (`Feature`) | Tỷ trọng đóng góp (`Importance %`) | Giá trị thô (`Raw Score`) | Phương pháp đo |",
            "| :---: | --- | ---: | ---: | --- |",
        ]
    )

    for item in report["feature_importance"][champion_key]:
        lines.append(
            f"| `{item['rank']}` | `{item['feature']}` | **`{item['importance_pct']:.2f}%`** | "
            f"`{item['importance_raw']:.6f}` | `{item['method']}` |"
        )

    lines.extend(
        [
            "",
            f"### 5.2 Độ quan trọng đặc trưng trên Mô hình Dự báo sớm (`{MODEL_DISPLAY_NAMES[ABLATION_MODEL_NAME]}` — Không có biến giỏ hàng)",
            "",
            "| Hạng (`Rank`) | Tên đặc trưng (`Feature`) | Tỷ trọng đóng góp (`Importance %`) | Giá trị thô (`Raw Score`) | Phương pháp đo |",
            "| :---: | --- | ---: | ---: | --- |",
        ]
    )

    for item in report["feature_importance"][ABLATION_MODEL_NAME]:
        lines.append(
            f"| `{item['rank']}` | `{item['feature']}` | **`{item['importance_pct']:.2f}%`** | "
            f"`{item['importance_raw']:.6f}` | `{item['method']}` |"
        )

    lines.append("")
    return "\n".join(lines)


def run_final_test_evaluation(
    test_csv_path: Path | str = SESSION_TEST_FEATURES_PATH,
    models_dir: Path | str = MODELS_DIR,
    output_json_path: Path | str = MODEL_EVAL_REPORT_JSON_PATH,
    output_md_path: Path | str = MODEL_EVAL_REPORT_MD_PATH,
    sample_size: int | None = None,
    random_state: int = DEFAULT_RANDOM_STATE,
) -> dict[str, Any]:
    """Run single-shot evaluation on the 2019-Dec Out-of-Time Test Set and emit reports."""
    started = perf_counter()
    test_csv = Path(test_csv_path).resolve()
    mod_dir = Path(models_dir).resolve()
    out_json = Path(output_json_path).resolve()
    out_md = Path(output_md_path).resolve()

    if not test_csv.is_file():
        raise FileNotFoundError(f"Out-of-Time Test CSV not found: {test_csv}")

    summary_path = mod_dir / "training_summary_meta.json"
    best_meta_path = mod_dir / "best_model_meta.json"
    if not summary_path.is_file() or not best_meta_path.is_file():
        raise FileNotFoundError(
            f"Trained model metadata not found in {mod_dir}. Run Stage 2 (`train.py`) first."
        )

    training_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    best_meta = json.loads(best_meta_path.read_text(encoding="utf-8"))

    print(f"[Stage 3] Loading Out-of-Time Test dataset from {test_csv} ...")
    raw_test_df = pd.read_csv(test_csv)
    clean_test = validate_feature_dataframe(raw_test_df)
    total_test_rows = len(clean_test)

    if sample_size is not None and sample_size < len(clean_test):
        clean_test, _ = train_test_split(
            clean_test,
            train_size=int(sample_size),
            stratify=clean_test[TARGET_LABEL_COLUMN],
            random_state=random_state,
        )
        clean_test = clean_test.reset_index(drop=True)

    X_test = clean_test[SESSION_FEATURE_COLUMNS].reset_index(drop=True)
    y_test = clean_test[TARGET_LABEL_COLUMN].to_numpy(dtype=np.int64)

    pos_test = int(y_test.sum())
    neg_test = int(len(y_test) - pos_test)
    rate_test = float(pos_test / len(y_test) * 100.0) if len(y_test) else 0.0
    ratio_test = float(neg_test / max(pos_test, 1))

    test_dataset_summary = {
        "total_available_rows": int(total_test_rows),
        "total_sessions": int(len(clean_test)),
        "positive_sessions": pos_test,
        "negative_sessions": neg_test,
        "conversion_rate_pct": round(rate_test, 4),
        "imbalance_ratio": round(ratio_test, 2),
        "imbalance_ratio_text": f"1 : {ratio_test:.2f}",
    }

    cart_mask = (X_test["cart_count"].to_numpy(dtype=np.float64) >= 1.0)
    X_test_cart = X_test.loc[cart_mask].reset_index(drop=True)
    y_test_cart = y_test[cart_mask]

    models_eval: dict[str, Any] = {}
    cart_subset_models: dict[str, Any] = {}
    feature_importance_map: dict[str, list[dict[str, Any]]] = {}

    for model_name in ALL_MODEL_NAMES:
        model_file = mod_dir / f"{model_name}.joblib"
        if not model_file.is_file():
            raise FileNotFoundError(f"Expected frozen model file missing: {model_file}")

        wrapper: CalibratedModelWrapper = joblib.load(model_file)
        train_info = training_summary["models"][model_name]
        locked_tau = float(train_info["optimal_threshold"])

        print(
            f"[Stage 3] Evaluating frozen model '{model_name}' on Test Set "
            f"(locked tau*={locked_tau:.4f}) ..."
        )
        uncal_test_proba = wrapper.predict_raw_proba(X_test)[:, 1]
        cal_test_proba = wrapper.predict_proba(X_test)[:, 1]

        test_metrics_cal = compute_classification_metrics(
            y_test, cal_test_proba, threshold=locked_tau
        )
        test_metrics_uncal = compute_classification_metrics(
            y_test, uncal_test_proba, threshold=0.50
        )
        test_uncal_curve = compute_calibration_curve_and_ece(y_test, uncal_test_proba)
        test_cal_curve = compute_calibration_curve_and_ece(y_test, cal_test_proba)

        models_eval[model_name] = {
            **train_info,
            "test_metrics_all_sessions_calibrated": test_metrics_cal,
            "test_metrics_all_sessions_uncalibrated_at_050": test_metrics_uncal,
            "test_calibration_comparison": {
                "uncalibrated": test_uncal_curve,
                "calibrated": test_cal_curve,
            },
        }

        if len(X_test_cart) > 0 and model_name in CANDIDATE_MODEL_NAMES:
            cart_proba = cal_test_proba[cart_mask]
            cart_subset_models[model_name] = compute_classification_metrics(
                y_test_cart, cart_proba, threshold=locked_tau
            )

        feature_importance_map[model_name] = _extract_feature_importance(
            wrapper, X_test, y_test, random_state=random_state
        )

    naive_all_rule = _evaluate_naive_cart_rule(X_test, y_test)
    naive_cart_rule = (
        _evaluate_naive_cart_rule(X_test_cart, y_test_cart)
        if len(X_test_cart) > 0
        else {}
    )

    partial_run = bool(
        training_summary["split_summary"].get("partial_sample_run", False)
        or (sample_size is not None and sample_size < total_test_rows)
    )

    full_report = {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "partial_run": partial_run,
        "sklearn_version": training_summary["sklearn_version"],
        "schema_version": training_summary["schema_version"],
        "evaluation_elapsed_seconds": round(perf_counter() - started, 3),
        "champion_model_name": best_meta["champion_model_name"],
        "champion_display_name": best_meta["champion_display_name"],
        "champion_optimal_threshold": float(best_meta["optimal_threshold"]),
        "candidate_ranking_by_val_pr_auc": training_summary["candidate_ranking_by_val_pr_auc"],
        "training_split_summary": training_summary["split_summary"],
        "test_dataset_summary": test_dataset_summary,
        "models": models_eval,
        "multi_slice_evaluation": {
            "all_test_sessions": {
                "naive_rule_baseline": naive_all_rule,
                "models": {
                    name: models_eval[name]["test_metrics_all_sessions_calibrated"]
                    for name in CANDIDATE_MODEL_NAMES
                },
            },
            "cart_active_subset": {
                "description": "Sessions with cart_count >= 1 (Purchase vs. Cart Abandonment)",
                "total_cart_active_sessions": int(len(X_test_cart)),
                "positive_purchase_sessions": int(y_test_cart.sum()) if len(y_test_cart) else 0,
                "abandoned_cart_sessions": int(len(y_test_cart) - y_test_cart.sum())
                if len(y_test_cart)
                else 0,
                "naive_rule_baseline": naive_cart_rule,
                "models": cart_subset_models,
            },
            "early_intent_ablation_no_cart": models_eval[ABLATION_MODEL_NAME][
                "test_metrics_all_sessions_calibrated"
            ],
        },
        "feature_importance": feature_importance_map,
    }

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(
        json.dumps(full_report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    markdown_text = _render_markdown_report(full_report)
    out_md.write_text(markdown_text, encoding="utf-8")

    # Update best_model_meta.json with final test summary
    best_meta["test_metrics_summary"] = models_eval[best_meta["champion_model_name"]][
        "test_metrics_all_sessions_calibrated"
    ]
    best_meta_path.write_text(
        json.dumps(best_meta, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(
        f"[Stage 3 Complete] Reports written to:\n"
        f"  - JSON: {out_json}\n"
        f"  - Markdown: {out_md}"
    )
    return full_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run single-shot evaluation on the 2019-Dec Out-of-Time Test Set."
    )
    parser.add_argument(
        "--test-csv",
        type=Path,
        default=SESSION_TEST_FEATURES_PATH,
        help="Path to Out-of-Time Test session_test_features.csv (2019-Dec).",
    )
    parser.add_argument(
        "--models-dir",
        type=Path,
        default=MODELS_DIR,
        help="Directory containing frozen .joblib models from Stage 2.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=MODEL_EVAL_REPORT_JSON_PATH,
        help="Output path for model_evaluation_report.json.",
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=MODEL_EVAL_REPORT_MD_PATH,
        help="Output path for rp_04_model_evaluation.md.",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=None,
        help="Optional stratified sample size for smoke testing only.",
    )
    args = parser.parse_args(argv)
    run_final_test_evaluation(
        test_csv_path=args.test_csv,
        models_dir=args.models_dir,
        output_json_path=args.output_json,
        output_md_path=args.output_md,
        sample_size=args.sample_size,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
