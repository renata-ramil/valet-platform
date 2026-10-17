from policies.garage import Garage
from policies.interfaces import PendingTask, ValetState
from policies.optimization import (
    CPSATDispatcher,
    CPSATStaffer,
    EDFDispatcher,
    apply_moves,
    overnight_reoptimize,
)


def test_overnight_reoptimize_swaps_unfavorable_order():
    garage = Garage(num_lanes=1, max_depth=3)
    garage.park("late", 1, 1)
    garage.park("mid", 1, 2)
    garage.park("soon", 1, 3)
    departures = {"late": (10_000.0, 60.0), "mid": (5_000.0, 60.0), "soon": (100.0, 60.0)}

    before = garage.relocation_count(1, 3) - 1
    moves = overnight_reoptimize(garage, departures, max_moves=10)
    apply_moves(garage, moves)

    spot = garage.find_car("soon")
    after = garage.relocation_count(spot.lane, spot.depth) - 1
    assert after < before


def test_overnight_reoptimize_respects_move_budget():
    garage = Garage(num_lanes=1, max_depth=3)
    garage.park("late", 1, 1)
    garage.park("mid", 1, 2)
    garage.park("soon", 1, 3)
    departures = {"late": (10_000.0, 60.0), "mid": (5_000.0, 60.0), "soon": (100.0, 60.0)}

    moves = overnight_reoptimize(garage, departures, max_moves=0)
    assert moves == []


def test_overnight_reoptimize_never_duplicates_or_loses_cars():
    garage = Garage(num_lanes=2, max_depth=4)
    cars = {}
    for lane in (1, 2):
        for depth in range(1, 4):
            car_id = f"car-{lane}-{depth}"
            garage.park(car_id, lane, depth)
            cars[car_id] = (float((lane * 10 + depth) * 100), 60.0)

    before_cars = {c for depths in garage.occupancy.values() for c in depths.values() if c}
    moves = overnight_reoptimize(garage, cars, max_moves=20)
    apply_moves(garage, moves)
    after_cars = {c for depths in garage.occupancy.values() for c in depths.values() if c}

    assert before_cars == after_cars


def test_apply_moves_handles_a_direct_swap_without_collision():
    garage = Garage(num_lanes=1, max_depth=2)
    garage.park("a", 1, 1)
    garage.park("b", 1, 2)
    from policies.optimization import ReassignmentMove

    apply_moves(
        garage,
        [ReassignmentMove("a", 1, 1, 2), ReassignmentMove("b", 1, 2, 1)],
    )
    assert garage.find_car("a").depth == 2
    assert garage.find_car("b").depth == 1


def test_edf_dispatcher_prioritizes_nearest_deadline():
    dispatcher = EDFDispatcher()
    valets = [ValetState("v1", 0.0)]
    tasks = [
        PendingTask("t1", "retrieve", 1, 1, ready_at=0.0, deadline=500.0),
        PendingTask("t2", "retrieve", 1, 2, ready_at=0.0, deadline=100.0),
    ]
    assignments = dispatcher.dispatch(valets, tasks, now=0.0)
    assert assignments == [("v1", "t2")]


def test_cpsat_dispatcher_assigns_faster_valet_to_tighter_deadline():
    def travel(valet_id, task):
        return 60.0 if valet_id == "v1" else 300.0

    dispatcher = CPSATDispatcher(travel)
    valets = [ValetState("v1", 0.0), ValetState("v2", 0.0)]
    tasks = [
        PendingTask("t1", "retrieve", 1, 1, ready_at=0.0, deadline=90.0),
        PendingTask("t2", "retrieve", 1, 2, ready_at=0.0, deadline=1000.0),
    ]
    assignments = dict(dispatcher.dispatch(valets, tasks, now=0.0))
    assert assignments["v1"] == "t1"
    assert assignments["v2"] == "t2"


def test_cpsat_dispatcher_ignores_unavailable_valets():
    dispatcher = CPSATDispatcher(lambda v, t: 60.0)
    valets = [ValetState("v1", 1000.0)]  # not available until t=1000
    tasks = [PendingTask("t1", "retrieve", 1, 1, ready_at=0.0, deadline=100.0)]
    assert dispatcher.dispatch(valets, tasks, now=0.0) == []


def test_staffer_covers_demand_at_minimum_cost():
    staffer = CPSATStaffer(bucket_minutes=60, shift_hours=4.0)
    forecast = {b: (2.0 if 8 <= b < 12 else 0.0) for b in range(24)}
    result = staffer.staff_with_report(forecast, ["v1", "v2", "v3"])
    assert result.uncovered_buckets == []
    assert len(result.assignments) == 2  # only 2 of 3 valets needed
    assert result.total_shift_hours == 8.0


def test_staffer_reports_shortfall_instead_of_failing():
    staffer = CPSATStaffer(bucket_minutes=60, shift_hours=4.0)
    forecast = {b: (5.0 if 8 <= b < 12 else 0.0) for b in range(24)}
    result = staffer.staff_with_report(forecast, ["v1", "v2"])
    assert result.uncovered_buckets == [8, 9, 10, 11]
    assert len(result.assignments) == 2


def test_staffer_optimal_on_a_hand_checked_instance():
    # 4 buckets need 1 valet each; one 2-bucket shift template per valet (set by
    # shift_hours matching bucket_minutes below). The cheapest feasible cover is
    # exactly 2 shifts of 2 buckets each (4 valet-bucket-hours), not 4 separate
    # 1-bucket-covering shifts, since shifts cover a fixed length each.
    staffer = CPSATStaffer(bucket_minutes=60, shift_hours=2.0)
    forecast = {0: 1.0, 1: 1.0, 2: 1.0, 3: 1.0}
    result = staffer.staff_with_report(forecast, ["v1", "v2", "v3", "v4"])
    assert result.uncovered_buckets == []
    assert result.total_shift_hours == 4.0
    assert len(result.assignments) == 2


def test_staffer_with_no_valets_reports_everything_uncovered():
    staffer = CPSATStaffer(bucket_minutes=60, shift_hours=4.0)
    forecast = {b: 1.0 for b in range(4)}
    result = staffer.staff_with_report(forecast, [])
    assert result.assignments == {}
    assert result.uncovered_buckets == [0, 1, 2, 3]
