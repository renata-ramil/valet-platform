import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
import pandas as pd
from ml.eta.model import (
    FEATURE_COLUMNS,
    conformalize,
    empirical_coverage,
    fit_quantile_models,
    predict_interval,
)


def _toy_dataset(n: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    data = {col: rng.uniform(0, 5, n) for col in FEATURE_COLUMNS}
    # target is a simple function of one feature plus noise, so quantile models
    # have something real to learn and the calibration set isn't degenerate
    noise = rng.normal(0, 10, n)
    data["service_duration_seconds"] = (
        60 + 10 * data["queue_length_at_request"] + noise
    )
    return pd.DataFrame(data)


def test_conformal_calibration_reaches_target_coverage_on_held_out_data():
    train_df = _toy_dataset(600, seed=1)
    calib_df = _toy_dataset(300, seed=2)
    test_df = _toy_dataset(2000, seed=3)

    models = fit_quantile_models(train_df)
    calibration = conformalize(models, calib_df, target_coverage=0.9)

    interval_df = predict_interval(models, calibration, test_df)
    coverage = empirical_coverage(interval_df, test_df["service_duration_seconds"].to_numpy())

    # Split conformal guarantees marginal coverage >= target in expectation; allow
    # a small tolerance for finite-sample noise on 2000 test points
    assert coverage >= 0.87


def test_conformal_margin_is_nonnegative_when_quantiles_undercover():
    train_df = _toy_dataset(600, seed=4)
    calib_df = _toy_dataset(300, seed=5)
    models = fit_quantile_models(train_df)
    calibration = conformalize(models, calib_df, target_coverage=0.9)
    assert calibration.margin >= 0
