import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

import numpy as np
import pandas as pd

FEATURE_COLUMNS = [
    "queue_length_at_request",
    "free_valets_at_request",
    "blockers_at_assignment",
    "lane_depth_at_assignment",
    "hour_of_day",
    "scheduled_load_next_hour",
]
QUANTILES = (0.1, 0.5, 0.9)


def features(df: pd.DataFrame) -> np.ndarray:
    return df[FEATURE_COLUMNS].to_numpy(dtype=float)


def fit_quantile_models(train_df: pd.DataFrame) -> dict[float, object]:
    import lightgbm as lgb

    X = features(train_df)
    y = train_df["service_duration_seconds"].to_numpy(dtype=float)
    models = {}
    for q in QUANTILES:
        model = lgb.LGBMRegressor(
            objective="quantile", alpha=q, n_estimators=150, max_depth=4, verbose=-1
        )
        model.fit(X, y)
        models[q] = model
    return models


def predict_quantiles(models: dict[float, object], df: pd.DataFrame) -> pd.DataFrame:
    X = features(df)
    preds = {f"p{int(q * 100)}": models[q].predict(X) for q in QUANTILES}
    return pd.DataFrame(preds, index=df.index)


@dataclass
class ConformalCalibration:
    margin: float
    target_coverage: float = 0.9


def conformalize(
    models: dict[float, object], calib_df: pd.DataFrame, target_coverage: float = 0.9
) -> ConformalCalibration:
    """Split conformal prediction: widen the [p10, p90] interval by the smallest
    margin that achieves target_coverage on the calibration set, using the
    finite-sample-corrected quantile of conformity scores (CQR, Romano et al. 2019).
    """
    preds = predict_quantiles(models, calib_df)
    y = calib_df["service_duration_seconds"].to_numpy(dtype=float)
    scores = np.maximum(preds["p10"].to_numpy() - y, y - preds["p90"].to_numpy())
    n = len(scores)
    level = min(1.0, np.ceil((n + 1) * target_coverage) / n)
    margin = float(np.quantile(scores, level, method="higher"))
    return ConformalCalibration(margin=margin, target_coverage=target_coverage)


def predict_interval(
    models: dict[float, object], calibration: ConformalCalibration, df: pd.DataFrame
) -> pd.DataFrame:
    preds = predict_quantiles(models, df)
    return pd.DataFrame(
        {
            "low": preds["p10"] - calibration.margin,
            "median": preds["p50"],
            "high": preds["p90"] + calibration.margin,
        },
        index=df.index,
    )


def empirical_coverage(interval_df: pd.DataFrame, actual: np.ndarray) -> float:
    return float(
        ((actual >= interval_df["low"]) & (actual <= interval_df["high"])).mean()
    )


def average_width(interval_df: pd.DataFrame) -> float:
    return float((interval_df["high"] - interval_df["low"]).mean())
