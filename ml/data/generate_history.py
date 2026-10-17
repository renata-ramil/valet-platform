import copy
import random
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

import pandas as pd
from policies.interfaces import NearestFreeSpotAssigner
from sim.run import load_scenario
from sim.simulation import run_scenario

WEEKS = 12
DAYS = WEEKS * 7
START_DATE = date(2026, 1, 5)  # a Monday
BUCKET_MINUTES = 15
BUCKETS_PER_DAY = (24 * 60) // BUCKET_MINUTES

OUT_DIR = Path(__file__).resolve().parent
ORIGIN = "simulated"


def _day_params(rng: random.Random, weekday: int) -> tuple[dict, str]:
    """weekday: 0=Monday .. 6=Sunday. Returns (params, anomaly_label)."""
    is_weekend = weekday >= 5
    base = load_scenario("weekend_calm" if is_weekend else "weekday_peak")
    params = copy.deepcopy(base)

    anomaly = "none"
    # A seasonal wobble so the forecast has something smooth to track, plus a
    # small chance of an evening event and a rare demand anomaly
    seasonal_factor = 1.0 + 0.15 * ((weekday - 2) / 7.0)
    params["commuters"]["count"] = max(1, round(params["commuters"]["count"] * seasonal_factor))

    if not is_weekend and rng.random() < 0.12:
        params["evening_event"] = {
            "enabled": True,
            "start_hour": 19.0,
            "count": rng.randint(10, 20),
            "spread_minutes": 20.0,
        }
        anomaly = "evening_event"

    if rng.random() < 0.025:
        multiplier = rng.choice([0.3, 2.0])
        params["commuters"]["count"] = max(1, round(params["commuters"]["count"] * multiplier))
        params["on_demand"]["base_rate_per_hour"] *= multiplier
        anomaly = f"demand_x{multiplier}"

    return params, anomaly


def generate(seed: int = 0) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = random.Random(seed)
    demand_rows = []
    eta_rows = []

    for day_index in range(DAYS):
        current_date = START_DATE + timedelta(days=day_index)
        weekday = current_date.weekday()
        params, anomaly = _day_params(rng, weekday)

        result = run_scenario(
            params, seed=rng.randint(0, 2**31 - 1), spot_assigner=NearestFreeSpotAssigner()
        )

        bucket_counts = [0] * BUCKETS_PER_DAY
        for request in result.requests:
            bucket = min(
                BUCKETS_PER_DAY - 1, int(request.request_time // (BUCKET_MINUTES * 60))
            )
            bucket_counts[bucket] += 1
            if request.delivered_at is not None and request.service_duration_seconds is not None:
                eta_rows.append(
                    {
                        "date": current_date.isoformat(),
                        "weekday": weekday,
                        "source": request.source,
                        "queue_length_at_request": request.queue_length_at_request,
                        "free_valets_at_request": request.free_valets_at_request,
                        "blockers_at_assignment": request.blockers_at_assignment,
                        "lane_depth_at_assignment": request.lane_depth_at_assignment,
                        "hour_of_day": request.hour_of_day,
                        "scheduled_load_next_hour": request.scheduled_load_next_hour,
                        "service_duration_seconds": request.service_duration_seconds,
                        "anomaly": anomaly,
                    }
                )

        for bucket, count in enumerate(bucket_counts):
            demand_rows.append(
                {
                    "date": current_date.isoformat(),
                    "day_index": day_index,
                    "weekday": weekday,
                    "bucket": bucket,
                    "count": count,
                    "anomaly": anomaly,
                }
            )

        if (day_index + 1) % 7 == 0:
            print(f"  generated {day_index + 1}/{DAYS} days")

    demand_df = pd.DataFrame(demand_rows)
    demand_df["origin"] = ORIGIN
    eta_df = pd.DataFrame(eta_rows)
    eta_df["origin"] = ORIGIN
    return demand_df, eta_df


def main() -> None:
    print(f"Generating {WEEKS} weeks ({DAYS} days) of simulated request history")
    demand_df, eta_df = generate()
    demand_path = OUT_DIR / "history_demand.parquet"
    eta_path = OUT_DIR / "history_eta.parquet"
    demand_df.to_parquet(demand_path, index=False)
    eta_df.to_parquet(eta_path, index=False)
    print(f"Wrote {demand_path} ({len(demand_df)} rows)")
    print(f"Wrote {eta_path} ({len(eta_df)} rows)")


if __name__ == "__main__":
    main()
