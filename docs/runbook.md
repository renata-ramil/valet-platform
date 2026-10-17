# Runbook

One page. For the full architecture and results, see README.md and
docs/KNOWN-ISSUES.md.

## Deploying (requires explicit confirmation of the target before running)

1. Point two DNS A records at the host: `DOMAIN` (frontend) and
   `API_DOMAIN` (backend). Caddy needs both resolvable before it can issue
   certificates.
2. `cp .env.prod.example .env.prod` and fill in every value. Generate
   `SECRET_KEY` with `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
   Never commit `.env.prod`.
3. `docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build`
4. Caddy (`deploy/Caddyfile`) obtains and renews TLS certificates
   automatically; no manual certbot step. First issuance can take up to a
   minute.
5. Confirm `https://<API_DOMAIN>/health` returns `{"status": "ok", "env":
   "production"}` and `https://<DOMAIN>` loads the login screen.
6. Seed demo data if this is a demo environment, or leave the database
   empty for a real building: `docker compose -f docker-compose.prod.yml
   exec backend python scripts/seed_demo.py` (reads `DATABASE_URL` from
   the container's own environment).

**Not verified yet**: no Docker daemon was available during
development (see docs/KNOWN-ISSUES.md), so the Dockerfiles and
`docker-compose.prod.yml` above have not been built or run end to end.
Review them before a real deploy; the backend Dockerfile in particular
installs `ortools`, `pymc`, and `lightgbm`, which have native
dependencies and a first build will take several minutes.

## Environment variables

See `backend/.env.example` and `.env.prod.example` for the full list.
The ones that change behavior materially:

- `APP_ENV=production` enables the stricter `SECRET_KEY` check
  (`app/settings.py`) and HSTS (`app/security_headers.py`).
- `DATABASE_URL` must point at Postgres in production; SQLite is for
  local development and the test suite only.
- `ANTHROPIC_API_KEY` unset means the support assistant runs the
  rule-based fallback (`app/support_assistant.py`), not the live model.
  Tested and safe either way; see docs/KNOWN-ISSUES.md.
- `TWILIO_AUTH_TOKEN` unset means `POST /sms/inbound` uses a well-known
  dev-only token (`app/settings.py`); set a real one before exposing that
  endpoint publicly, since the token is what verifies the webhook came
  from Twilio.

## Common operations

- **Back up the database**: `docker compose -f docker-compose.prod.yml
  exec postgres pg_dump -U valet valet > backup.sql`
- **Restore**: `docker compose -f docker-compose.prod.yml exec -T postgres
  psql -U valet valet < backup.sql`
- **Run a migration after a code update**: migrations run automatically
  on backend container start (`alembic upgrade head` in
  `backend/Dockerfile`'s `CMD`); restarting the backend service applies
  them.
- **Check the audit chain**: `docker compose -f docker-compose.prod.yml
  exec backend python -m app.audit verify`. A broken chain prints the
  exact event and position; see `reports/tamper_demo.txt` for what that
  output looks like and `docs/threat-model.md` for what it means.
- **Rotate `SECRET_KEY`**: invalidates every active session (sessions are
  server-side rows, not signed by the secret, so this is actually a no-op
  for existing sessions today; `SECRET_KEY` is reserved for future
  signing needs and is enforced non-placeholder in production as a
  defense-in-depth measure). Update `.env.prod` and restart the backend.

## Incident response

- **Suspected tampering with the event log**: run the audit chain check
  above immediately. A broken chain names the exact request and event;
  cross-reference `RequestEvent.actor_id` for who touched it last through
  the application (a direct database edit bypassing the app will not
  have a plausible actor). Preserve the database before taking further
  action.
- **Elevated error rate**: check `docker compose -f docker-compose.prod.yml
  logs backend`; unhandled exceptions are logged server-side with a full
  traceback (`app/main.py`'s exception handler) even though the client
  only ever sees `{"detail": "Internal server error"}`.
- **Suspected credential stuffing**: `LoginFailure` rows
  (`backend/app/models.py`) record every failed attempt with email and IP;
  query recent rows directly against Postgres to see the pattern. Account
  and IP lockout already apply automatically (`app/security.py`).
