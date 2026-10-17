from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import beta as beta_dist

CLUSTER_GAP_MINUTES = 30
MIN_OBSERVATIONS = 3
RECURRENCE_THRESHOLD = 0.6
WEEKDAY_MERGE_TOLERANCE_MINUTES = 20


@dataclass
class Suggestion:
    weekdays: list[int]
    time_minutes: float  # minutes since midnight
    recurrence_probability: float
    observations: int
    weeks_observed: int

    @property
    def hour(self) -> int:
        return int(self.time_minutes // 60)

    @property
    def minute(self) -> int:
        return int(self.time_minutes % 60)


def _cluster_times(times: list[float]) -> list[list[float]]:
    if not times:
        return []
    times = sorted(times)
    clusters = [[times[0]]]
    for t in times[1:]:
        if t - clusters[-1][-1] <= CLUSTER_GAP_MINUTES:
            clusters[-1].append(t)
        else:
            clusters.append([t])
    return clusters


def _weekday_candidates(weekday_requests: pd.DataFrame, total_weeks: int) -> list[Suggestion]:
    times = weekday_requests["time_minutes"].tolist()
    candidates = []
    for cluster in _cluster_times(times):
        successes = len(cluster)
        if successes < MIN_OBSERVATIONS:
            continue
        posterior = beta_dist(1 + successes, 1 + max(0, total_weeks - successes))
        recurrence_probability = float(posterior.mean())
        if recurrence_probability < RECURRENCE_THRESHOLD:
            continue
        candidates.append(
            Suggestion(
                weekdays=[],  # filled in by the caller once merged across weekdays
                time_minutes=float(np.mean(cluster)),
                recurrence_probability=recurrence_probability,
                observations=successes,
                weeks_observed=total_weeks,
            )
        )
    return candidates


def detect_recurring_slots(
    history: pd.DataFrame, weeks_of_history: int | None = None
) -> list[Suggestion]:
    """history: columns [weekday, time_minutes, week_index]. Returns merged
    suggestions (weekdays grouped when their cluster centers are close), using a
    beta-binomial posterior on how often a slot recurs out of the weeks observed.
    """
    if history.empty:
        return []
    total_weeks = weeks_of_history or (int(history["week_index"].max()) + 1)

    per_weekday: dict[int, list[Suggestion]] = {}
    for weekday in sorted(history["weekday"].unique()):
        subset = history[history["weekday"] == weekday]
        per_weekday[int(weekday)] = _weekday_candidates(subset, total_weeks)

    # Merge weekdays whose best candidate cluster centers are close together
    unmerged = [
        (weekday, candidate)
        for weekday, candidates in per_weekday.items()
        for candidate in candidates
    ]
    merged: list[Suggestion] = []
    used = [False] * len(unmerged)
    for i, (weekday_i, cand_i) in enumerate(unmerged):
        if used[i]:
            continue
        group_weekdays = [weekday_i]
        group_times = [cand_i.time_minutes]
        group_obs = cand_i.observations
        used[i] = True
        for j in range(i + 1, len(unmerged)):
            if used[j]:
                continue
            weekday_j, cand_j = unmerged[j]
            if abs(cand_j.time_minutes - cand_i.time_minutes) <= WEEKDAY_MERGE_TOLERANCE_MINUTES:
                group_weekdays.append(weekday_j)
                group_times.append(cand_j.time_minutes)
                group_obs += cand_j.observations
                used[j] = True
        merged.append(
            Suggestion(
                weekdays=sorted(group_weekdays),
                time_minutes=float(np.mean(group_times)),
                recurrence_probability=cand_i.recurrence_probability,
                observations=group_obs,
                weeks_observed=total_weeks,
            )
        )
    return merged
