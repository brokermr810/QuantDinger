"""Cross-sectional factor diagnostics."""

from __future__ import annotations

import math
from typing import Any, Mapping

import numpy as np
import pandas as pd


def winsorize_zscore(
    scores: Mapping[str, Any],
    *,
    lower_quantile: float = 0.01,
    upper_quantile: float = 0.99,
) -> dict[str, float]:
    series = _series(scores)
    if series.empty:
        return {}
    lower = float(series.quantile(lower_quantile))
    upper = float(series.quantile(upper_quantile))
    clipped = series.clip(lower=lower, upper=upper)
    std = float(clipped.std(ddof=0))
    normalized = (clipped - clipped.mean()) / std if std > 0 else clipped * 0.0
    return {str(index): float(value) for index, value in normalized.items()}


def information_coefficient(
    scores: Mapping[str, Any],
    forward_returns: Mapping[str, Any],
) -> dict[str, float]:
    left = _series(scores).rename("score")
    right = _series(forward_returns).rename("forward_return")
    joined = pd.concat([left, right], axis=1, join="inner").dropna()
    if len(joined) < 3:
        return {"ic": 0.0, "rank_ic": 0.0, "coverage": 0.0, "sample_count": len(joined)}
    denominator = max(1, len(set(left.index) | set(right.index)))
    return {
        "ic": _safe_correlation(joined["score"], joined["forward_return"], method="pearson"),
        "rank_ic": _safe_correlation(joined["score"], joined["forward_return"], method="spearman"),
        "coverage": len(joined) / denominator,
        "sample_count": len(joined),
    }


def quantile_returns(
    scores: Mapping[str, Any],
    forward_returns: Mapping[str, Any],
    *,
    quantiles: int = 5,
) -> list[dict]:
    left = _series(scores).rename("score")
    right = _series(forward_returns).rename("forward_return")
    joined = pd.concat([left, right], axis=1, join="inner").dropna()
    bucket_count = max(2, min(int(quantiles or 5), len(joined)))
    if len(joined) < 2:
        return []
    ranks = joined["score"].rank(method="first")
    joined["bucket"] = pd.qcut(ranks, q=bucket_count, labels=False, duplicates="drop") + 1
    output = []
    for bucket, frame in joined.groupby("bucket", sort=True):
        output.append({
            "quantile": int(bucket),
            "mean_return": float(frame["forward_return"].mean()),
            "count": int(len(frame)),
        })
    return output


def _series(values: Mapping[str, Any]) -> pd.Series:
    clean = {}
    for key, value in (values or {}).items():
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(parsed):
            clean[str(key)] = parsed
    return pd.Series(clean, dtype=float)


def _safe_correlation(left: pd.Series, right: pd.Series, *, method: str) -> float:
    if method == "spearman":
        value = left.rank(method="average").corr(right.rank(method="average"), method="pearson")
    else:
        value = left.corr(right, method="pearson")
    return float(value) if value is not None and np.isfinite(value) else 0.0
