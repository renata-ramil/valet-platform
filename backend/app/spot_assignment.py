from policies.garage import Garage
from policies.interfaces import ArrivingCar, DepartureAwareAssigner, NearestFreeSpotAssigner
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Car, ParkingSpot, Schedule
from app.settings import settings

_departure_aware_registry: dict[str, tuple[float, float]] = {}


def get_assigner(policy_name: str | None = None):
    """The same classes sim/experiments.py measured: the live app picks one by
    name instead of hardcoding a choice, so it can run with the simpler baseline
    (see reports/policies_summary.md for why departure_aware is the default)."""
    name = policy_name or settings.spot_assignment_policy
    if name == "nearest_free":
        return NearestFreeSpotAssigner()
    if name == "departure_aware":
        return DepartureAwareAssigner(car_departures=_departure_aware_registry)
    raise ValueError(f"Unknown spot_assignment_policy {name!r}")


def _load_garage(db: Session, building_id: str) -> tuple[Garage, dict[tuple[int, int], str]]:
    spots = list(db.scalars(select(ParkingSpot).where(ParkingSpot.building_id == building_id)))
    num_lanes = max((s.lane for s in spots), default=0)
    max_depth = max((s.depth for s in spots), default=0)
    garage = Garage(num_lanes=num_lanes, max_depth=max_depth)
    spot_id_by_coord: dict[tuple[int, int], str] = {}
    for spot in spots:
        spot_id_by_coord[(spot.lane, spot.depth)] = spot.id

    occupied_cars = list(
        db.scalars(
            select(Car).where(
                Car.building_id == building_id, Car.parking_spot_id.is_not(None)
            )
        )
    )
    spot_by_id = {s.id: s for s in spots}
    for car in occupied_cars:
        spot = spot_by_id.get(car.parking_spot_id)
        if spot is not None and not garage.is_occupied(spot.lane, spot.depth):
            garage.park(car.id, spot.lane, spot.depth)
    return garage, spot_id_by_coord


def assign_spot_for_car(db: Session, car: Car) -> ParkingSpot | None:
    """Assigns a free parking spot to a newly registered car using the configured
    policy, and returns the ParkingSpot row (or None if the garage is full or has
    no layout yet)."""
    garage, spot_id_by_coord = _load_garage(db, car.building_id)
    if not spot_id_by_coord or not garage.free_spots():
        return None

    schedule = db.scalar(select(Schedule).where(Schedule.car_id == car.id))
    predicted = None
    if schedule is not None:
        # A rough next-needed estimate: today's scheduled time, in seconds from
        # midnight server time. Good enough signal for the assigner; the live app
        # doesn't need simulator-grade precision here.
        t = schedule.ready_by_local_time
        predicted = float(t.hour * 3600 + t.minute * 60 + t.second)

    assigner = get_assigner()
    spot = assigner.assign(garage, ArrivingCar(car.id, predicted), now=0.0)

    spot_id = spot_id_by_coord.get((spot.lane, spot.depth))
    if spot_id is None:
        return None
    parking_spot = db.get(ParkingSpot, spot_id)
    car.parking_spot_id = spot_id
    parking_spot.is_occupied = True
    db.add(car)
    db.add(parking_spot)
    return parking_spot
