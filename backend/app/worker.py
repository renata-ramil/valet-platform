import time

from app.db import SessionLocal
from app.schedule_engine import materialize_all_schedules
from app.worker_billing import run_all as run_all_billing_jobs

POLL_SECONDS = 60
# Billing jobs are date-gated internally (the 20th, the 1st, day 3/7 after a
# failure) and fully idempotent, so running them every poll is safe; this
# just keeps the schedule worker as the single background process
BILLING_POLL_ITERATIONS = 10


def run_once() -> int:
    db = SessionLocal()
    try:
        created = materialize_all_schedules(db)
        return len(created)
    finally:
        db.close()


def run_billing_once() -> dict:
    db = SessionLocal()
    try:
        return run_all_billing_jobs(db)
    finally:
        db.close()


def run_forever() -> None:
    print("Schedule worker started, materializing every 60 seconds")
    print(f"Billing jobs run every {BILLING_POLL_ITERATIONS * POLL_SECONDS} seconds")
    iteration = 0
    while True:
        created = run_once()
        iteration += 1
        print(f"[worker] iteration {iteration}: materialized {created} requests")
        if iteration % BILLING_POLL_ITERATIONS == 0:
            run_billing_once()
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    run_forever()
