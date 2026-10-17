import pytest
from policies.garage import Garage


def _small_garage() -> Garage:
    return Garage(num_lanes=3, max_depth=4)


def test_park_and_find_car():
    garage = _small_garage()
    garage.park("car-1", lane=1, depth=1)
    spot = garage.find_car("car-1")
    assert spot.lane == 1
    assert spot.depth == 1


def test_parking_an_occupied_spot_raises():
    garage = _small_garage()
    garage.park("car-1", lane=1, depth=1)
    with pytest.raises(ValueError):
        garage.park("car-2", lane=1, depth=1)


def test_no_blockers_at_depth_one():
    garage = _small_garage()
    garage.park("car-1", lane=1, depth=1)
    assert garage.blockers_of(1, 1) == []
    assert garage.relocation_count(1, 1) == 1


def test_blockers_are_every_shallower_occupied_depth():
    garage = _small_garage()
    garage.park("car-1", lane=1, depth=1)
    garage.park("car-2", lane=1, depth=2)
    garage.park("car-3", lane=1, depth=3)
    blockers = garage.blockers_of(1, 3)
    assert {(b.lane, b.depth) for b in blockers} == {(1, 1), (1, 2)}
    assert garage.relocation_count(1, 3) == 3


def test_gap_in_lane_is_not_a_blocker():
    garage = _small_garage()
    garage.park("car-1", lane=1, depth=1)
    # depth 2 left empty
    garage.park("car-3", lane=1, depth=3)
    blockers = garage.blockers_of(1, 3)
    assert {(b.lane, b.depth) for b in blockers} == {(1, 1)}


def test_free_spots_excludes_occupied():
    garage = _small_garage()
    garage.park("car-1", lane=1, depth=1)
    free = garage.free_spots()
    assert (1, 1) not in {(s.lane, s.depth) for s in free}
    assert len(free) == garage.capacity() - 1


def test_relocation_conservation_no_car_lost_or_duplicated():
    garage = _small_garage()
    for depth in range(1, 4):
        garage.park(f"car-{depth}", lane=1, depth=depth)

    destinations = garage.relocation_destinations(1, 3)
    assert len(destinations) == 2

    before_cars = {
        occupant
        for depths in garage.occupancy.values()
        for occupant in depths.values()
        if occupant is not None
    }

    blockers = garage.blockers_of(1, 3)
    for blocker, dest in zip(blockers, destinations, strict=True):
        car_id = garage.remove(blocker.lane, blocker.depth)
        garage.park(car_id, dest.lane, dest.depth)
    retrieved = garage.remove(1, 3)

    after_cars = {
        occupant
        for depths in garage.occupancy.values()
        for occupant in depths.values()
        if occupant is not None
    }
    after_cars.add(retrieved)

    assert before_cars == after_cars
    assert len(before_cars) == len(after_cars)


def test_full_lane_has_no_free_spots():
    garage = Garage(num_lanes=1, max_depth=2)
    garage.park("car-1", lane=1, depth=1)
    garage.park("car-2", lane=1, depth=2)
    assert garage.free_spots() == []


def test_full_garage_relocation_destinations_raises():
    garage = Garage(num_lanes=1, max_depth=2)
    garage.park("car-1", lane=1, depth=1)
    garage.park("car-2", lane=1, depth=2)
    with pytest.raises(ValueError):
        garage.relocation_destinations(1, 2)


def test_remove_empty_spot_raises():
    garage = _small_garage()
    with pytest.raises(ValueError):
        garage.remove(1, 1)


def test_travel_time_increases_with_depth():
    garage = _small_garage()
    shallow = garage.travel_time("lobby", lane=1, depth=1)
    deep = garage.travel_time("lobby", lane=1, depth=4)
    assert deep > shallow


def test_travel_time_increases_with_lane_distance_from_desk():
    garage = Garage(num_lanes=5, max_depth=1)
    near = garage.travel_time("desk", lane=1, depth=1)
    far = garage.travel_time("desk", lane=5, depth=1)
    assert far > near


def test_find_car_returns_none_when_absent():
    garage = _small_garage()
    assert garage.find_car("nope") is None
