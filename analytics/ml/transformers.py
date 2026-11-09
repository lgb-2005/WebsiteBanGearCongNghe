"""Custom scikit-learn transformers and probability calibration wrappers.

This module has ZERO Django dependencies so it can run seamlessly on both
Google Colab Extension kernels and the local Django web server without
causing `__main__` pickle/joblib deserialization errors.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, ClassifierMixin, TransformerMixin
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

from analytics.ml.config import (
    EARLY_INTENT_EXCLUDED_COLUMNS,
    MAX_SESSION_DURATION_SEC,
    SESSION_FEATURE_COLUMNS,
)

LOG1P_CANDIDATE_COLUMNS = (
    "view_count",
    "unique_products",
    "unique_categories",
    "cart_count",
    "session_duration_sec",
    "avg_price",
    "max_price",
    "min_price",
    "cart_to_view_ratio",
)


class SessionFeatureTransformer(BaseEstimator, TransformerMixin):
    """Mitigate session duration outliers, right-skewness, and price domain shift.

    Transformations performed (without mutating the caller's DataFrame):
    1. Clips `session_duration_sec` to `[0.0, max_duration_sec]` (default 3600s)
       to eliminate 57-day cookie outliers and mitigate right-censoring cutoff bias.
    2. Adds dimensionless `price_range_ratio = (max_price - min_price) / max(avg_price, 1e-3)`
       which is invariant to USD vs. VND currency scaling.
    3. Optionally drops cart-related features (`drop_cart_features=True`) for the
       Early-Intent browsing-only ablation model.
    4. Applies `np.log1p` to skewed count, duration, and price columns.
    """

    def __init__(
        self,
        max_duration_sec: float = MAX_SESSION_DURATION_SEC,
        add_price_range_ratio: bool = True,
        drop_cart_features: bool = False,
    ) -> None:
        self.max_duration_sec = max_duration_sec
        self.add_price_range_ratio = add_price_range_ratio
        self.drop_cart_features = drop_cart_features

    def _prepare_dataframe(self, X: pd.DataFrame | np.ndarray) -> pd.DataFrame:
        if isinstance(X, pd.DataFrame):
            missing = [col for col in SESSION_FEATURE_COLUMNS if col not in X.columns]
            if missing:
                raise ValueError(
                    f"Missing required session feature columns: {', '.join(missing)}"
                )
            df = X[SESSION_FEATURE_COLUMNS].copy()
        else:
            arr = np.asarray(X, dtype=np.float64)
            if arr.ndim != 2 or arr.shape[1] != len(SESSION_FEATURE_COLUMNS):
                raise ValueError(
                    f"Expected 2D input with {len(SESSION_FEATURE_COLUMNS)} columns"
                )
            df = pd.DataFrame(arr, columns=SESSION_FEATURE_COLUMNS)

        for col in SESSION_FEATURE_COLUMNS:
            df[col] = pd.to_numeric(df[col], errors="raise").astype(np.float64)
        if not np.isfinite(df.to_numpy()).all():
            raise ValueError("Input features contain NaN or infinite values")
        return df

    def _compute_feature_names(self) -> list[str]:
        cols = [
            col
            for col in SESSION_FEATURE_COLUMNS
            if not (self.drop_cart_features and col in EARLY_INTENT_EXCLUDED_COLUMNS)
        ]
        if self.add_price_range_ratio:
            cols.append("price_range_ratio")
        return cols

    def fit(self, X: pd.DataFrame | np.ndarray, y: np.ndarray | None = None) -> SessionFeatureTransformer:
        if self.max_duration_sec <= 0:
            raise ValueError("max_duration_sec must be positive")
        _ = self._prepare_dataframe(X)
        self.n_features_in_ = len(SESSION_FEATURE_COLUMNS)
        self.feature_names_in_ = np.array(SESSION_FEATURE_COLUMNS, dtype=object)
        self.output_feature_names_ = self._compute_feature_names()
        return self

    def transform(self, X: pd.DataFrame | np.ndarray) -> np.ndarray:
        df = self._prepare_dataframe(X)

        df["session_duration_sec"] = np.clip(
            df["session_duration_sec"].to_numpy(), 0.0, float(self.max_duration_sec)
        )

        if self.add_price_range_ratio:
            safe_avg = np.clip(df["avg_price"].to_numpy(), 1e-3, None)
            spread = np.clip(
                df["max_price"].to_numpy() - df["min_price"].to_numpy(), 0.0, None
            )
            df["price_range_ratio"] = np.log1p(spread / safe_avg)

        if self.drop_cart_features:
            df = df.drop(columns=list(EARLY_INTENT_EXCLUDED_COLUMNS))

        for col in LOG1P_CANDIDATE_COLUMNS:
            if col in df.columns:
                df[col] = np.log1p(np.clip(df[col].to_numpy(), 0.0, None))

        ordered_cols = getattr(self, "output_feature_names_", self._compute_feature_names())
        out = df[ordered_cols].to_numpy(dtype=np.float64, copy=True)
        if not np.isfinite(out).all():
            raise ValueError("Transformed features contain non-finite values")
        return out

    def get_feature_names_out(self, input_features: list[str] | None = None) -> np.ndarray:
        names = getattr(self, "output_feature_names_", self._compute_feature_names())
        return np.asarray(names, dtype=object)


def _logit(prob: np.ndarray) -> np.ndarray:
    clipped = np.clip(np.asarray(prob, dtype=np.float64), 1e-6, 1.0 - 1e-6)
    return np.log(clipped / (1.0 - clipped)).reshape(-1, 1)


class CalibratedModelWrapper(BaseEstimator, ClassifierMixin):
    """Post-hoc probability calibrator fitted on a dedicated held-out validation split.

    Corrects the probability inflation introduced by `class_weight='balanced'`
    (1 : 19.94 imbalance) and tree-ensemble variance without retraining the
    underlying base pipeline.
    """

    def __init__(
        self,
        base_estimator: BaseEstimator,
        method: str = "isotonic",
        optimal_threshold: float = 0.5,
    ) -> None:
        self.base_estimator = base_estimator
        self.method = method
        self.optimal_threshold = optimal_threshold

    def fit_calibrator(
        self,
        X_calib: pd.DataFrame | np.ndarray,
        y_calib: pd.Series | np.ndarray,
    ) -> CalibratedModelWrapper:
        if self.method not in ("isotonic", "sigmoid"):
            raise ValueError("Calibration method must be 'isotonic' or 'sigmoid'")
        y_arr = np.asarray(y_calib, dtype=np.int64)
        raw_pos = self.predict_raw_proba(X_calib)[:, 1]

        if self.method == "isotonic":
            calibrator = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
            calibrator.fit(raw_pos, y_arr)
        else:
            calibrator = LogisticRegression(C=1e6, solver="lbfgs", max_iter=500, random_state=42)
            calibrator.fit(_logit(raw_pos), y_arr)

        self.calibrator_ = calibrator
        self.classes_ = np.array([0, 1], dtype=np.int64)
        self.optimal_threshold_ = float(self.optimal_threshold)
        return self

    def fit(
        self,
        X: pd.DataFrame | np.ndarray,
        y: pd.Series | np.ndarray,
    ) -> CalibratedModelWrapper:
        self.base_estimator.fit(X, y)
        return self.fit_calibrator(X, y)

    def predict_raw_proba(self, X: pd.DataFrame | np.ndarray) -> np.ndarray:
        raw = np.asarray(self.base_estimator.predict_proba(X), dtype=np.float64)
        if raw.ndim == 1:
            pos = np.clip(raw, 0.0, 1.0)
            return np.column_stack([1.0 - pos, pos])
        pos = np.clip(raw[:, 1], 0.0, 1.0)
        return np.column_stack([1.0 - pos, pos])

    def predict_proba(self, X: pd.DataFrame | np.ndarray) -> np.ndarray:
        raw_pos = self.predict_raw_proba(X)[:, 1]
        if not hasattr(self, "calibrator_"):
            return np.column_stack([1.0 - raw_pos, raw_pos])

        if self.method == "isotonic":
            cal_pos = np.asarray(self.calibrator_.predict(raw_pos), dtype=np.float64)
        else:
            cal_pos = np.asarray(
                self.calibrator_.predict_proba(_logit(raw_pos))[:, 1],
                dtype=np.float64,
            )
        cal_pos = np.clip(cal_pos, 0.0, 1.0)
        return np.column_stack([1.0 - cal_pos, cal_pos])

    def set_optimal_threshold(self, threshold: float) -> None:
        value = float(threshold)
        if not (0.0 < value < 1.0):
            raise ValueError("optimal_threshold must be strictly between 0 and 1")
        self.optimal_threshold = value
        self.optimal_threshold_ = value

    def predict(
        self,
        X: pd.DataFrame | np.ndarray,
        threshold: float | None = None,
    ) -> np.ndarray:
        cutoff = (
            float(threshold)
            if threshold is not None
            else float(getattr(self, "optimal_threshold_", self.optimal_threshold))
        )
        pos_proba = self.predict_proba(X)[:, 1]
        return (pos_proba >= cutoff).astype(np.int64)
