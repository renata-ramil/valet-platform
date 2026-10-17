import json
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import date

from app.db import Base, SessionLocal, engine
from app.fleet_service import create_car
from app.models import Building, InviteCode, ParkingSpot, Plan, PlanPrice, Role, User
from app.security import hash_password
from sqlalchemy import select

RESIDENT_COUNT = 40
VALET_COUNT = 6
MANAGER_COUNT = 2
SUPPORT_COUNT = 1
LANES = 14
MAX_DEPTH = 8

CAR_MAKES = ["Honda", "Toyota", "Tesla", "Ford", "BMW", "Subaru", "Kia", "Mazda"]
CAR_MODELS = ["Civic", "Camry", "Model 3", "F-150", "3 Series", "Outback", "Soul", "CX-5"]
COLORS = ["black", "white", "silver", "blue", "red", "gray"]


def generate_password() -> str:
    return secrets.token_urlsafe(9)


def main() -> None:
    print("Creating tables")
    Base.metadata.create_all(engine)

    db = SessionLocal()
    passwords: dict[str, str] = {}

    try:
        print("Seeding Harbor Tower")
        building = Building(name="Harbor Tower", timezone="America/Los_Angeles")
        db.add(building)
        db.commit()
        db.refresh(building)

        print(f"Seeding garage layout: {LANES} lanes up to depth {MAX_DEPTH}")
        spot_count = 0
        for lane in range(1, LANES + 1):
            for depth in range(1, MAX_DEPTH + 1):
                db.add(ParkingSpot(building_id=building.id, lane=lane, depth=depth))
                spot_count += 1
            if lane % 5 == 0:
                print(f"  seeded {lane}/{LANES} lanes")
        db.commit()
        print(f"Seeded {spot_count} parking spots")

        def make_user(email: str, role: Role, full_name: str) -> User:
            password = generate_password()
            passwords[email] = password
            user = User(
                building_id=building.id,
                email=email,
                password_hash=hash_password(password),
                role=role,
                full_name=full_name,
            )
            db.add(user)
            return user

        print(f"Seeding {RESIDENT_COUNT} residents")
        residents = []
        for i in range(1, RESIDENT_COUNT + 1):
            resident = make_user(
                f"resident{i}@harbortower.example.com", Role.resident, f"Resident {i}"
            )
            residents.append(resident)
            if i % 10 == 0:
                print(f"  seeded {i}/{RESIDENT_COUNT} residents")
        db.commit()
        for r in residents:
            db.refresh(r)

        print(f"Seeding {VALET_COUNT} valets, {MANAGER_COUNT} managers, {SUPPORT_COUNT} support")
        for i in range(1, VALET_COUNT + 1):
            make_user(f"valet{i}@harbortower.example.com", Role.valet, f"Valet {i}")
        managers = [
            make_user(f"manager{i}@harbortower.example.com", Role.manager, f"Manager {i}")
            for i in range(1, MANAGER_COUNT + 1)
        ]
        for i in range(1, SUPPORT_COUNT + 1):
            make_user(f"support{i}@harbortower.example.com", Role.support, f"Support {i}")
        db.commit()
        for m in managers:
            db.refresh(m)

        print("Seeding a default plan")
        plan = Plan(building_id=building.id, name="Standard", size_class="sedan")
        db.add(plan)
        db.flush()
        db.add(
            PlanPrice(
                plan_id=plan.id, effective_month=date.today().replace(day=1), monthly_cents=14900
            )
        )
        db.commit()

        print(
            "Seeding cars for residents, through the manager fleet service "
            "(app.fleet_service.create_car)"
        )
        spots = list(db.scalars(select(ParkingSpot).where(ParkingSpot.building_id == building.id)))
        manager = managers[0]
        car_count = 0
        for i, resident in enumerate(residents, start=1):
            num_cars = 1 if i % 2 == 0 else 2
            for _ in range(num_cars):
                create_car(
                    db,
                    building,
                    manager,
                    resident.id,
                    CAR_MAKES[car_count % len(CAR_MAKES)],
                    CAR_MODELS[car_count % len(CAR_MODELS)],
                    COLORS[car_count % len(COLORS)],
                    f"{secrets.token_hex(3).upper()}",
                    plan.id,
                    date.today(),
                )
                car_count += 1
            if i % 10 == 0:
                print(f"  seeded cars for {i}/{RESIDENT_COUNT} residents")
        print(f"Seeded {car_count} cars, up to {len(spots)} parked in spots")

        print("Creating a spare resident invite code")
        invite = InviteCode(
            building_id=building.id,
            code="HARBOR-WELCOME",
            role=Role.resident,
            max_uses=100,
        )
        db.add(invite)
        db.commit()

        passwords_path = Path(__file__).resolve().parent / "seed_passwords.local.json"
        passwords_path.write_text(json.dumps(passwords, indent=2))
        print(f"Wrote {len(passwords)} generated passwords to {passwords_path}")

        print(
            f"Done: 1 building, {RESIDENT_COUNT} residents, {VALET_COUNT} valets, "
            f"{MANAGER_COUNT} managers, {SUPPORT_COUNT} support agent, {car_count} cars, "
            f"{spot_count} parking spots, invite code HARBOR-WELCOME"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
