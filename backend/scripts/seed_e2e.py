import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import Base, SessionLocal, engine
from app.models import Building, InviteCode, Role


def main() -> None:
    print("Creating tables for the e2e run")
    Base.metadata.create_all(engine)

    db = SessionLocal()
    try:
        building = Building(name="Harbor Tower", timezone="America/Los_Angeles")
        db.add(building)
        db.commit()
        db.refresh(building)

        resident_invite = InviteCode(
            building_id=building.id, code="E2E-RESIDENT", role=Role.resident, max_uses=1000
        )
        valet_invite = InviteCode(
            building_id=building.id, code="E2E-VALET", role=Role.valet, max_uses=1000
        )
        manager_invite = InviteCode(
            building_id=building.id, code="E2E-MANAGER", role=Role.manager, max_uses=1000
        )
        db.add(resident_invite)
        db.add(valet_invite)
        db.add(manager_invite)
        db.commit()
        print(
            f"Seeded building {building.id} with invite codes "
            "E2E-RESIDENT, E2E-VALET and E2E-MANAGER"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
