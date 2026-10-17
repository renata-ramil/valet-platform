import random
from dataclasses import dataclass


@dataclass
class RequestSeed:
    request_time: float  # seconds from midnight when the request is created
    ready_by: float  # seconds from midnight the car should be ready
    source: str  # commuter, on_demand, evening


def generate_commuters(
    rng: random.Random,
    count: int,
    ready_by_hour: float,
    jitter_minutes_std: float,
    skip_probability: float,
    lead_minutes_range: tuple[float, float] = (5.0, 45.0),
) -> list[RequestSeed]:
    """Residents with a fixed daily ready-by time, lateness jitter and a chance to skip."""
    requests = []
    for _ in range(count):
        if rng.random() < skip_probability:
            continue
        jitter = rng.gauss(0.0, jitter_minutes_std * 60.0)
        ready_by = ready_by_hour * 3600.0 + jitter
        lead = rng.uniform(*lead_minutes_range) * 60.0
        request_time = max(0.0, ready_by - lead)
        requests.append(RequestSeed(request_time, ready_by, "commuter"))
    return requests


def generate_on_demand(
    rng: random.Random,
    duration_hours: float,
    base_rate_per_hour: float,
    peak_multiplier: float,
    peak_hours: tuple[float, float],
) -> list[RequestSeed]:
    """A non-homogeneous Poisson process by hour, thinned from a peak-rate envelope."""

    def rate(hour: float) -> float:
        if peak_hours[0] <= hour < peak_hours[1]:
            return base_rate_per_hour * peak_multiplier
        return base_rate_per_hour

    max_rate = base_rate_per_hour * max(peak_multiplier, 1.0)
    requests = []
    t = 0.0
    duration_seconds = duration_hours * 3600.0
    while t < duration_seconds:
        t += rng.expovariate(max_rate / 3600.0)
        if t >= duration_seconds:
            break
        hour = (t / 3600.0) % 24
        if rng.random() <= rate(hour) / max_rate:
            # On-demand requests want the car immediately
            requests.append(RequestSeed(t, t, "on_demand"))
    return requests


def generate_evening_wave(
    rng: random.Random,
    start_hour: float,
    count: int,
    spread_minutes: float,
) -> list[RequestSeed]:
    """An event letting out: a cluster of ready-by times around start_hour."""
    requests = []
    for _ in range(count):
        jitter = rng.gauss(0.0, spread_minutes * 60.0)
        ready_by = max(0.0, start_hour * 3600.0 + jitter)
        lead = rng.uniform(2.0, 15.0) * 60.0
        request_time = max(0.0, ready_by - lead)
        requests.append(RequestSeed(request_time, ready_by, "evening"))
    return requests


def generate_valet_absences(
    rng: random.Random, valet_ids: list[str], probability: float
) -> set[str]:
    """Random shift losses: each valet independently has a chance of being absent."""
    return {v for v in valet_ids if rng.random() < probability}
