.PHONY: dev test e2e sim experiments report audit reconcile security eval-support demo

dev:
	@if command -v docker >/dev/null 2>&1; then \
		docker compose up -d postgres; \
	else \
		echo "docker not found, skipping Postgres. Install Docker Desktop to run the real database."; \
	fi
	@echo "Starting API on http://localhost:8000 and frontend on http://localhost:5173"
	@trap 'kill 0' EXIT; \
	( cd backend && . .venv/bin/activate && uvicorn app.main:app --reload --port 8000 ) & \
	( cd frontend && npm run dev ) & \
	wait

test:
	@echo "Running backend tests"
	cd backend && . .venv/bin/activate && python -m pytest -q
	@echo "Running frontend tests"
	cd frontend && npm run test

e2e:
	cd frontend && npm run e2e

sim:
	cd backend && . .venv/bin/activate && cd .. && python3 -m sim.run --scenario $(SCENARIO) --seeds 30

experiments:
	cd backend && . .venv/bin/activate && cd .. && python3 -m sim.experiments

report:
	cd backend && . .venv/bin/activate && cd .. && python3 scripts/build_results.py

audit:
	cd backend && . .venv/bin/activate && python -m app.audit verify

reconcile:
	cd backend && . .venv/bin/activate && python -m app.reconcile

security:
	@echo "Running bandit against backend/app"
	cd backend && . .venv/bin/activate && bandit -r app -q
	@echo "Running pip-audit against the backend virtualenv"
	cd backend && . .venv/bin/activate && PIPAPI_PYTHON_LOCATION=$$(which python) pip-audit
	@echo "Running npm audit against the frontend"
	cd frontend && npm audit
	@echo "See docs/security-report.md and docs/threat-model.md for triage and findings."

eval-support:
	cd backend && . .venv/bin/activate && python scripts/run_support_eval.py

demo:
	@if [ ! -f backend/.env ]; then \
		echo "backend/.env not found, copy backend/.env.example first: cp backend/.env.example backend/.env"; \
		exit 1; \
	fi
	@if [ ! -f frontend/.env ]; then \
		echo "frontend/.env not found, copy frontend/.env.example first: cp frontend/.env.example frontend/.env"; \
		exit 1; \
	fi
	@echo "Migrating the database"
	cd backend && . .venv/bin/activate && alembic upgrade head
	@echo "Seeding 30 days of demo data (residents, valets, shifts, tickets)"
	cd backend && . .venv/bin/activate && python scripts/seed_demo.py
	@echo "Demo login sheet: backend/scripts/demo_login_sheet.local.md"
	@echo "Starting API on http://localhost:8000 and frontend on http://localhost:5173"
	@trap 'kill 0' EXIT; \
	( cd backend && . .venv/bin/activate && uvicorn app.main:app --reload --port 8000 ) & \
	( cd frontend && npm run dev ) & \
	wait
