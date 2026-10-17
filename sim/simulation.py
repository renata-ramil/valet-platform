import random
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import simpy
from policies.garage import Garage
from policies.interfaces import ArrivingCar, NearestFreeSpotAssigner, SpotAssigner

from sim.generators import (
    RequestSeed,
    generate_commuters,
    generate_evening_wave,
    generate_on_demand,
    generate_valet_absences,
)

RETRIEVAL_SECONDS = 30.0
RELOCATION_SECONDS = 45.0
RETRIEVAL_SPEED_CV = 0.2  # coefficient of variation for per-task valet speed


@dataclass
class RequestRecord:
    request_id: str
    car_id: str
    source: str
    request_time: float
    ready_by: float
    hour_of_day: float
    queue_length_at_request: int
    free_valets_at_request: int
    lane_depth_at_assignment: int = 0
    scheduled_load_next_hour: int = 0
    start_by: float | None = None
    retrieval_started_at: float | None = None
    delivered_at: float | None = None
    blockers_at_assignment: int = 0
    relocations: int = 0
    on_time: bool | None = None
    wait_seconds: float | None = None
    service_duration_seconds: float | None = None


@dataclass
class SimResult:
    requests: list[RequestRecord] = field(default_factory=list)
    valet_busy_seconds: dict[str, float] = field(default_factory=dict)
    duration_seconds: float = 0.0
    absent_valets: set[str] = field(default_factory=set)
    background_count: int = 0
    capacity: int = 0
    restages_completed: int = 0


def _load_requests(rng: random.Random, params: dict) -> list[RequestSeed]:
    requests: list[RequestSeed] = []
    commuters = params.get("commuters", {})
    if commuters.get("count", 0):
        requests += generate_commuters(
            rng,
            count=commuters["count"],
            ready_by_hour=commuters["ready_by_hour"],
            jitter_minutes_std=commuters["ready_by_jitter_minutes_std"],
            skip_probability=commuters["skip_probability"],
        )
    on_demand = params.get("on_demand", {})
    if on_demand.get("base_rate_per_hour", 0):
        requests += generate_on_demand(
            rng,
            duration_hours=params["duration_hours"],
            base_rate_per_hour=on_demand["base_rate_per_hour"],
            peak_multiplier=on_demand.get("peak_multiplier", 1.0),
            peak_hours=tuple(on_demand.get("peak_hours", [7, 10])),
        )
    evening = params.get("evening_event", {})
    if evening.get("enabled") and evening.get("count", 0):
        requests += generate_evening_wave(
            rng,
            start_hour=evening["start_hour"],
            count=evening["count"],
            spread_minutes=evening.get("spread_minutes", 15.0),
        )
    requests.sort(key=lambda r: r.request_time)
    return requests


def run_scenario(
    params: dict,
    seed: int,
    spot_assigner: SpotAssigner | None = None,
    pre_staging: bool = False,
    dispatch_mode: str = "edf",
    restage_window_hours: float = 2.0,
) -> SimResult:
    rng = random.Random(seed)
    spot_assigner = spot_assigner or NearestFreeSpotAssigner()

    building = params["building"]
    garage = Garage(num_lanes=building["num_lanes"], max_depth=building["max_depth"])
    capacity = garage.capacity()

    requests = _load_requests(rng, params)

    # Every car in the scenario is already parked before the day begins (overnight
    # or drop-off happened earlier): this is where a departure-aware SpotAssigner
    # gets to use each car's known ready_by. Background cars (other residents who
    # make no request today) fill the remaining capacity.
    occupancy_fraction = building.get("background_occupancy_fraction", 0.5)
    target_background = int(capacity * occupancy_fraction)
    background_count = max(0, min(target_background, capacity - len(requests)))
    if background_count < target_background:
        print(
            f"  [sim] note: garage too small for {len(requests)} requests at "
            f"{occupancy_fraction:.0%} background occupancy; using {background_count} "
            f"background cars instead of {target_background}"
        )

    for i in range(background_count):
        free = garage.free_spots()
        rng.shuffle(free)
        spot = min(free, key=lambda s: garage.travel_time("desk", s.lane, s.depth))
        garage.park(f"background-{i}", spot.lane, spot.depth)

    for i, seed_request in enumerate(requests):
        car_id = f"car-{i}"
        # On-demand requests are, by definition, not known ahead of time: only
        # commuter and evening-event cars carry a real predicted next-needed time
        predicted = seed_request.ready_by if seed_request.source != "on_demand" else None
        spot = spot_assigner.assign(garage, ArrivingCar(car_id, predicted), now=0.0)
        garage.park(car_id, spot.lane, spot.depth)

    valet_ids = [f"valet-{i}" for i in range(building["num_valets"])]
    absence_probability = params.get("valet_absence", {}).get("probability", 0.0)
    absent = generate_valet_absences(rng, valet_ids, absence_probability)
    active_valets = [v for v in valet_ids if v not in absent]

    env = simpy.Environment()
    valet_resource = simpy.PriorityResource(env, capacity=max(len(active_valets), 1))
    # One valet works a given lane at a time: a second valet can't relocate or
    # retrieve a car in a lane while another is mid-relocation there
    lane_locks = {
        lane: simpy.Resource(env, capacity=1) for lane in range(1, building["num_lanes"] + 1)
    }
    # Relocations normally stay within the lane already locked above. The rare case
    # where a lane has no free depth of its own and must borrow a spot in another
    # lane is serialized globally instead of trying to lock an unbounded set of
    # lanes up front
    global_relocation_lock = simpy.Resource(env, capacity=1)

    result = SimResult(
        absent_valets=absent,
        duration_seconds=params["duration_hours"] * 3600.0,
        background_count=background_count,
        capacity=capacity,
    )
    for v in active_valets:
        result.valet_busy_seconds[v] = 0.0

    pending_counter = {"n": 0}
    free_valets = {"n": len(active_valets)}

    def service_time(lane: int, depth: int, relocations: int) -> float:
        speed_factor = max(0.3, rng.lognormvariate(0.0, RETRIEVAL_SPEED_CV))
        travel = garage.travel_time("desk", lane, depth)
        drive_back = garage.travel.shortest_path_time(f"lane_{lane}_head", "lobby")
        base = travel + drive_back + RETRIEVAL_SECONDS + relocations * RELOCATION_SECONDS
        return base * speed_factor

    def relocate_blockers(lane: int, depth: int):
        """Move this spot's blockers aside. Called with the lane already locked.
        Prefers free depths in the same lane (no extra locking needed); falls back
        to the global relocation lock only when the lane itself has no room.
        """
        blockers = garage.blockers_of(lane, depth)
        if not blockers:
            return 0

        same_lane_free = [
            d
            for d in range(1, garage.max_depth + 1)
            if not garage.is_occupied(lane, d) and d != depth
        ]
        if len(same_lane_free) >= len(blockers):
            for blocker, dest_depth in zip(blockers, same_lane_free, strict=False):
                moved = garage.remove(blocker.lane, blocker.depth)
                garage.park(moved, lane, dest_depth)
            return len(blockers)

        with global_relocation_lock.request() as req:
            yield req
            blockers = garage.blockers_of(lane, depth)
            destinations = garage.relocation_destinations(lane, depth)
            for blocker, dest in zip(blockers, destinations, strict=True):
                moved = garage.remove(blocker.lane, blocker.depth)
                garage.park(moved, dest.lane, dest.depth)
        return len(blockers)

    def handle_request(seed_request: RequestSeed, index: int, car_id: str):
        yield env.timeout(max(0.0, seed_request.request_time - env.now))

        record = RequestRecord(
            request_id=f"req-{index}",
            car_id=car_id,
            source=seed_request.source,
            request_time=env.now,
            ready_by=seed_request.ready_by,
            hour_of_day=(env.now / 3600.0) % 24,
            queue_length_at_request=pending_counter["n"],
            free_valets_at_request=free_valets["n"],
            scheduled_load_next_hour=sum(
                1
                for r in requests
                if r.source in ("commuter", "evening")
                and env.now <= r.ready_by < env.now + 3600.0
            ),
        )

        spot = garage.find_car(car_id)
        if spot is None:
            raise RuntimeError(f"{record.request_id} car={car_id} is not in the garage")
        record.lane_depth_at_assignment = spot.depth

        expected_blockers = len(garage.blockers_of(spot.lane, spot.depth))
        drive_back = garage.travel.shortest_path_time(f"lane_{spot.lane}_head", "lobby")
        lead_time = (
            garage.travel_time("desk", spot.lane, spot.depth)
            + drive_back
            + RETRIEVAL_SECONDS
            + expected_blockers * RELOCATION_SECONDS
        )
        record.start_by = max(env.now, seed_request.ready_by - lead_time)
        wait_for_start = max(0.0, record.start_by - env.now)
        if wait_for_start:
            yield env.timeout(wait_for_start)

        record.blockers_at_assignment = expected_blockers
        pending_counter["n"] += 1

        # EDF serves the earliest deadline first; FCFS serves whoever asked first,
        # regardless of how soon they need the car
        priority = record.ready_by if dispatch_mode == "edf" else seed_request.request_time
        with valet_resource.request(priority=priority) as req:
            yield req
            free_valets["n"] = max(0, free_valets["n"] - 1)
            pending_counter["n"] = max(0, pending_counter["n"] - 1)
            record.retrieval_started_at = env.now

            # The car may have been relocated as someone else's blocker since it
            # was parked, so look up where it actually is before retrieving it
            current = garage.find_car(car_id)
            if current is None:
                raise RuntimeError(f"{record.request_id} car={car_id} is not in the garage")
            lane, depth = current.lane, current.depth

            # Hold this lane for the whole operation so no other valet relocates
            # or retrieves a car here while we're working the lane
            with lane_locks[lane].request() as lane_req:
                yield lane_req
                current = garage.find_car(car_id)
                lane, depth = current.lane, current.depth

                relocations = yield from relocate_blockers(lane, depth)
                record.relocations = relocations

                duration = service_time(lane, depth, relocations)
                yield env.timeout(duration)

                garage.remove(lane, depth)

            record.delivered_at = env.now
            record.wait_seconds = record.delivered_at - record.ready_by
            record.on_time = record.delivered_at <= record.ready_by
            record.service_duration_seconds = record.delivered_at - record.retrieval_started_at
            free_valets["n"] += 1

        result.requests.append(record)

    restage_in_progress: set[str] = set()

    def handle_restage(seed_request: RequestSeed, car_id: str, restage_time: float):
        yield env.timeout(max(0.0, restage_time - env.now))

        spot = garage.find_car(car_id)
        if spot is None or spot.depth == 1:
            return  # already gone, or already at the lane head
        if not garage.blockers_of(spot.lane, spot.depth):
            return  # nothing ahead of it to avoid; restaging would waste valet time

        restage_in_progress.add(car_id)
        try:
            # Low priority: never preempts an actual retrieval that's waiting
            with valet_resource.request(priority=seed_request.ready_by + 1e9) as req:
                yield req
                source_lane = spot.lane
                # Candidate destination lane heads are not yet locked, so pick one,
                # then acquire both lane locks in a fixed order (lowest lane number
                # first) to avoid deadlocking against another restage doing the same
                candidates = [
                    s for s in garage.free_spots() if s.depth == 1 and s.lane != source_lane
                ]
                if not candidates:
                    return  # no staging spot available this run; skip
                candidates.sort(key=lambda s: garage.travel_time("desk", s.lane, s.depth))
                dest_lane = candidates[0].lane
                first_lane, second_lane = sorted((source_lane, dest_lane))

                with lane_locks[first_lane].request() as first_req:
                    yield first_req
                    with lane_locks[second_lane].request() as second_req:
                        yield second_req

                        spot = garage.find_car(car_id)
                        if spot is None or spot.depth == 1:
                            return
                        if garage.is_occupied(dest_lane, 1):
                            return  # someone else took it while we waited; skip

                        duration = garage.travel_time("desk", spot.lane, spot.depth)
                        yield env.timeout(duration)

                        moved = garage.remove(spot.lane, spot.depth)
                        garage.park(moved, dest_lane, 1)
                        result.restages_completed += 1
        finally:
            restage_in_progress.discard(car_id)

    scheduled_requests = [
        (i, r) for i, r in enumerate(requests) if r.source in ("commuter", "evening")
    ]
    # One shared quiet window before the earliest wave, not a window relative to
    # each car's own ready_by: restaging for an 8 AM wave should happen well
    # before 8 AM for everyone, not bunch up right against each car's deadline
    if pre_staging and scheduled_requests:
        wave_start = min(r.ready_by for _, r in scheduled_requests)
        window_seconds = restage_window_hours * 3600.0
        window_start = max(0.0, wave_start - window_seconds)

    for i, seed_request in enumerate(requests):
        car_id = f"car-{i}"
        env.process(handle_request(seed_request, i, car_id))
        if pre_staging and seed_request.source in ("commuter", "evening"):
            restage_time = rng.uniform(window_start, wave_start)
            env.process(handle_restage(seed_request, car_id, restage_time))

    env.run(until=result.duration_seconds)
    return result
