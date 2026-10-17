# Security report

This covers threat modeling, the controls built or
confirmed, and the output of every scanner actually run against this
codebase. Every finding below came from a real run; none are invented for
the sake of having something to report.

## What was tested

- **bandit** (static analysis) against `backend/app`.
- **pip-audit** against the backend's installed dependencies (the actual
  virtualenv, not the system Python; the tool defaults to the latter and
  was pointed at the right one with `PIPAPI_PYTHON_LOCATION`).
- **npm audit** against the frontend's dependencies.
- **Schemathesis** fuzzing the live OpenAPI schema of a running instance
  (347 generated cases across all 45 operations, all checks enabled).
- **The authorization matrix** (`backend/tests/test_authorization_matrix.py`,
  documented in `docs/authorization-matrix.md`): every endpoint in the live
  OpenAPI schema, called for real as a resident, a valet, a manager,
  support staff, a resident of a second building, and an unauthenticated
  caller.
- **The audit tamper demonstration** (`backend/tests/test_audit_tamper.py`,
  output saved to `reports/tamper_demo.txt`): a raw SQL `UPDATE` and a raw
  SQL `DELETE` against `request_events`, bypassing the append-only trigger,
  both caught by `verify_all`.
- The full backend test suite (162 tests at the time of this review, up from 147),
  including 9 new TOTP tests, 5 new rate limit/header/body-size/idle-session
  tests, 4 new audit tamper tests, and the 2 authorization matrix tests.

## Controls implemented or confirmed

- **TOTP two-factor authentication** for valet, manager and support roles
  (`app/routers/totp.py`, `app/security.py`). Recovery codes are generated
  once at enrollment, shown in plaintext exactly that one time, and stored
  hashed with the same argon2 hasher used for passwords. Login for an
  account with a confirmed TOTP credential returns a short-lived (5 minute)
  challenge id instead of a session; the real session is only issued after
  `POST /auth/totp/verify` with a correct code or an unused recovery code.
- **Session rotation on privilege change**: confirming or disabling TOTP
  issues a brand new session id and CSRF token and deletes the old one, so
  a token captured before the change is immediately worthless.
- **Idle and absolute session timeouts**: sessions expire 12 hours after
  login (unchanged) and now also after 30 minutes of inactivity
  (`SESSION_IDLE_TIMEOUT`, enforced in `get_valid_session`). Logout deletes
  the server-side session row, not just the cookie.
- **Rate limits** on every write endpoint via a global per-IP middleware
  (120 requests/minute on non-GET methods), with stricter named limits on
  login (10/min/IP), registration (10/min/IP), invite code creation
  (10/min/user), TOTP verification (10/min/IP), and handoff code creation
  and verification (5/min/IP each).
- **Security headers** on every response: a CSP with no `unsafe-inline`
  (`default-src 'self'`, `frame-ancestors 'none'`), HSTS in production,
  `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, a
  `Referrer-Policy`, and a restrictive `Permissions-Policy`.
- **Request validation and uniform errors**: a 64 KB request body cap
  (`app/security_headers.py`), and exception handlers that return
  `{"detail": "..."}` for every error class, including unhandled
  exceptions, which are logged server side (with the real traceback) but
  never echoed to the client.
- **Startup secret check**: `Settings.validate_for_runtime()` now also
  rejects a production boot whose `SECRET_KEY` is a known placeholder
  (`changeme`, `secret`, `password`, etc.) or under 16 characters, not just
  a missing one.
- **Authorization matrix**: `docs/authorization-matrix.md`, generated and
  verified by `backend/tests/test_authorization_matrix.py` against every
  endpoint the live OpenAPI schema reports. A new endpoint with no entry
  fails `make test`.
- **Audit chain tamper detection**: `RequestEvent` gained a per-request
  `sequence` column. `verify_request_chain` now reports exactly which
  failure mode occurred (a deleted event leaves a sequence gap; an edited
  event leaves a hash mismatch; a reordered or substituted event leaves a
  `prev_hash` mismatch), not just that something is wrong.

## Findings

### 1. Uniform 422 error body breaks the OpenAPI-documented validation schema (accepted)

**Severity: informational. Tool: Schemathesis (3 occurrences: `POST
/auth/login`, `POST /auth/register`, `POST /auth/totp/verify`).**

FastAPI's default validation error body is
`{"detail": [{"loc": [...], "msg": "...", "type": "..."}]}`, which names
the exact field and rule that failed. The app's
`validation_exception_handler` replaces it with `{"detail": "Invalid
request"}` on every endpoint, which is a deliberate hardening tradeoff
(not naming internal field names, types or validation rules to an
unauthenticated caller probing `/auth/*`) at the cost of no longer matching
the schema FastAPI auto-generates for `HTTPValidationError`.

**Disposition: accepted.** The alternative (matching the schema) means
leaking exact field names and pydantic type names on every malformed
request, which is more useful to an attacker mapping the API than to a
legitimate client, since legitimate clients are this project's own
frontend and already send well-formed requests. A future pass could
publish a corrected `responses={422: ...}` schema per route so the
documentation matches the intentionally-simplified body, which is tracked
below under residual risks rather than fixed now, since it is a
documentation-accuracy issue, not a vulnerability.

### 2. `OPTIONS` requests return 405 instead of a Fastapi-default `Allow` header (accepted)

**Severity: informational. Tool: Schemathesis (6 occurrences, various
paths).**

A plain `OPTIONS` request (no `Origin` or `Access-Control-Request-Method`
header, so not a real CORS preflight) falls through to normal routing,
which has no `OPTIONS` handler registered, and returns a generic 405. This
is FastAPI's and Starlette's standard behavior; the CORS middleware only
answers `OPTIONS` for genuine preflight requests, which is the only case
browsers actually send one for.

**Disposition: accepted, not a vulnerability.** No information is
disclosed by the 405 beyond what `GET`/`POST`/etc. already reveal about
which paths exist, and real preflight requests (the only kind a browser
sends) are handled correctly by `CORSMiddleware` (verified manually: the
frontend's cross-origin requests from `localhost:5173` work in `make e2e`).

### 3. Rate limiting surfaces as an undocumented 429 in the OpenAPI schema (accepted)

**Severity: informational. Tool: Schemathesis (63 occurrences across most
write endpoints, once its 20-examples-per-endpoint fuzzing run exceeded
the global rate limit).**

FastAPI does not auto-document a `429` response for routes that can return
one via a dependency, so Schemathesis correctly flags it as
"undocumented." This is rate limiting doing exactly what it is designed to
do: Schemathesis itself is a burst of rapid automated requests from one
IP, which is precisely the traffic pattern the limiter exists to slow
down.

**Disposition: accepted.** Documenting `429` on every route via
`responses={429: ...}` would be straightforward but purely cosmetic; it is
tracked under residual risks rather than done now since it changes no
runtime behavior.

### 4. Bandit: possible hardcoded password string (false positive)

**Severity: low, confidence medium. Tool: bandit (B106).**

`backend/app/routers/auth.py:75` sets `csrf_token=""` on the response to
`POST /auth/register` (registration does not log the user in, so there is
no session yet and therefore no real CSRF token to return). Bandit's B106
check pattern-matches any keyword argument literally named `*token*` or
`*password*` assigned a string literal.

**Disposition: false positive.** No secret or credential is involved; the
empty string is a placeholder for a field that genuinely has no value at
this point in the flow.

### 4b. Bandit: try/except/pass around the live model call (accepted)

**Severity: low, confidence high. Tool: bandit (B110).**

`backend/app/support_assistant.py:197` (`run_support_turn`) catches any
exception from `_run_live_model` and falls through to the rule-based
responder without logging. This is a deliberate availability choice: a
resident's chat should not fail outright because of a transient Anthropic
API problem.

**Disposition: accepted, with a gap worth closing later.** Silently
swallowing every exception type (not just network/timeout errors) means a
real bug in the live-model code path (for example a malformed tool
schema) would also silently fall back to the rule-based responder instead
of surfacing anywhere. A future pass should narrow the `except` to the
specific transient-failure exception types the Anthropic SDK raises and
log the rest, rather than catching `Exception` broadly. Tracked in
docs/KNOWN-ISSUES.md rather than fixed now, since narrowing
it correctly needs knowing the SDK's real exception hierarchy under
load, not just its happy-path types.

### 5. pip-audit and npm audit: no findings

**Tool: pip-audit (backend), npm audit (frontend).**

Both ran clean: zero known vulnerabilities in the backend's installed
dependency set, and zero in the frontend's (`info: 0, low: 0, moderate: 0,
high: 0, critical: 0`). An empty findings list from either tool is worth
double-checking rather than trusting blindly, so both were re-run pointed explicitly at the correct environment
(`PIPAPI_PYTHON_LOCATION` for pip-audit, since it defaults to the system
Python and silently audits the wrong interpreter otherwise) to confirm the
clean result was not an artifact of auditing nothing.

## Residual risks

- See `docs/threat-model.md`'s "Residual risks" section: invite code brute
  forcing is slowed, not stopped; the in-memory rate limiter does not share
  state across multiple worker processes; invite code issuance is not
  individually audit-logged; TOTP is available but not mandatory for staff
  roles.
- The 422/429 documentation gaps above (findings 1 and 3) mean a consumer
  generating a client from this project's OpenAPI schema would not see
  accurate response shapes for those status codes. Worth fixing before
  publishing the schema to a third party; not worth fixing to protect this
  project's own frontend, which already handles both correctly by status
  code rather than by parsing `detail`'s shape.
- Schemathesis was run unauthenticated this round (no `--auth` or session
  fixture wired in), so its fuzzing coverage is limited to routes reachable
  without a session plus the shape of every route's rejection of
  unauthenticated traffic. The authorization matrix test is the
  authenticated-path coverage; a follow-up could feed
  Schemathesis a real session cookie to fuzz authenticated bodies too.
