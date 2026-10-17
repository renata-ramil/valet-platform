from policies.garage import Garage
from policies.interfaces import (
    ArrivingCar,
    DepartureAwareAssigner,
    probability_a_before_b,
)


def test_sooner_car_placed_shallower_than_later_car():
    garage = Garage(num_lanes=1, max_depth=4)
    assigner = DepartureAwareAssigner()

    soon_spot = assigner.assign(garage, ArrivingCar("soon", 100.0, 60.0), now=0.0)
    garage.park("soon", soon_spot.lane, soon_spot.depth)

    later_spot = assigner.assign(garage, ArrivingCar("later", 10_000.0, 60.0), now=0.0)

    assert later_spot.depth > soon_spot.depth


def test_never_returns_an_occupied_spot():
    garage = Garage(num_lanes=2, max_depth=2)
    assigner = DepartureAwareAssigner()
    for i in range(3):
        spot = assigner.assign(garage, ArrivingCar(f"car-{i}", float(i * 100), 60.0), now=0.0)
        assert not garage.is_occupied(spot.lane, spot.depth)
        garage.park(f"car-{i}", spot.lane, spot.depth)


def test_never_picks_a_full_lane_when_another_lane_has_room():
    garage = Garage(num_lanes=2, max_depth=1)
    garage.park("occupant", 1, 1)  # lane 1 is full
    assigner = DepartureAwareAssigner()
    spot = assigner.assign(garage, ArrivingCar("car-1", 100.0, 60.0), now=0.0)
    assert spot.lane == 2
    assert not garage.is_occupied(spot.lane, spot.depth)


def test_raises_when_garage_is_full():
    garage = Garage(num_lanes=1, max_depth=1)
    garage.park("car-0", 1, 1)
    assigner = DepartureAwareAssigner()
    try:
        assigner.assign(garage, ArrivingCar("car-1", 100.0, 60.0), now=0.0)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_unknown_car_uses_building_wide_prior():
    garage = Garage(num_lanes=1, max_depth=2)
    assigner = DepartureAwareAssigner(unknown_mean=500.0, unknown_std=50.0)
    spot = assigner.assign(garage, ArrivingCar("mystery", None, None), now=0.0)
    assert assigner.car_departures["mystery"] == (500.0, 50.0)
    garage.park("mystery", spot.lane, spot.depth)


def test_given_a_free_choice_of_lane_it_avoids_a_known_conflict():
    # car-1 (needed late) already sits alone in lane 1. car-2 (needed soon) arrives
    # with lane 2 completely free: parking behind car-1 would mean car-2 has to
    # shove car-1 aside to leave first, so the assigner should prefer the empty lane.
    garage = Garage(num_lanes=2, max_depth=2)
    assigner = DepartureAwareAssigner()
    spot1 = assigner.assign(garage, ArrivingCar("car-1", 10_000.0, 60.0), now=0.0)
    garage.park("car-1", spot1.lane, spot1.depth)

    spot2 = assigner.assign(garage, ArrivingCar("car-2", 100.0, 60.0), now=0.0)
    assert spot2.lane != spot1.lane


def test_probability_a_before_b_is_half_when_identical():
    assert probability_a_before_b(100.0, 10.0, 100.0, 10.0) == 0.5


def test_probability_a_before_b_favors_earlier_mean():
    p = probability_a_before_b(0.0, 10.0, 1000.0, 10.0)
    assert p > 0.99
