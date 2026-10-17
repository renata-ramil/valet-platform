import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal
from app.models import Building, Role, User
from app.security import create_session
from sqlalchemy import select

BASE_URL = os.environ.get("FAKE_VALET_BASE_URL", "http://localhost:8000")
POLL_SECONDS = 1.0
MIN_STEP_SECONDS = 2.0
MAX_STEP_SECONDS = 5.0

FORWARD_PATH = ["assigned", "retrieving", "en_route", "delivered"]

# fake_valet drives the real API over HTTP (rather than writing to the database
# directly) so state changes flow through the same event bus the resident app's
# SSE connection subscribes to, exactly as a real valet's phone would


def _find_or_create_valet(db) -> tuple[str, str]:
    valet = db.scalar(select(User).where(User.role == Role.valet))
    if valet is not None:
        return valet.id, valet.building_id
    building = db.scalar(select(Building))
    if building is None:
        raise RuntimeError("No building found. Run scripts/seed.py first.")
    from app.security import hash_password

    valet = User(
        building_id=building.id,
        email="fake-valet@harbortower.example.com",
        password_hash=hash_password("not-used"),
        role=Role.valet,
        full_name="Fake Valet",
    )
    db.add(valet)
    db.commit()
    db.refresh(valet)
    return valet.id, valet.building_id


def _request(method: str, path: str, session_id: str, csrf: str | None, body=None):
    headers = {"Content-Type": "application/json", "Cookie": f"session_id={session_id}"}
    if csrf:
        headers["X-CSRF-Token"] = csrf
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{BASE_URL}{path}", data=data, headers=headers, method=method)
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read())


def run_once(session_id: str, csrf: str) -> int:
    requests_list = _request("GET", "/requests", session_id, csrf)
    open_requests = [
        r
        for r in requests_list
        if r["state"] in ("queued", "assigned", "retrieving", "en_route")
    ]
    advanced = 0
    for item in open_requests:
        current = item["state"]
        target = FORWARD_PATH[0] if current not in FORWARD_PATH else FORWARD_PATH[
            FORWARD_PATH.index(current) + 1
        ]
        try:
            updated = _request(
                "POST",
                f"/requests/{item['id']}/transition",
                session_id,
                csrf,
                {"target_state": target},
            )
        except urllib.error.HTTPError as exc:
            print(f"  request {item['id'][:8]}: failed to advance ({exc.code})")
            continue
        print(f"  request {item['id'][:8]}: {current} -> {updated['state']}")
        advanced += 1
        time.sleep(random.uniform(MIN_STEP_SECONDS, MAX_STEP_SECONDS))
    return advanced


def main() -> None:
    print(f"fake_valet started, driving {BASE_URL} as a valet")
    db = SessionLocal()
    try:
        valet_id, building_id = _find_or_create_valet(db)
        session = create_session(db, valet_id, building_id)
    finally:
        db.close()

    iteration = 0
    try:
        while True:
            advanced = run_once(session.id, session.csrf_token)
            iteration += 1
            print(f"[fake_valet] iteration {iteration}: advanced {advanced} requests")
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        print("fake_valet stopped")


if __name__ == "__main__":
    main()
