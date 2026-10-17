# Known issues and limitations

What is built and verified, what is simplified, and what has not yet been
exercised outside a local development machine.

## Not yet verified against real infrastructure

- **Not deployed, not built end to end.** `docker-compose.prod.yml` and
  both production `Dockerfile`s are written but have never been built or
  run (no Docker daemon was available during development). Review before
  a real deploy; the backend image installs `ortools`, `pymc` and
  `lightgbm`, which have native build dependencies.
- **Postgres paths.** All migrations were generated and run against
  SQLite only, including the partial unique indexes and the append-only
  triggers on `audit_events` and `ledger_entries`. The Postgres
  LISTEN/NOTIFY event bus and the append-only trigger's Postgres branch
  have not been exercised against a real Postgres instance.
- **`StripeProvider` has never run against the live Stripe test API.** It
  is written against the documented `stripe` SDK shapes (SetupIntent with
  the Payment Element, off session PaymentIntents,
  `stripe.Webhook.construct_event` signature verification) and read for
  correctness only. `FakeProvider` is the fully exercised default
  (`PAYMENTS_PROVIDER=fake`) and every billing test runs against it. Next
  step: run with real test keys and exercise setup, an off session
  charge, a decline and the webhook round trip.
- **The support assistant's live model path** has not been exercised
  against a real API call (no API key was available).
  `reports/support_eval.md` reports the rule-based fallback's results and
  says so.
- **Calendar import's success path** (fetching a real external ICS feed)
  is covered by unit tests against hand-built ICS text and a live check of
  the SSRF rejection path, not by a live fetch of a real calendar.
- **Lighthouse** was run against the login screen only. The resident
  home, schedule, valet queue and manager board were checked manually and
  have no saved Lighthouse report.

## Backend limitations

- **Billing worker jobs are not started automatically.**
  `app/worker_billing.py`'s five jobs (`issue_invoices`, `charge_autopay`,
  `retry_failed`, `mark_past_due`, `send_notifications`) are tested
  against an injected clock and wired into `app/worker.py`'s
  `run_forever()` loop, but neither `make dev` nor docker compose starts
  that process; run it with `python -m app.worker`. Next step: add a
  `worker` service to both compose files.
- **`POST /valet/cars/{car_id}/arrived` needs the car to have at least one
  `Request` row** to attach the park task to. Every car gets one the first
  time it is requested and the demo data always has one; a car with none
  gets a clean 409.
- **CSV import takes a JSON body** (`{"csv_text": ..., "dry_run": ...}`)
  instead of a multipart file upload, so the authorization-matrix harness
  can drive it with plain JSON. The manager UI reads the file client side
  and posts its text.
- **`support_assistant.run_support_turn` catches `Exception` broadly**
  around the live-model call (bandit finding, see
  [security-report.md](security-report.md) finding 4b). It keeps the chat
  available by falling back to the rule-based responder, and it also
  means a real bug in the live path would fall back silently. Next step:
  narrow it to the SDK's transient-failure exception types and log
  everything else.
- **The in-memory rate limiter holds state per process.** A multi-worker
  deployment needs a shared store (Redis) for limits to apply globally.
  See [threat-model.md](threat-model.md).
- **TOTP enrollment** has backend support and full test coverage but no
  settings-page UI; staff enroll through a direct API call. The login-time
  code prompt has a real UI.
- **Schemathesis** found 422 and 429 OpenAPI documentation gaps; they are
  cosmetic and not fixed.

## Models and data

- The habit detector, demand forecast and all policy experiment numbers
  are evaluated on simulated history, labeled `origin=simulated`, until a
  pilot building provides real history.
- Every figure in `reports/billing_checks.md` comes from the seeded demo
  data (`backend/scripts/seed_demo.py`); the report labels itself
  simulated and names its run date.
- `CalibratedEtaProvider._features()` uses fixed population-average
  placeholders for four of its six features at the current call site;
  only `hour_of_day` is real per request.
- Pre-staging is implemented and measured but not enabled in the live
  app, since the experiments do not support it as a default
  ([policies_summary.md](../reports/policies_summary.md)).

## Screens that show less than the design

Each of these renders only data the API actually returns, with a comment
in the component and, where a user would notice, on-screen copy. Codes
name the design screens (M manager, R resident, V valet, N notifications).

- **M09 residents list, M10 resident detail:** `ResidentSummary` carries
  no billing fields, so the monthly total, balance and autopay columns,
  the past-due and no-autopay filters, and the detail page's invoices,
  credits and notes panels are left out.
- **M13 add car success, M17 end a car:** the dollar preview (first
  invoice, final proration) is a plain policy sentence, since there is no
  preview endpoint and the server computes every amount.
- **M15 bulk import:** a CSV-paste textarea replaces the drag-and-drop
  picker and column mapping; `fleet_service.import_cars_csv` reads fixed
  header names.
- **M18 car requests:** there is no endpoint to mark a `CarRequest`
  applied, so converting one resolves the originating ticket instead.
- **M19 plans:** `size_class` is a free string and `Plan` has no car
  count, so the form takes plain text and the catalog shows active or
  archived.
- **M20 billing overview:** `collection_curve` gives one real series
  (collected by day); the second "expected" curve is a flat reference
  line at the billed total.
- **M22 invoice detail:** `Payment` has no card brand or last four, so
  payments show method and provider. The invoice audit trail shows only
  the event types the endpoint returns.
- **M24, M25 approvals:** `ApprovalRequestOut` has no `invoice_id`, so an
  approval card cannot link to its invoice.
- **M26 month close:** a data-backed checklist (pending approvals, past
  due count, export) replaces the per-resident narrative, which needs
  payment failure data the API does not expose.
- **R29 payment verify:** there is no OTP confirmation endpoint; "Verify"
  retries `payInvoice` with a fresh idempotency key and "Send a new code"
  clears the field.
- **R30 invoice detail, R31 payment methods:** a derived status summary
  replaces the itemized payment list, and the "Default" method label is
  left out (`PaymentMethodResponse` has no field for it).
- **V06, V07 car search:** results show no unit badge (`CarSearchResult`
  has no unit field), and the park task preview card is left out since
  that data exists only after the task is created.
- **N01 message templates** (email and push copy) have no render surface
  in the app.
- **Week view skips and overrides are session-local.** There is no
  endpoint to list or reverse a `ScheduleException`, so a reload loses the
  "Skipped" mark even though the backend recorded the exception.
