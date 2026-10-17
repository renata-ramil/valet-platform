from dataclasses import dataclass

from ortools.sat.python import cp_model

from policies.garage import Garage
from policies.interfaces import PendingTask, ValetState, probability_a_before_b

COST_SCALE = 1000  # CP-SAT needs integer coefficients; probabilities are scaled


@dataclass
class ReassignmentMove:
    car_id: str
    lane: int
    from_depth: int
    to_depth: int


def _lane_cost(depths_by_car: dict[str, int], departures: dict[str, tuple[float, float]]) -> float:
    total = 0.0
    cars = list(depths_by_car)
    for a in cars:
        for b in cars:
            if a == b:
                continue
            if depths_by_car[a] > depths_by_car[b]:
                mean_a, std_a = departures[a]
                mean_b, std_b = departures[b]
                total += probability_a_before_b(mean_a, std_a, mean_b, std_b)
    return total


def _solve_lane(
    cars: list[str], depths: list[int], departures: dict[str, tuple[float, float]]
) -> dict[str, int] | None:
    model = cp_model.CpModel()
    x = {(car, d): model.NewBoolVar(f"x_{car}_{d}") for car in cars for d in depths}
    for car in cars:
        model.Add(sum(x[car, d] for d in depths) == 1)
    for d in depths:
        model.Add(sum(x[car, d] for car in cars) <= 1)

    depth_of = {car: sum(d * x[car, d] for d in depths) for car in cars}

    y = {}
    for a in cars:
        for b in cars:
            if a == b:
                continue
            y[a, b] = model.NewBoolVar(f"y_{a}_{b}")
            # y[a, b] == 1 iff depth(a) > depth(b)
            model.Add(depth_of[a] - depth_of[b] >= 1).OnlyEnforceIf(y[a, b])
            model.Add(depth_of[a] - depth_of[b] <= 0).OnlyEnforceIf(y[a, b].Not())

    terms = []
    for a in cars:
        for b in cars:
            if a == b:
                continue
            mean_a, std_a = departures[a]
            mean_b, std_b = departures[b]
            weight = round(probability_a_before_b(mean_a, std_a, mean_b, std_b) * COST_SCALE)
            if weight:
                terms.append(weight * y[a, b])
    model.Minimize(sum(terms) if terms else 0)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 2.0
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    return {car: d for car in cars for d in depths if solver.Value(x[car, d])}


def overnight_reoptimize(
    garage: Garage,
    departures: dict[str, tuple[float, float]],
    max_moves: int,
) -> list[ReassignmentMove]:
    """Re-examine each lane's car ordering and propose swaps that reduce expected
    relocations, capped at max_moves total moves across the whole garage. Only
    reorders cars within their current lane; never moves a car into a spot that's
    occupied, and never exceeds the move budget.
    """
    candidate_moves: list[tuple[float, list[ReassignmentMove]]] = []

    for lane in range(1, garage.num_lanes + 1):
        current = {
            d: garage.occupancy[lane][d]
            for d in range(1, garage.max_depth + 1)
            if garage.occupancy[lane].get(d)
        }
        if len(current) < 2:
            continue
        cars = list(current.values())
        if any(car not in departures for car in cars):
            continue
        depths = list(current.keys())
        current_depth_by_car = {car: d for d, car in current.items()}

        current_cost = _lane_cost(current_depth_by_car, departures)
        solved = _solve_lane(cars, depths, departures)
        if solved is None:
            continue
        new_cost = _lane_cost(solved, departures)
        improvement = current_cost - new_cost
        if improvement <= 1e-9:
            continue

        moves = [
            ReassignmentMove(car, lane, current_depth_by_car[car], solved[car])
            for car in cars
            if solved[car] != current_depth_by_car[car]
        ]
        if moves:
            candidate_moves.append((improvement, moves))

    candidate_moves.sort(key=lambda item: item[0], reverse=True)

    applied: list[ReassignmentMove] = []
    budget = max_moves
    for _improvement, moves in candidate_moves:
        if len(moves) > budget:
            continue
        applied.extend(moves)
        budget -= len(moves)
        if budget <= 0:
            break
    return applied


def apply_moves(garage: Garage, moves: list[ReassignmentMove]) -> None:
    # Two-phase: pull everyone out first, then park, so intermediate states never
    # collide even when two cars are swapping depths within the same lane
    pulled = []
    for move in moves:
        car_id = garage.remove(move.lane, move.from_depth)
        pulled.append((car_id, move.lane, move.to_depth))
    for car_id, lane, depth in pulled:
        garage.park(car_id, lane, depth)


class EDFDispatcher:
    """Earliest-deadline-first: the task with the nearest deadline goes to the
    earliest-available valet."""

    def dispatch(
        self, valets: list[ValetState], tasks: list[PendingTask], now: float
    ) -> list[tuple[str, str]]:
        available = sorted(
            (v for v in valets if v.available_at <= now), key=lambda v: v.available_at
        )
        pending = sorted(
            tasks, key=lambda t: t.deadline if t.deadline is not None else float("inf")
        )
        return [
            (valet.valet_id, task.task_id)
            for valet, task in zip(available, pending, strict=False)
        ]


class CPSATDispatcher:
    """Batch-assigns the currently pending tasks to currently available valets,
    minimizing total lateness, given each valet's travel time to each task."""

    def __init__(self, travel_time_fn):
        # travel_time_fn(valet_id, task) -> seconds
        self.travel_time_fn = travel_time_fn

    def dispatch(
        self, valets: list[ValetState], tasks: list[PendingTask], now: float
    ) -> list[tuple[str, str]]:
        available = [v for v in valets if v.available_at <= now]
        if not available or not tasks:
            return []

        model = cp_model.CpModel()
        x = {
            (v.valet_id, t.task_id): model.NewBoolVar(f"x_{v.valet_id}_{t.task_id}")
            for v in available
            for t in tasks
        }
        for t in tasks:
            model.Add(sum(x[v.valet_id, t.task_id] for v in available) <= 1)
        for v in available:
            model.Add(sum(x[v.valet_id, t.task_id] for t in tasks) <= 1)

        lateness_terms = []
        for v in available:
            for t in tasks:
                travel = self.travel_time_fn(v.valet_id, t)
                finish = now + travel
                deadline = t.deadline if t.deadline is not None else finish
                lateness = max(0, round(finish - deadline))
                lateness_terms.append(lateness * x[v.valet_id, t.task_id])

        # Prefer assigning more tasks, then minimize total lateness among assigned
        assigned_count = sum(x.values())
        model.Maximize(assigned_count * 10_000_000 - sum(lateness_terms))

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 2.0
        status = solver.Solve(model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return []

        return [
            (v.valet_id, t.task_id)
            for v in available
            for t in tasks
            if solver.Value(x[v.valet_id, t.task_id])
        ]


@dataclass
class ShiftTemplate:
    name: str
    start_bucket: int
    length_buckets: int


@dataclass
class StaffingResult:
    assignments: dict[str, list[tuple[int, int]]]
    uncovered_buckets: list[int]
    total_shift_hours: float


def build_shift_templates(
    bucket_count: int, shift_length_buckets: int, step_buckets: int
) -> list[ShiftTemplate]:
    templates = []
    start = 0
    while start + shift_length_buckets <= bucket_count:
        templates.append(ShiftTemplate(f"shift_{start}", start, shift_length_buckets))
        start += step_buckets
    return templates


class CPSATStaffer:
    """Covers a per-bucket demand vector with valet shifts chosen from a fixed set
    of templates (encoding max shift length and an implicit break), minimizing
    total staffed hours. Each valet works at most one shift (min rest between
    shifts is then automatic). Reports buckets that can't be covered instead of
    failing, so the result is always usable.
    """

    def __init__(self, bucket_minutes: int = 15, shift_hours: float = 8.0):
        self.bucket_minutes = bucket_minutes
        self.shift_length_buckets = int(shift_hours * 60 / bucket_minutes)

    def staff(
        self, forecast: dict[int, float], valet_pool: list[str]
    ) -> dict[str, list[tuple[int, int]]]:
        result = self.staff_with_report(forecast, valet_pool)
        return result.assignments

    def staff_with_report(
        self, forecast: dict[int, float], valet_pool: list[str]
    ) -> StaffingResult:
        bucket_count = (max(forecast.keys()) + 1) if forecast else 0
        required = {b: max(0, round(forecast.get(b, 0.0))) for b in range(bucket_count)}
        templates = build_shift_templates(bucket_count, self.shift_length_buckets, step_buckets=1)

        if not templates or not valet_pool:
            return StaffingResult({}, sorted(required.keys()), 0.0)

        model = cp_model.CpModel()
        # x[valet, template] = 1 if this valet works this shift
        x = {
            (valet, t.name): model.NewBoolVar(f"x_{valet}_{t.name}")
            for valet in valet_pool
            for t in templates
        }
        for valet in valet_pool:
            model.Add(sum(x[valet, t.name] for t in templates) <= 1)

        max_shortfall = max(required.values(), default=0)
        slack = {b: model.NewIntVar(0, max_shortfall, f"slack_{b}") for b in required}
        for b, need in required.items():
            covering = [
                x[valet, t.name]
                for valet in valet_pool
                for t in templates
                if t.start_bucket <= b < t.start_bucket + t.length_buckets
            ]
            model.Add(sum(covering) + slack[b] >= need)

        total_shift_buckets = sum(
            t.length_buckets * x[valet, t.name] for valet in valet_pool for t in templates
        )
        model.Minimize(sum(slack.values()) * 1_000_000 + total_shift_buckets)

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 5.0
        status = solver.Solve(model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return StaffingResult({}, sorted(required.keys()), 0.0)

        assignments: dict[str, list[tuple[int, int]]] = {}
        total_buckets = 0
        for valet in valet_pool:
            for t in templates:
                if solver.Value(x[valet, t.name]):
                    assignments[valet] = [(t.start_bucket, t.start_bucket + t.length_buckets)]
                    total_buckets += t.length_buckets

        uncovered = [b for b in required if solver.Value(slack[b]) > 0]
        total_hours = total_buckets * self.bucket_minutes / 60.0
        return StaffingResult(assignments, uncovered, total_hours)
