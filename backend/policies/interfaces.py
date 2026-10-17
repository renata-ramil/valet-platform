import math
import random
from dataclasses import dataclass
from typing import Protocol

from policies.garage import Garage, Spot


@dataclass
class ArrivingCar:
    car_id: str
    predicted_next_needed_at: float | None  # sim clock seconds, None if unknown
    predicted_std: float | None = None  # uncertainty on that estimate, seconds


@dataclass
class PendingTask:
    task_id: str
    task_type: str  # retrieve, deliver, park, restage
    lane: int | None
    depth: int | None
    ready_at: float
    deadline: float | None


@dataclass
class ValetState:
    valet_id: str
    available_at: float  # sim clock seconds when this valet is next free


class SpotAssigner(Protocol):
    def assign(self, garage: Garage, car: ArrivingCar, now: float) -> Spot: ...


class Dispatcher(Protocol):
    def dispatch(
        self, valets: list[ValetState], tasks: list[PendingTask], now: float
    ) -> list[tuple[str, str]]:
        """Return (valet_id, task_id) pairs to assign right now."""
        ...


class Staffer(Protocol):
    def staff(
        self, forecast: dict[int, float], valet_pool: list[str]
    ) -> dict[str, list[tuple[int, int]]]:
        """Given expected demand per 15-minute bucket index, return valet_id -> list of
        (start_bucket, end_bucket) shift ranges."""
        ...


class RandomSpotAssigner:
    """Baseline: park in a uniformly random free spot."""

    def __init__(self, rng: random.Random | None = None):
        self.rng = rng or random.Random()

    def assign(self, garage: Garage, car: ArrivingCar, now: float) -> Spot:
        free = garage.free_spots()
        if not free:
            raise ValueError("No free spots available")
        return self.rng.choice(free)


class NearestFreeSpotAssigner:
    """Baseline: park in the free spot with the shortest travel time from the desk."""

    def assign(self, garage: Garage, car: ArrivingCar, now: float) -> Spot:
        free = garage.free_spots()
        if not free:
            raise ValueError("No free spots available")
        return min(free, key=lambda s: garage.travel_time("desk", s.lane, s.depth))


def _normal_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def probability_a_before_b(mean_a: float, std_a: float, mean_b: float, std_b: float) -> float:
    """P(A < B) for A ~ Normal(mean_a, std_a), B ~ Normal(mean_b, std_b), independent."""
    diff_mean = mean_a - mean_b
    diff_std = math.sqrt(std_a**2 + std_b**2)
    if diff_std == 0:
        if diff_mean < 0:
            return 1.0
        if diff_mean > 0:
            return 0.0
        return 0.5
    return _normal_cdf(-diff_mean / diff_std)


DEFAULT_PREDICTED_STD = 600.0  # 10 minutes, used when a caller gives a point estimate only


class DepartureAwareAssigner:
    """Chooses the spot that minimizes the expected number of relocations over the
    horizon: a car needed sooner should sit shallower than cars needed later in the
    same lane. Scheduled requests carry a near-deterministic next-needed time; cars
    with no prediction (on-demand, or anyone the caller doesn't have a habit model
    for yet) fall back to a wide building-wide prior, reflecting "could be needed any
    time today."

    Shares a car_id -> (mean, std) registry across assign() calls so later lookahead
    can see earlier assignments' predicted departure times, including this
    assigner's own guesses for cars it has already placed.
    """

    def __init__(
        self,
        car_departures: dict[str, tuple[float, float]] | None = None,
        unknown_mean: float = 12 * 3600.0,
        unknown_std: float = 12 * 3600.0,
    ):
        self.car_departures = car_departures if car_departures is not None else {}
        self.unknown_mean = unknown_mean
        self.unknown_std = unknown_std

    def _distribution_for(
        self, car_id: str, predicted: float | None, predicted_std: float | None
    ) -> tuple[float, float]:
        if car_id in self.car_departures:
            return self.car_departures[car_id]
        if predicted is not None:
            return (predicted, predicted_std or DEFAULT_PREDICTED_STD)
        return (self.unknown_mean, self.unknown_std)

    def _expected_relocations(self, garage: Garage, spot: Spot, mean: float, std: float) -> float:
        total = 0.0
        for blocker in garage.blockers_of(spot.lane, spot.depth):
            occupant = garage.occupancy[blocker.lane][blocker.depth]
            b_mean, b_std = self._distribution_for(occupant, None, None)
            # This car departs while a shallower car (occupant) is still parked:
            # occupant must be moved aside
            total += probability_a_before_b(mean, std, b_mean, b_std)
        for depth in range(spot.depth + 1, garage.max_depth + 1):
            if not garage.is_occupied(spot.lane, depth):
                continue
            occupant = garage.occupancy[spot.lane][depth]
            d_mean, d_std = self._distribution_for(occupant, None, None)
            # A deeper car departs while this car is still parked: this car
            # becomes that car's blocker and must be moved aside
            total += probability_a_before_b(d_mean, d_std, mean, std)
        return total

    def assign(self, garage: Garage, car: ArrivingCar, now: float) -> Spot:
        free = garage.free_spots()
        if not free:
            raise ValueError("No free spots available")

        mean, std = self._distribution_for(
            car.car_id, car.predicted_next_needed_at, car.predicted_std
        )
        self.car_departures[car.car_id] = (mean, std)

        def cost(spot: Spot) -> tuple[float, float]:
            relocations = self._expected_relocations(garage, spot, mean, std)
            travel = garage.travel_time("desk", spot.lane, spot.depth)
            return (relocations, travel)

        return min(free, key=cost)


class FCFSDispatcher:
    """Baseline: the longest-waiting task goes to the earliest-available valet."""

    def dispatch(
        self, valets: list[ValetState], tasks: list[PendingTask], now: float
    ) -> list[tuple[str, str]]:
        available = sorted(
            (v for v in valets if v.available_at <= now), key=lambda v: v.available_at
        )
        pending = sorted(tasks, key=lambda t: t.ready_at)
        assignments = []
        for valet, task in zip(available, pending, strict=False):
            assignments.append((valet.valet_id, task.task_id))
        return assignments


class FlatStaffer:
    """Baseline: every valet works the same fixed shift regardless of forecast."""

    def __init__(self, bucket_count: int):
        self.bucket_count = bucket_count

    def staff(
        self, forecast: dict[int, float], valet_pool: list[str]
    ) -> dict[str, list[tuple[int, int]]]:
        return {valet_id: [(0, self.bucket_count)] for valet_id in valet_pool}
