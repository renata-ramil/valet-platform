import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

import numpy as np
import pandas as pd
import pymc as pm

N_WEEKDAYS = 7
N_BUCKETS = 96
N_HOURS = 24


@dataclass
class ForecastModel:
    trace: object
    model: object


def fit_hierarchical_nb(
    train_df: pd.DataFrame,
    draws: int = 600,
    tune: int = 800,
    chains: int = 4,
    target_accept: float = 0.92,
    seed: int = 0,
) -> ForecastModel:
    """Hierarchical negative binomial: log(mu) = intercept + weekday effect (partial
    pooling across weekdays) + a smooth time-of-day curve (GaussianRandomWalk over
    15-minute buckets, mean-centered to avoid confounding with the intercept) +
    weekday-specific hourly deviations from that curve (partial pooling again)."""
    weekday_idx = train_df["weekday"].values
    bucket_idx = train_df["bucket"].values
    hour_idx = (train_df["bucket"] // 4).values
    counts = train_df["count"].values

    with pm.Model() as model:
        sigma_weekday = pm.HalfNormal("sigma_weekday", 0.5)
        weekday_effect = pm.Normal("weekday_effect", 0, sigma_weekday, shape=N_WEEKDAYS)

        sigma_grw = pm.HalfNormal("sigma_grw", 0.2)
        global_bucket_raw = pm.GaussianRandomWalk(
            "global_bucket_raw",
            sigma=sigma_grw,
            shape=N_BUCKETS,
            init_dist=pm.Normal.dist(0, 0.1),
        )
        global_bucket = pm.Deterministic(
            "global_bucket", global_bucket_raw - global_bucket_raw.mean()
        )

        sigma_dev = pm.HalfNormal("sigma_dev", 0.3)
        weekday_deviation = pm.Normal(
            "weekday_deviation", 0, sigma_dev, shape=(N_WEEKDAYS, N_HOURS)
        )

        intercept = pm.Normal("intercept", 0, 2)

        log_mu = (
            intercept
            + weekday_effect[weekday_idx]
            + global_bucket[bucket_idx]
            + weekday_deviation[weekday_idx, hour_idx]
        )
        mu = pm.math.exp(log_mu)
        alpha = pm.HalfNormal("alpha", 5)

        pm.NegativeBinomial("obs", mu=mu, alpha=alpha, observed=counts)

        trace = pm.sample(
            draws=draws,
            tune=tune,
            chains=chains,
            target_accept=target_accept,
            random_seed=seed,
            progressbar=False,
        )
    return ForecastModel(trace=trace, model=model)


def predict_hierarchical_nb(
    fitted: ForecastModel, weekday: int, buckets: list[int] | None = None
) -> pd.DataFrame:
    """Posterior mean and 80%/95% intervals for every bucket of the given weekday,
    derived directly from the posterior draws (no new sampling needed)."""
    buckets = buckets if buckets is not None else list(range(N_BUCKETS))
    post = fitted.trace.posterior
    intercept = post["intercept"].values.reshape(-1)
    weekday_effect = post["weekday_effect"].values.reshape(-1, N_WEEKDAYS)[:, weekday]
    global_bucket = post["global_bucket"].values.reshape(-1, N_BUCKETS)
    weekday_deviation = post["weekday_deviation"].values.reshape(-1, N_WEEKDAYS, N_HOURS)[
        :, weekday, :
    ]
    alpha = post["alpha"].values.reshape(-1)

    rows = []
    rng = np.random.default_rng(0)
    for bucket in buckets:
        hour = bucket // 4
        log_mu = intercept + weekday_effect + global_bucket[:, bucket] + weekday_deviation[:, hour]
        mu = np.exp(log_mu)
        # Draw from the NB to get predictive (not just mean) intervals
        p = alpha / (alpha + mu)
        draws = rng.negative_binomial(alpha, p)
        rows.append(
            {
                "weekday": weekday,
                "bucket": bucket,
                "mean": float(mu.mean()),
                "low80": float(np.quantile(draws, 0.10)),
                "high80": float(np.quantile(draws, 0.90)),
                "low95": float(np.quantile(draws, 0.025)),
                "high95": float(np.quantile(draws, 0.975)),
            }
        )
    return pd.DataFrame(rows)


def seasonal_naive_forecast(train_df: pd.DataFrame) -> pd.DataFrame:
    """Mean count observed for each (weekday, bucket) so far."""
    return (
        train_df.groupby(["weekday", "bucket"])["count"]
        .mean()
        .reset_index()
        .rename(columns={"count": "mean"})
    )


def fit_lightgbm_baseline(train_df: pd.DataFrame):
    import lightgbm as lgb

    bucket = train_df["bucket"].values
    features = np.column_stack(
        [
            train_df["weekday"].values,
            bucket,
            np.sin(2 * np.pi * bucket / N_BUCKETS),
            np.cos(2 * np.pi * bucket / N_BUCKETS),
        ]
    )
    target = train_df["count"].values
    model = lgb.LGBMRegressor(objective="poisson", n_estimators=200, verbose=-1)
    model.fit(features, target)
    return model


def lightgbm_features(df: pd.DataFrame) -> np.ndarray:
    bucket = df["bucket"].values
    return np.column_stack(
        [
            df["weekday"].values,
            bucket,
            np.sin(2 * np.pi * bucket / N_BUCKETS),
            np.cos(2 * np.pi * bucket / N_BUCKETS),
        ]
    )


def wape(actual: np.ndarray, predicted: np.ndarray) -> float:
    denom = np.abs(actual).sum()
    if denom == 0:
        return float("nan")
    return float(np.abs(actual - predicted).sum() / denom)
