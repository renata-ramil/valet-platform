# Threat model

## Assets

- Resident accounts: email, password hash, session cookies, CSRF tokens.
- Staff accounts (valet, manager, support): the same, plus TOTP secrets and
  recovery codes once enrolled.
- Car locations: which lane and depth a resident's car is parked at, and the
  live state of their request (where their car is, right now).
- Key custody: the chain of valet-only actions (key taken, car retrieved,
  delivered at the lobby, car arrived, parked, key returned) that accounts
  for where a car and its key are at every point in a visit.
- Schedules: a resident's daily routine (when they leave, which car), which
  is itself sensitive (it says where someone will be and when).
- The audit log: who did what to a request and when, used for disputes and
  incident review. Its value depends on it being tamper evident.
- Invite codes: the only way into a building's tenant; a leaked code lets
  someone register as a resident, valet, manager or support user for that
  building.

## Trust boundaries

- Browser to API: the only boundary a resident or staff member crosses
  directly. Everything past it is inside the building's tenant once a
  session is established.
- API to database: SQL only ever reaches the database through SQLAlchemy's
  parameterized queries; no endpoint builds a query from string
  interpolation.
- Building to building: every query in every router goes through
  `scoped_query`, which filters by `building_id`. A session's `building_id`
  is fixed at login and never taken from client input.
- Database to database admin: the append-only trigger on `request_events`
  is a boundary inside the database itself, and it only holds against an
  ordinary connection; a privileged admin (Postgres superuser, or anyone
  with file access to the SQLite file) can disable or bypass it. The hash
  chain, not the trigger, is the real control against that attacker; see
  `reports/tamper_demo.txt` for a worked example.
- Operator to deployment: `SECRET_KEY` and `DATABASE_URL` come only from the
  environment; `Settings.validate_for_runtime()` refuses to boot in
  production with no secret, a placeholder secret, or a secret under 16
  characters.

## STRIDE per component

| Component | Spoofing | Tampering | Repudiation | Info disclosure | DoS | Elevation of privilege |
|---|---|---|---|---|---|---|
| Session cookie | Stolen cookie reused from another device | N/A (opaque token) | Session rotates on login and on TOTP enrollment, invalidating old tokens | `httponly`, `secure` in production, `samesite=lax` | Idle (30 min) and absolute (12 h) timeouts bound a stolen session's life | A hijacked resident session cannot become staff; role is not client-controlled |
| CSRF token | N/A | A forged cross-site request lacking the token is rejected on every write | Logged via `RequestEvent.actor_id` | Token only reaches the legitimate client via the login/me response body | N/A | N/A |
| Login | Credential stuffing, password guessing | N/A | `LoginFailure` rows record every bad attempt | Generic "Invalid email or password" (no "user not found" vs "wrong password" distinction) | Per account and per IP lockout after 5/20 failures in 15 minutes; login itself is also rate limited (10/min/IP) | N/A |
| TOTP / recovery codes | A stolen password alone no longer logs a staff account in | Recovery codes are hashed at rest like passwords; each is single use | MFA challenges are short lived (5 min) and single use | The enrollment response is the only time the secret and recovery codes appear in plaintext | Verify endpoint is rate limited (10/min/IP) | Enrolling in TOTP rotates the session, so a token issued before enrollment cannot outlive it |
| `request_events` (audit log) | Actor id is set server side from the authenticated session, never from client input | Trigger blocks UPDATE/DELETE at the database level for an ordinary connection | The hash chain over `(type, payload, prev_hash)` plus a per-request sequence number detects any edit or deletion even if the trigger is bypassed | Payloads avoid storing anything beyond state transitions; no card numbers or full addresses | N/A | N/A |
| Invite codes | A guessed code lets someone join as any role the code grants | `uses_count` is incremented server side only, under the same transaction as account creation | Not individually logged today (open issue) | Codes are random (`secrets.token_urlsafe(8)`), not sequential | Invite code creation (manager only) is rate limited | A `role` on the invite code is fixed at creation; registering cannot request a different role |
| Valet custody events (`audit_events`, `subject_type="task"`) | Actor id is set server side from the authenticated session, never from client input | Appended through the same hash-chained, append-only `audit_events` table as fleet and money events | Every custody action carries the valet id, car id, spot and timestamp, chained per task | Payloads carry only ids, a plate and a spot; no resident contact details | N/A | Only a valet or manager role reaches `/valet/car-search` and `/valet/cars/{id}/arrived`; a resident gets 403 |
| Cross-tenant data (`scoped_query`) | N/A | N/A | N/A | A session's `building_id` is fixed at login; no endpoint accepts a building id from the client, so one tenant cannot read another's data by supplying a different id | N/A | A resident of building B cannot act on building A's resources: scoped queries return 404, and role gates that run before any query (manager/valet/support only routes) return 403 regardless of building. See `docs/authorization-matrix.md` |

## Abuse cases

1. **A valet reads another building's data.** Every query goes through
   `scoped_query(Model, user.building_id)`, where `user.building_id` comes
   from the session, not the request. Covered by the "Other building" column
   of `docs/authorization-matrix.md`, which exercises this live for every
   endpoint and expects 403 or 404, never a cross-tenant 200.
2. **A valet re-parks the same car twice.** `complete-park` checks the park
   task is still `pending` or `in_progress` before assigning a spot; a
   second call against an already-completed task is rejected with 409
   (tested in `test_car_arrived.py`). The resident confirms nothing in this
   flow; there is no code to replay.
3. **An attacker enumerates invite codes.** Codes are 8 bytes of
   `secrets.token_urlsafe` (over 10^14 possibilities), not sequential, and
   invite code creation is rate limited so a leaked building cannot be
   mass-enrolled quickly even by a manager account that got compromised.
   Guessing a valid code by brute force against `/auth/register` is slowed
   by the register rate limit (10/min/IP); this is a mitigation, not a full
   stop, and is called out below as a residual risk.
4. **Session theft.** Cookies are `httponly` (no JS access) and `secure` in
   production (never sent over plain HTTP). Idle and absolute timeouts
   bound how long a stolen cookie is useful. Logout deletes the
   server-side session row immediately, not just the cookie.
5. **Event log tampering by a database admin.** This is the one actor the
   append-only trigger cannot stop, by definition (they can disable the
   trigger or edit the file directly). The hash chain is the real control:
   `reports/tamper_demo.txt` shows a raw SQL UPDATE on a stored event's
   payload, bypassing the trigger, caught by `make audit` with the exact
   broken link. Deleting a row entirely is caught the same way through the
   per-request `sequence` column (a gap is unambiguous).

## Residual risks (not fully mitigated, documented rather than hidden)

- Invite code brute forcing against `/auth/register` is slowed by rate
  limiting but not fully stopped; a sustained distributed attack from many
  IPs could still guess a code eventually given enough attempts. A
  production deployment would want a CAPTCHA or a much shorter code
  lifetime on top of this.
- The in-memory rate limiter (`app/ratelimit.py`) is per-process. A
  multi-worker production deployment (more than one uvicorn worker, or
  multiple instances behind a load balancer) would need a shared store
  (Redis) for the limits to hold across all of them; today each worker
  enforces its own limit independently.
- Invite code issuance itself is not individually logged to the audit
  chain (`request_events` only covers request lifecycle events). A manager
  creating many invite codes is rate limited but not separately audited.
- TOTP is available for valet, manager and support roles but not enforced
  as mandatory; an account can operate with password-only auth until an
  operator or the user themselves enrolls. Making it mandatory is a product
  decision (it adds friction to onboarding) left to the building operator.
