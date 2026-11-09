"""Stage 1 & Stage 2: Stratified 70/15/15 split, multi-model training,
probability calibration, and decision threshold tuning on October-November data.

IMPORTANT:
- This module NEVER touches `session_test_features.csv` (2019-Dec Out-of-Time Test Set).
- All hyperparameter choices, probability calibration fits (`Val_Calib`),
  threshold tuning (`Val_Select`), and champion model selection (`PR-AUC` on
  `Val_Select`) happen strictly within the October-November dataset.
- Has ZERO Django dependencies so it can execute directly on Google Colab Extension.
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
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    log_loss,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import RobustScaler

from analytics.ml.config import (
    DEFAULT_RANDOM_STATE,
    MAX_SESSION_DURATION_SEC,
    MODELS_DIR,
    SESSION_FEATURE_COLUMNS,
    SESSION_FEATURES_PATH,
    TARGET_LABEL_COLUMN,
    VND_TO_USD_RATE,
)
from analytics.ml.features import SCHEMA_VERSION
from analytics.ml.transformers import CalibratedModelWrapper, SessionFeatureTransformer

CANDIDATE_MODEL_NAMES = (
    "logistic_regression",
    "random_forest",
    "gradient_boosting",
)
ABLATION_MODEL_NAME = "early_intent_no_cart"
ALL_MODEL_NAMES = (*CANDIDATE_MODEL_NAMES, ABLATION_MODEL_NAME)

MODEL_DISPLAY_NAMES = {
    "logistic_regression": "Logistic Regression (Linear Baseline)",
    "random_forest": "Random Forest (Bagging Tree Ensemble)",
    "gradient_boosting": "HistGradientBoosting (Gradient Boosted Trees)",
    "early_intent_no_cart": "Early-Intent HistGB (View-Only Ablation, No Cart)",
}


def validate_feature_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Validate that a session feature DataFrame conforms to the 16-column contract."""
    required = ["user_session", *SESSION_FEATURE_COLUMNS, TARGET_LABEL_COLUMN]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns in feature dataset: {', '.join(missing)}")
    if df.empty:
        raise ValueError("Feature dataset must not be empty")

    clean = df[required].copy()
    for col in SESSION_FEATURE_COLUMNS:
        clean[col] = pd.to_numeric(clean[col], errors="raise").astype(np.float64)
    clean[TARGET_LABEL_COLUMN] = (
        pd.to_numeric(clean[TARGET_LABEL_COLUMN], errors="raise").astype(np.int64)
    )
    unique_labels = set(clean[TARGET_LABEL_COLUMN].unique())
    if not unique_labels.issubset({0, 1}) or len(unique_labels) < 2:
        raise ValueError(
            f"Target column '{TARGET_LABEL_COLUMN}' must contain both binary classes 0 and 1"
        )
    return clean


def split_session_features_70_15_15(
    features_df: pd.DataFrame,
    sample_size: int | None = None,
    random_state: int = DEFAULT_RANDOM_STATE,
) -> dict[str, Any]:
    """Perform Stratified 70% Train_Fit / 15% Val_Calib / 15% Val_Select split."""
    clean = validate_feature_dataframe(features_df)
    total_available_rows = len(clean)

    if sample_size is not None:
        if sample_size < 100:
            raise ValueError("sample_size must be at least 100 sessions")
        if sample_size < len(clean):
            clean, _ = train_test_split(
                clean,
                train_size=int(sample_size),
                stratify=clean[TARGET_LABEL_COLUMN],
                random_state=random_state,
            )
            clean = clean.reset_index(drop=True)

    train_df, temp_val_df = train_test_split(
        clean,
        test_size=0.30,
        stratify=clean[TARGET_LABEL_COLUMN],
        random_state=random_state,
    )
    val_calib_df, val_select_df = train_test_split(
        temp_val_df,
        test_size=0.50,
        stratify=temp_val_df[TARGET_LABEL_COLUMN],
        random_state=random_state,
    )

    if (
        set(train_df.index).intersection(val_calib_df.index)
        or set(train_df.index).intersection(val_select_df.index)
        or set(val_calib_df.index).intersection(val_select_df.index)
    ):
        raise AssertionError("Stratified 70/15/15 splits must be strictly disjoint")

    def _split_stats(part: pd.DataFrame) -> dict[str, Any]:
        pos = int(part[TARGET_LABEL_COLUMN].sum())
        neg = int(len(part) - pos)
        rate = float(pos / len(part) * 100.0) if len(part) else 0.0
        ratio = float(neg / max(pos, 1))
        return {
            "total_sessions": int(len(part)),
            "positive_sessions": pos,
            "negative_sessions": neg,
            "conversion_rate_pct": round(rate, 4),
            "imbalance_ratio": round(ratio, 2),
            "imbalance_ratio_text": f"1 : {ratio:.2f}",
        }

    return {
        "X_train_fit": train_df[SESSION_FEATURE_COLUMNS].reset_index(drop=True),
        "y_train_fit": train_df[TARGET_LABEL_COLUMN].to_numpy(dtype=np.int64),
        "X_val_calib": val_calib_df[SESSION_FEATURE_COLUMNS].reset_index(drop=True),
        "y_val_calib": val_calib_df[TARGET_LABEL_COLUMN].to_numpy(dtype=np.int64),
        "X_val_select": val_select_df[SESSION_FEATURE_COLUMNS].reset_index(drop=True),
        "y_val_select": val_select_df[TARGET_LABEL_COLUMN].to_numpy(dtype=np.int64),
        "split_summary": {
            "total_available_rows": int(total_available_rows),
            "used_rows": int(len(clean)),
            "sample_size": int(sample_size) if sample_size is not None else None,
            "partial_sample_run": sample_size is not None and sample_size < total_available_rows,
            "random_state": int(random_state),
            "train_fit_70": _split_stats(train_df),
            "val_calib_15": _split_stats(val_calib_df),
            "val_select_15": _split_stats(val_select_df),
        },
    }


def build_candidate_pipelines(
    max_duration_sec: float = MAX_SESSION_DURATION_SEC,
    random_state: int = DEFAULT_RANDOM_STATE,
    rf_n_estimators: int = 150,
    gb_max_iter: int = 250,
    min_samples_leaf: int = 50,
) -> dict[str, Pipeline]:
    """Construct the 3 baseline models on all 14 features + 1 Early-Intent ablation model."""
    return {
        "logistic_regression": Pipeline(
            [
                (
                    "features",
                    SessionFeatureTransformer(
                        max_duration_sec=max_duration_sec,
                        add_price_range_ratio=True,
                        drop_cart_features=False,
                    ),
                ),
                ("scaler", RobustScaler()),
                (
                    "classifier",
                    LogisticRegression(
                        class_weight="balanced",
                        C=1.0,
                        max_iter=500,
                        random_state=random_state,
                    ),
                ),
            ]
        ),
        "random_forest": Pipeline(
            [
                (
                    "features",
                    SessionFeatureTransformer(
                        max_duration_sec=max_duration_sec,
                        add_price_range_ratio=True,
                        drop_cart_features=False,
                    ),
                ),
                ("scaler", RobustScaler()),
                (
                    "classifier",
                    RandomForestClassifier(
                        n_estimators=rf_n_estimators,
                        max_depth=12,
                        min_samples_leaf=min_samples_leaf,
                        max_features="sqrt",
                        class_weight="balanced_subsample",
                        n_jobs=-1,
                        random_state=random_state,
                    ),
                ),
            ]
        ),
        "gradient_boosting": Pipeline(
            [
                (
                    "features",
                    SessionFeatureTransformer(
                        max_duration_sec=max_duration_sec,
                        add_price_range_ratio=True,
                        drop_cart_features=False,
                    ),
                ),
                ("scaler", RobustScaler()),
                (
                    "classifier",
                    HistGradientBoostingClassifier(
                        max_iter=gb_max_iter,
                        learning_rate=0.05,
                        max_leaf_nodes=63,
                        min_samples_leaf=min_samples_leaf,
                        l2_regularization=1.0,
                        max_features=0.7,
                        class_weight="balanced",
                        early_stopping=True,
                        random_state=random_state,
                    ),
                ),
            ]
        ),
        "early_intent_no_cart": Pipeline(
            [
                (
                    "features",
                    SessionFeatureTransformer(
                        max_duration_sec=max_duration_sec,
                        add_price_range_ratio=True,
                        drop_cart_features=True,
                    ),
                ),
                ("scaler", RobustScaler()),
                (
                    "classifier",
                    HistGradientBoostingClassifier(
                        max_iter=gb_max_iter,
                        learning_rate=0.05,
                        max_leaf_nodes=63,
                        min_samples_leaf=min_samples_leaf,
                        l2_regularization=1.0,
                        max_features=0.8,
                        class_weight="balanced",
                        early_stopping=True,
                        random_state=random_state,
                    ),
                ),
            ]
        ),
    }


def compute_calibration_curve_and_ece(
    y_true: np.ndarray,
    pos_proba: np.ndarray,
    n_bins: int = 10,
) -> dict[str, Any]:
    """Compute Expected Calibration Error (ECE) and 10-bin reliability table."""
    y_arr = np.asarray(y_true, dtype=np.int64)
    p_arr = np.clip(np.asarray(pos_proba, dtype=np.float64), 0.0, 1.0)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    bin_indices = np.minimum(np.digitize(p_arr, edges[1:-1], right=False), n_bins - 1)

    total = len(y_arr)
    ece = 0.0
    bins_report = []

    for b in range(n_bins):
        mask = bin_indices == b
        count = int(mask.sum())
        low, high = float(edges[b]), float(edges[b + 1])
        if count > 0:
            mean_pred = float(p_arr[mask].mean())
            frac_pos = float(y_arr[mask].mean())
            abs_gap = abs(mean_pred - frac_pos)
            ece += (count / total) * abs_gap
        else:
            mean_pred = 0.0
            frac_pos = 0.0
            abs_gap = 0.0
        bins_report.append(
            {
                "bin_index": b + 1,
                "bin_range": f"[{low:.1f}, {high:.1f}{']' if b == n_bins - 1 else ')'}",
                "count": count,
                "mean_predicted_prob": round(mean_pred, 6),
                "empirical_positive_rate": round(frac_pos, 6),
                "abs_calibration_gap": round(abs_gap, 6),
            }
        )

    return {
        "ece": round(float(ece), 6),
        "brier_score": round(float(brier_score_loss(y_arr, p_arr)), 6),
        "log_loss": round(float(log_loss(y_arr, np.clip(p_arr, 1e-6, 1.0 - 1e-6))), 6),
        "mean_predicted_prob": round(float(p_arr.mean()), 6),
        "empirical_positive_rate": round(float(y_arr.mean()), 6),
        "bins": bins_report,
    }


def find_optimal_threshold(
    y_true: np.ndarray,
    pos_proba: np.ndarray,
) -> dict[str, float]:
    """Find probability threshold tau* on Validation that maximizes F1-score."""
    y_arr = np.asarray(y_true, dtype=np.int64)
    p_arr = np.clip(np.asarray(pos_proba, dtype=np.float64), 0.0, 1.0)

    precisions, recalls, pr_thresholds = precision_recall_curve(y_arr, p_arr)
    grid = np.linspace(0.01, 0.99, 99)
    if len(pr_thresholds) > 0:
        valid_pr = pr_thresholds[(pr_thresholds > 0.005) & (pr_thresholds < 0.995)]
        if len(valid_pr) > 500:
            idx = np.linspace(0, len(valid_pr) - 1, 500, dtype=int)
            valid_pr = valid_pr[idx]
        candidates = np.unique(np.concatenate([grid, valid_pr]))
    else:
        candidates = grid

    best_tau = 0.50
    best_f1 = -1.0
    best_prec = 0.0
    best_rec = 0.0

    for tau in candidates:
        preds = (p_arr >= tau).astype(np.int64)
        score = float(f1_score(y_arr, preds, zero_division=0))
        if score > best_f1:
            best_f1 = score
            best_tau = float(tau)
            best_prec = float(precision_score(y_arr, preds, zero_division=0))
            best_rec = float(recall_score(y_arr, preds, zero_division=0))

    return {
        "optimal_threshold": round(float(np.clip(best_tau, 0.01, 0.99)), 4),
        "best_f1": round(best_f1, 6),
        "precision_at_optimal": round(best_prec, 6),
        "recall_at_optimal": round(best_rec, 6),
    }


def compute_classification_metrics(
    y_true: np.ndarray,
    pos_proba: np.ndarray,
    threshold: float,
) -> dict[str, Any]:
    """Compute ranking, probability, and threshold-based metrics for binary classification."""
    y_arr = np.asarray(y_true, dtype=np.int64)
    p_arr = np.clip(np.asarray(pos_proba, dtype=np.float64), 0.0, 1.0)

    has_both_classes = len(np.unique(y_arr)) >= 2
    pr_auc = float(average_precision_score(y_arr, p_arr)) if has_both_classes else 0.0
    roc_auc = float(roc_auc_score(y_arr, p_arr)) if has_both_classes else 0.0
    brier = float(brier_score_loss(y_arr, p_arr))
    logloss_val = (
        float(log_loss(y_arr, np.clip(p_arr, 1e-6, 1.0 - 1e-6), labels=[0, 1]))
        if len(y_arr) > 0
        else 0.0
    )

    preds_opt = (p_arr >= threshold).astype(np.int64)
    preds_050 = (p_arr >= 0.50).astype(np.int64)

    tn, fp, fn, tp = confusion_matrix(y_arr, preds_opt, labels=[0, 1]).ravel()

    return {
        "total_samples": int(len(y_arr)),
        "positive_samples": int(y_arr.sum()),
        "negative_samples": int(len(y_arr) - y_arr.sum()),
        "positive_rate_pct": round(float(y_arr.mean() * 100.0) if len(y_arr) else 0.0, 4),
        "pr_auc": round(pr_auc, 6),
        "roc_auc": round(roc_auc, 6),
        "brier_score": round(brier, 6),
        "log_loss": round(logloss_val, 6),
        "threshold_used": round(float(threshold), 4),
        "f1_at_threshold": round(float(f1_score(y_arr, preds_opt, zero_division=0)), 6),
        "precision_at_threshold": round(
            float(precision_score(y_arr, preds_opt, zero_division=0)), 6
        ),
        "recall_at_threshold": round(
            float(recall_score(y_arr, preds_opt, zero_division=0)), 6
        ),
        "accuracy_at_threshold_reference_only": round(
            float(accuracy_score(y_arr, preds_opt)), 6
        ),
        "f1_at_default_050": round(float(f1_score(y_arr, preds_050, zero_division=0)), 6),
        "precision_at_default_050": round(
            float(precision_score(y_arr, preds_050, zero_division=0)), 6
        ),
        "recall_at_default_050": round(
            float(recall_score(y_arr, preds_050, zero_division=0)), 6
        ),
        "confusion_matrix": {
            "tp": int(tp),
            "fp": int(fp),
            "tn": int(tn),
            "fn": int(fn),
        },
    }


def run_training_pipeline(
    train_csv_path: Path | str = SESSION_FEATURES_PATH,
    models_dir: Path | str = MODELS_DIR,
    sample_size: int | None = None,
    random_state: int = DEFAULT_RANDOM_STATE,
    max_duration_sec: float = MAX_SESSION_DURATION_SEC,
    rf_n_estimators: int = 150,
    gb_max_iter: int = 250,
    min_samples_leaf: int = 50,
) -> dict[str, Any]:
    """Execute Stage 1 & Stage 2 on October-November data and persist calibrated models."""
    started = perf_counter()
    train_csv = Path(train_csv_path).resolve()
    out_dir = Path(models_dir).resolve()

    if not train_csv.is_file():
        raise FileNotFoundError(f"Training session features CSV not found: {train_csv}")

    print(f"[Stage 1] Loading session features from {train_csv} ...")
    raw_df = pd.read_csv(train_csv)
    split_data = split_session_features_70_15_15(
        raw_df, sample_size=sample_size, random_state=random_state
    )

    X_train_fit = split_data["X_train_fit"]
    y_train_fit = split_data["y_train_fit"]
    X_val_calib = split_data["X_val_calib"]
    y_val_calib = split_data["y_val_calib"]
    X_val_select = split_data["X_val_select"]
    y_val_select = split_data["y_val_select"]

    print(
        f"[Stage 1] Split complete: Train_Fit={len(X_train_fit):,}, "
        f"Val_Calib={len(X_val_calib):,}, Val_Select={len(X_val_select):,}"
    )

    pipelines = build_candidate_pipelines(
        max_duration_sec=max_duration_sec,
        random_state=random_state,
        rf_n_estimators=rf_n_estimators,
        gb_max_iter=gb_max_iter,
        min_samples_leaf=min_samples_leaf,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    models_report: dict[str, Any] = {}
    calibrated_wrappers: dict[str, CalibratedModelWrapper] = {}

    for model_name in ALL_MODEL_NAMES:
        base_pipe = pipelines[model_name]
        display_name = MODEL_DISPLAY_NAMES[model_name]
        print(f"[Stage 2] Training base model: {display_name} ...")
        t0 = perf_counter()
        base_pipe.fit(X_train_fit, y_train_fit)
        train_elapsed = perf_counter() - t0

        # Evaluate uncalibrated probabilities on Val_Select
        uncal_val_proba = base_pipe.predict_proba(X_val_select)[:, 1]
        uncal_calib_stats = compute_calibration_curve_and_ece(y_val_select, uncal_val_proba)
        uncal_metrics = compute_classification_metrics(
            y_val_select, uncal_val_proba, threshold=0.50
        )

        # Fit both Isotonic and Sigmoid calibrators on Val_Calib
        t_cal = perf_counter()
        iso_wrapper = CalibratedModelWrapper(base_estimator=base_pipe, method="isotonic")
        iso_wrapper.fit_calibrator(X_val_calib, y_val_calib)
        iso_val_proba = iso_wrapper.predict_proba(X_val_select)[:, 1]
        iso_calib_stats = compute_calibration_curve_and_ece(y_val_select, iso_val_proba)

        sig_wrapper = CalibratedModelWrapper(base_estimator=base_pipe, method="sigmoid")
        sig_wrapper.fit_calibrator(X_val_calib, y_val_calib)
        sig_val_proba = sig_wrapper.predict_proba(X_val_select)[:, 1]
        sig_calib_stats = compute_calibration_curve_and_ece(y_val_select, sig_val_proba)
        calib_elapsed = perf_counter() - t_cal

        # Select calibration method with lower Brier score on Val_Select
        if iso_calib_stats["brier_score"] <= sig_calib_stats["brier_score"]:
            chosen_method = "isotonic"
            chosen_wrapper = iso_wrapper
            chosen_val_proba = iso_val_proba
            chosen_calib_stats = iso_calib_stats
        else:
            chosen_method = "sigmoid"
            chosen_wrapper = sig_wrapper
            chosen_val_proba = sig_val_proba
            chosen_calib_stats = sig_calib_stats

        # Tune decision threshold tau* on Val_Select calibrated probabilities
        threshold_info = find_optimal_threshold(y_val_select, chosen_val_proba)
        optimal_tau = threshold_info["optimal_threshold"]
        chosen_wrapper.set_optimal_threshold(optimal_tau)

        t_inf = perf_counter()
        _ = chosen_wrapper.predict_proba(X_val_select.iloc[: min(1000, len(X_val_select))])
        inference_ms_per_1k = (perf_counter() - t_inf) * 1000.0

        val_select_metrics = compute_classification_metrics(
            y_val_select, chosen_val_proba, threshold=optimal_tau
        )

        model_file = out_dir / f"{model_name}.joblib"
        joblib.dump(chosen_wrapper, model_file)
        calibrated_wrappers[model_name] = chosen_wrapper

        models_report[model_name] = {
            "model_name": model_name,
            "display_name": display_name,
            "is_ablation_no_cart": model_name == ABLATION_MODEL_NAME,
            "model_artifact_path": str(model_file),
            "train_time_sec": round(train_elapsed, 4),
            "calibration_time_sec": round(calib_elapsed, 4),
            "inference_ms_per_1k_sessions": round(inference_ms_per_1k, 4),
            "chosen_calibration_method": chosen_method,
            "optimal_threshold": optimal_tau,
            "val_select_metrics_calibrated": val_select_metrics,
            "val_select_metrics_uncalibrated_at_050": uncal_metrics,
            "calibration_comparison_on_val_select": {
                "uncalibrated": uncal_calib_stats,
                "isotonic": iso_calib_stats,
                "sigmoid": sig_calib_stats,
                "selected": chosen_calib_stats,
            },
        }
        print(
            f"  -> {model_name}: Val_Select PR-AUC={val_select_metrics['pr_auc']:.4f}, "
            f"ROC-AUC={val_select_metrics['roc_auc']:.4f}, "
            f"Brier (Uncal={uncal_calib_stats['brier_score']:.4f} -> Cal={chosen_calib_stats['brier_score']:.4f}), "
            f"tau*={optimal_tau:.4f} (F1={val_select_metrics['f1_at_threshold']:.4f})"
        )

    # Select champion among the 3 full-feature candidate models by PR-AUC on Val_Select
    ranking = sorted(
        CANDIDATE_MODEL_NAMES,
        key=lambda name: (
            models_report[name]["val_select_metrics_calibrated"]["pr_auc"],
            models_report[name]["val_select_metrics_calibrated"]["f1_at_threshold"],
            -models_report[name]["val_select_metrics_calibrated"]["brier_score"],
        ),
        reverse=True,
    )
    champion_name = ranking[0]
    champion_wrapper = calibrated_wrappers[champion_name]
    champion_info = models_report[champion_name]

    best_model_path = out_dir / "best_purchase_model.joblib"
    joblib.dump(champion_wrapper, best_model_path)

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    best_model_meta = {
        "generated_at_utc": generated_at,
        "champion_model_name": champion_name,
        "champion_display_name": champion_info["display_name"],
        "selection_metric": "PR-AUC (Average Precision on Val_Select)",
        "optimal_threshold": champion_info["optimal_threshold"],
        "calibration_method": champion_info["chosen_calibration_method"],
        "schema_version": SCHEMA_VERSION,
        "sklearn_version": sklearn.__version__,
        "input_feature_columns": list(SESSION_FEATURE_COLUMNS),
        "vnd_to_usd_rate": float(VND_TO_USD_RATE),
        "max_session_duration_sec": float(max_duration_sec),
        "partial_sample_run": split_data["split_summary"]["partial_sample_run"],
        "val_select_metrics": champion_info["val_select_metrics_calibrated"],
        "all_model_thresholds": {
            name: models_report[name]["optimal_threshold"] for name in ALL_MODEL_NAMES
        },
    }

    best_meta_path = out_dir / "best_model_meta.json"
    best_meta_path.write_text(
        json.dumps(best_model_meta, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    training_summary = {
        "generated_at_utc": generated_at,
        "sklearn_version": sklearn.__version__,
        "schema_version": SCHEMA_VERSION,
        "train_csv_path": str(train_csv),
        "models_dir": str(out_dir),
        "best_model_path": str(best_model_path),
        "best_model_meta_path": str(best_meta_path),
        "total_elapsed_seconds": round(perf_counter() - started, 3),
        "split_summary": split_data["split_summary"],
        "champion_model_name": champion_name,
        "candidate_ranking_by_val_pr_auc": list(ranking),
        "models": models_report,
    }

    summary_path = out_dir / "training_summary_meta.json"
    summary_path.write_text(
        json.dumps(training_summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"[Stage 2 Complete] Champion model: {champion_name} "
        f"(Val PR-AUC={champion_info['val_select_metrics_calibrated']['pr_auc']:.4f}, "
        f"tau*={champion_info['optimal_threshold']:.4f}) saved to {best_model_path}"
    )
    return training_summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Train, calibrate, and select purchase-intent models on Oct-Nov session features."
    )
    parser.add_argument(
        "--train-csv",
        type=Path,
        default=SESSION_FEATURES_PATH,
        help="Path to training session_features.csv (Oct + Nov).",
    )
    parser.add_argument(
        "--models-dir",
        type=Path,
        default=MODELS_DIR,
        help="Output directory for trained .joblib models and metadata.",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=None,
        help="Optional stratified sample size for quick smoke testing (e.g. 50000).",
    )
    parser.add_argument(
        "--random-state",
        type=int,
        default=DEFAULT_RANDOM_STATE,
        help="Random seed for reproducible splitting and training.",
    )
    args = parser.parse_args(argv)
    run_training_pipeline(
        train_csv_path=args.train_csv,
        models_dir=args.models_dir,
        sample_size=args.sample_size,
        random_state=args.random_state,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
