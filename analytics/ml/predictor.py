"""Stage 4: Web Inference Adapter for the TechGear Django Website.

Bridges live `analytics.models.Session` / `analytics.models.Event` records
with the calibrated purchase-intent model (`best_purchase_model.joblib`),
handling:
1. Currency domain adaptation: VND -> USD (`price / vnd_to_usd_rate`).
2. Dead-feature mitigation (`remove_cart_count = 0` in Kaggle): computes
   effective net cart count `max(0, add_to_cart - remove_from_cart)` so cart
   removals on the website accurately reduce purchase probability.
3. Anti-leakage cutoff: only uses events strictly before the first `checkout`.
"""

from __future__ import annotations

from datetime import timezone as dt_timezone
import json
import math
from pathlib import Path
from typing import Any, Iterable

import joblib
import pandas as pd

from analytics.ml.config import (
    BEST_MODEL_META_PATH,
    BEST_MODEL_PATH,
    MAX_SESSION_DURATION_SEC,
    SESSION_FEATURE_COLUMNS,
    VND_TO_USD_RATE,
)

_MODEL_CACHE: dict[str, Any] = {}


def resolve_analytics_session(request=None, session_id=None, user=None):
    from .purchase_intent import resolve_analytics_session as resolve
    return resolve(request=request, session_id=session_id, user=user)


def build_consultation_strategy(prediction_result):
    from .purchase_intent import build_consultation_strategy as build
    return build(prediction_result)


def get_customer_purchase_intent_payload(request=None, session_id=None, user_id=None):
    from .purchase_intent import get_customer_purchase_intent_payload as payload
    return payload(request=request, session_id=session_id, user_id=user_id)


def clear_predictor_cache() -> None:
    """Clear in-memory cached model and metadata."""
    _MODEL_CACHE.clear()


def load_best_model_and_meta(
    model_path: Path | str = BEST_MODEL_PATH,
    meta_path: Path | str = BEST_MODEL_META_PATH,
) -> tuple[Any, dict[str, Any]]:
    """Load and cache `best_purchase_model.joblib` and `best_model_meta.json`."""
    resolved_model = Path(model_path).resolve()
    resolved_meta = Path(meta_path).resolve()

    if not resolved_model.is_file():
        raise FileNotFoundError(f"Trained purchase model not found: {resolved_model}")
    if not resolved_meta.is_file():
        raise FileNotFoundError(f"Trained model metadata not found: {resolved_meta}")

    cache_key = (
        f"{resolved_model}:{resolved_model.stat().st_mtime_ns}:"
        f"{resolved_meta}:{resolved_meta.stat().st_mtime_ns}"
    )
    cached = _MODEL_CACHE.get(cache_key)
    if cached is not None:
        return cached

    model = joblib.load(resolved_model)
    meta = json.loads(resolved_meta.read_text(encoding="utf-8"))
    _MODEL_CACHE.clear()
    _MODEL_CACHE[cache_key] = (model, meta)
    return model, meta


def _resolve_event_price_usd(event_obj: Any, vnd_to_usd_rate: float) -> float:
    """Extract positive price in USD from a Django Event or Product (stored in VND)."""
    raw_val = getattr(event_obj, "event_value", None)
    if raw_val is None or float(raw_val) <= 0:
        product = getattr(event_obj, "product", None)
        if product is not None:
            raw_val = getattr(product, "price", None)

    if raw_val is None:
        return 0.0
    val = float(raw_val)
    if not math.isfinite(val) or val <= 0:
        return 0.0

    # Convert VND prices to USD scale matching the Kaggle training distribution
    rate = float(vnd_to_usd_rate) if vnd_to_usd_rate and vnd_to_usd_rate > 0 else VND_TO_USD_RATE
    return val / rate


def extract_live_session_features(
    session_or_events: Any,
    vnd_to_usd_rate: float = VND_TO_USD_RATE,
    default_price_usd: float = 50.0,
) -> dict[str, Any]:
    """Extract the 14 session features from a Django `Session` or iterable of `Event` objects."""
    session_id = "live-session"
    if hasattr(session_or_events, "event_set"):
        session_id = str(getattr(session_or_events, "pk", "live-session"))
        events_qs = (
            session_or_events.event_set.select_related("product", "product__category")
            .order_by("created_at", "id")
        )
        events_list = list(events_qs)
    elif isinstance(session_or_events, Iterable):
        events_list = sorted(
            list(session_or_events),
            key=lambda e: (getattr(e, "created_at", None), getattr(e, "id", 0) or 0),
        )
        if events_list and getattr(events_list[0], "session_id", None):
            session_id = str(events_list[0].session_id)
    else:
        raise TypeError("Expected an analytics.models.Session instance or iterable of Event objects")

    # Anti-leakage cutoff: only keep events strictly before the first checkout event
    checkout_times = [
        e.created_at
        for e in events_list
        if getattr(e, "event_type", None) == "checkout" and getattr(e, "created_at", None) is not None
    ]
    first_checkout = min(checkout_times) if checkout_times else None
    if first_checkout is not None:
        observed = [
            e
            for e in events_list
            if getattr(e, "event_type", None) in ("view_product", "add_to_cart", "remove_from_cart")
            and getattr(e, "created_at", None) is not None and e.created_at < first_checkout
        ]
    else:
        observed = [
            e
            for e in events_list
            if getattr(e, "event_type", None) in ("view_product", "add_to_cart", "remove_from_cart")
        ]

    if not observed:
        return {
            "user_session": session_id,
            "view_count": 0,
            "unique_products": 0,
            "unique_categories": 0,
            "cart_count": 0,
            "remove_cart_count": 0,
            "session_duration_sec": 0.0,
            "avg_price": float(default_price_usd),
            "max_price": float(default_price_usd),
            "min_price": float(default_price_usd),
            "repeat_view_ratio": 0.0,
            "cart_to_view_ratio": 0.0,
            "hour": 12,
            "day_of_week": 0,
            "is_weekend": 0,
            "raw_add_to_cart_count": 0,
            "raw_remove_from_cart_count": 0,
            "effective_cart_count": 0,
        }

    view_count = 0
    raw_add_cart = 0
    raw_remove_cart = 0
    all_products: set[Any] = set()
    viewed_products: set[Any] = set()
    categories: set[Any] = set()
    prices_usd: list[float] = []
    timestamps = []

    for ev in observed:
        etype = getattr(ev, "event_type", "")
        pid = getattr(ev, "product_id", None)
        product = getattr(ev, "product", None)
        if pid is not None:
            all_products.add(pid)
        if product is not None and getattr(product, "category_id", None) is not None:
            categories.add(product.category_id)
        elif pid is not None:
            categories.add(f"cat_of_{pid}")

        if etype == "view_product":
            view_count += 1
            if pid is not None:
                viewed_products.add(pid)
        elif etype == "add_to_cart":
            raw_add_cart += 1
        elif etype == "remove_from_cart":
            raw_remove_cart += 1

        price_usd = _resolve_event_price_usd(ev, vnd_to_usd_rate=vnd_to_usd_rate)
        if price_usd > 0:
            prices_usd.append(price_usd)

        created_at = getattr(ev, "created_at", None)
        if created_at is not None:
            timestamps.append(created_at)

    # Effective net cart count handles cart removals on the website
    effective_cart_count = max(0, raw_add_cart - raw_remove_cart)
    denom = max(view_count, 1)
    repeat_view_ratio = max(0.0, float(view_count - len(viewed_products)) / float(denom))
    cart_to_view_ratio = float(effective_cart_count) / float(denom)

    if timestamps:
        first_ts = min(timestamps)
        last_ts = max(timestamps)
        duration_sec = max(0.0, float((last_ts - first_ts).total_seconds()))
        duration_sec = min(duration_sec, float(MAX_SESSION_DURATION_SEC))
        utc_first = (
            first_ts.astimezone(dt_timezone.utc)
            if getattr(first_ts, "tzinfo", None) is not None
            else first_ts
        )
        hour = int(utc_first.hour)
        day_of_week = int(utc_first.weekday())
        is_weekend = 1 if day_of_week in (5, 6) else 0
    else:
        duration_sec = 0.0
        hour = 12
        day_of_week = 0
        is_weekend = 0

    if prices_usd:
        avg_price = float(sum(prices_usd) / len(prices_usd))
        max_price = float(max(prices_usd))
        min_price = float(min(prices_usd))
    else:
        avg_price = float(default_price_usd)
        max_price = float(default_price_usd)
        min_price = float(default_price_usd)

    return {
        "user_session": session_id,
        "view_count": int(view_count),
        "unique_products": int(max(len(all_products), 1 if observed else 0)),
        "unique_categories": int(max(len(categories), 1 if observed else 0)),
        "cart_count": int(effective_cart_count),
        "remove_cart_count": int(raw_remove_cart),
        "session_duration_sec": round(duration_sec, 4),
        "avg_price": round(avg_price, 4),
        "max_price": round(max_price, 4),
        "min_price": round(min_price, 4),
        "repeat_view_ratio": round(repeat_view_ratio, 6),
        "cart_to_view_ratio": round(cart_to_view_ratio, 6),
        "hour": int(hour),
        "day_of_week": int(day_of_week),
        "is_weekend": int(is_weekend),
        "raw_add_to_cart_count": int(raw_add_cart),
        "raw_remove_from_cart_count": int(raw_remove_cart),
        "effective_cart_count": int(effective_cart_count),
    }


def _classify_intent_level(probability: float, optimal_threshold: float) -> str:
    if probability >= optimal_threshold:
        return "high"
    if probability >= optimal_threshold * 0.5:
        return "medium"
    return "low"


def predict_from_feature_dict(
    feature_dict: dict[str, Any],
    model_path: Path | str = BEST_MODEL_PATH,
    meta_path: Path | str = BEST_MODEL_META_PATH,
) -> dict[str, Any]:
    """Predict calibrated purchase probability and binary label from a 14-feature dict."""
    model, meta = load_best_model_and_meta(model_path=model_path, meta_path=meta_path)
    optimal_threshold = float(meta.get("optimal_threshold", 0.5))

    row_df = pd.DataFrame(
        [{col: feature_dict[col] for col in SESSION_FEATURE_COLUMNS}],
        columns=SESSION_FEATURE_COLUMNS,
    )
    cal_prob = float(model.predict_proba(row_df)[0, 1])
    raw_prob = (
        float(model.predict_raw_proba(row_df)[0, 1])
        if hasattr(model, "predict_raw_proba")
        else cal_prob
    )
    will_purchase = bool(cal_prob >= optimal_threshold)

    return {
        "user_session": str(feature_dict.get("user_session", "live-session")),
        "purchase_probability": round(cal_prob, 6),
        "uncalibrated_probability": round(raw_prob, 6),
        "will_purchase": will_purchase,
        "intent_level": _classify_intent_level(cal_prob, optimal_threshold),
        "optimal_threshold": round(optimal_threshold, 4),
        "champion_model_name": meta.get("champion_model_name", "unknown"),
        "features": {col: feature_dict[col] for col in SESSION_FEATURE_COLUMNS},
    }


def predict_session_purchase_intent(
    session_or_events: Any,
    model_path: Path | str = BEST_MODEL_PATH,
    meta_path: Path | str = BEST_MODEL_META_PATH,
    vnd_to_usd_rate: float | None = None,
) -> dict[str, Any]:
    """Extract live session features from Django ORM and return calibrated purchase prediction."""
    _, meta = load_best_model_and_meta(model_path=model_path, meta_path=meta_path)
    rate = (
        float(vnd_to_usd_rate)
        if vnd_to_usd_rate is not None
        else float(meta.get("vnd_to_usd_rate", VND_TO_USD_RATE))
    )
    extracted = extract_live_session_features(
        session_or_events, vnd_to_usd_rate=rate
    )
    if (
        extracted["view_count"] == 0
        and extracted["raw_add_to_cart_count"] == 0
        and extracted["raw_remove_from_cart_count"] == 0
    ):
        optimal_threshold = float(meta.get("optimal_threshold", 0.5))
        return {
            "user_session": extracted["user_session"],
            "purchase_probability": 0.0,
            "uncalibrated_probability": 0.0,
            "will_purchase": False,
            "intent_level": "low",
            "optimal_threshold": round(optimal_threshold, 4),
            "champion_model_name": meta.get("champion_model_name", "unknown"),
            "features": {col: extracted[col] for col in SESSION_FEATURE_COLUMNS},
        }
    result = predict_from_feature_dict(
        extracted, model_path=model_path, meta_path=meta_path
    )
    result["raw_add_to_cart_count"] = extracted["raw_add_to_cart_count"]
    result["raw_remove_from_cart_count"] = extracted["raw_remove_from_cart_count"]
    result["effective_cart_count"] = extracted["effective_cart_count"]
    return result
