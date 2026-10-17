import random

from policies.garage import Garage
from policies.interfaces import (
    ArrivingCar,
    FCFSDispatcher,
    FlatStaffer,
    NearestFreeSpotAssigner,
    PendingTask,
    RandomSpotAssigner,
    ValetState,
)


def test_random_spot_assigner_returns_a_free_spot():
    garage = Garage(num_lanes=2, max_depth=2)
    assigner = RandomSpotAssigner(rng=random.Random(42))
    spot = assigner.assign(garage, ArrivingCar("car-1", None), now=0.0)
    assert not garage.is_occupied(spot.lane, spot.depth)


def test_nearest_free_spot_assigner_prefers_closest_lane():
    garage = Garage(num_lanes=5, max_depth=1)
    assigner = NearestFreeSpotAssigner()
    spot = assigner.assign(garage, ArrivingCar("car-1", None), now=0.0)
    assert spot.lane == 1


def test_nearest_free_spot_assigner_skips_occupied_near_spots():
    garage = Garage(num_lanes=3, max_depth=1)
    garage.park("car-0", lane=1, depth=1)
    assigner = NearestFreeSpotAssigner()
    spot = assigner.assign(garage, ArrivingCar("car-1", None), now=0.0)
    assert spot.lane == 2


def test_nearest_free_spot_assigner_never_picks_a_full_lane():
    garage = Garage(num_lanes=2, max_depth=1)
    garage.park("occupant", 1, 1)
    assigner = NearestFreeSpotAssigner()
    spot = assigner.assign(garage, ArrivingCar("car-1", None), now=0.0)
    assert spot.lane == 2
    assert not garage.is_occupied(spot.lane, spot.depth)


def test_fcfs_dispatcher_pairs_oldest_task_with_earliest_free_valet():
    dispatcher = FCFSDispatcher()
    valets = [ValetState("v1", available_at=5.0), ValetState("v2", available_at=0.0)]
    tasks = [
        PendingTask("t1", "retrieve", 1, 1, ready_at=10.0, deadline=None),
        PendingTask("t2", "retrieve", 1, 2, ready_at=0.0, deadline=None),
    ]
    assignments = dispatcher.dispatch(valets, tasks, now=10.0)
    assert ("v2", "t2") in assignments
    assert ("v1", "t1") in assignments


def test_fcfs_dispatcher_only_uses_available_valets():
    dispatcher = FCFSDispatcher()
    valets = [ValetState("v1", available_at=100.0)]
    tasks = [PendingTask("t1", "retrieve", 1, 1, ready_at=0.0, deadline=None)]
    assignments = dispatcher.dispatch(valets, tasks, now=10.0)
    assert assignments == []


def test_flat_staffer_assigns_every_valet_full_day():
    staffer = FlatStaffer(bucket_count=96)
    shifts = staffer.staff(forecast={}, valet_pool=["v1", "v2"])
    assert shifts == {"v1": [(0, 96)], "v2": [(0, 96)]}
