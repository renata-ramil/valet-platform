from app.fleet_service import create_car as fleet_create_car
from app.models import ParkingSpot, Role
from app.spot_assignment import assign_spot_for_car, get_assigner

from tests.conftest import make_user


def test_get_assigner_resolves_known_policy_names():
    from policies.interfaces import DepartureAwareAssigner, NearestFreeSpotAssigner

    assert isinstance(get_assigner("nearest_free"), NearestFreeSpotAssigner)
    assert isinstance(get_assigner("departure_aware"), DepartureAwareAssigner)


def test_assign_spot_returns_none_without_a_garage_layout(db_session, building):
    resident = make_user(db_session, building.id, email="resident@example.com")
    from app.models import Car

    car = Car(
        building_id=building.id,
        owner_id=resident.id,
        make="Honda",
        model="Civic",
        color="blue",
        license_plate="ABC123",
    )
    db_session.add(car)
    db_session.flush()
    result = assign_spot_for_car(db_session, car)
    assert result is None
    assert car.parking_spot_id is None


def test_creating_a_car_assigns_a_parking_spot(db_session, building):
    for lane in range(1, 3):
        for depth in range(1, 3):
            db_session.add(ParkingSpot(building_id=building.id, lane=lane, depth=depth))
    db_session.commit()

    manager = make_user(db_session, building.id, Role.manager, "manager@example.com")
    resident = make_user(db_session, building.id, email="resident@example.com")
    car = fleet_create_car(
        db_session, building, manager, resident.id, "Honda", "Civic", "blue", "ABC123", None, None
    )
    assert car.parking_spot_id is not None
    spot = db_session.get(ParkingSpot, car.parking_spot_id)
    assert spot.is_occupied is True


def test_two_cars_get_different_spots(db_session, building):
    for lane in range(1, 3):
        for depth in range(1, 3):
            db_session.add(ParkingSpot(building_id=building.id, lane=lane, depth=depth))
    db_session.commit()

    manager = make_user(db_session, building.id, Role.manager, "manager@example.com")
    resident = make_user(db_session, building.id, email="resident@example.com")
    car1 = fleet_create_car(
        db_session, building, manager, resident.id, "Honda", "Civic", "blue", "ABC123", None, None
    )
    car2 = fleet_create_car(
        db_session, building, manager, resident.id, "Toyota", "Camry", "red", "XYZ789", None, None
    )
    assert car1.parking_spot_id != car2.parking_spot_id
