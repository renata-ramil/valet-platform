import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
import pandas as pd
from ml.forecast.model import lightgbm_features, seasonal_naive_forecast, wape


def test_wape_zero_when_predictions_match():
    actual = np.array([1.0, 2.0, 3.0])
    assert wape(actual, actual) == 0.0


def test_wape_known_value():
    actual = np.array([2.0, 2.0])
    predicted = np.array([1.0, 3.0])
    # |2-1| + |2-3| = 2, sum(actual) = 4 -> wape = 0.5
    assert wape(actual, predicted) == 0.5


def test_wape_handles_zero_actuals():
    result = wape(np.array([0.0, 0.0]), np.array([1.0, 2.0]))
    assert result != result  # NaN != NaN


def test_seasonal_naive_forecast_is_mean_per_weekday_bucket():
    df = pd.DataFrame(
        {
            "weekday": [0, 0, 0, 1],
            "bucket": [10, 10, 11, 10],
            "count": [2, 4, 1, 5],
        }
    )
    result = seasonal_naive_forecast(df)
    row = result[(result["weekday"] == 0) & (result["bucket"] == 10)].iloc[0]
    assert row["mean"] == 3.0


def test_lightgbm_features_shape():
    df = pd.DataFrame({"weekday": [0, 1, 2], "bucket": [0, 48, 95]})
    features = lightgbm_features(df)
    assert features.shape == (3, 4)
