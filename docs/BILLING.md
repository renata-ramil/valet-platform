# Billing

Fleet ownership and billing for the valet platform. Managers own the fleet,
residents pay a monthly fee per car through the app, and every money
movement is correct, idempotent and tamper evident. All payment code runs
offline against a fake provider by default, and against Stripe in test mode
when configured. No real money moves in this project.

## Decisions

1. **Fleet.** Only managers create, edit plates for and end cars. A car
   belongs to one resident, one plan and one building. Residents can read
   their cars and change the nickname. Everything else about a car is a
   manager action and lands in the audit chain.
2. **Car lifecycle.** pending (start date in the future), active, ended. A
   plate is unique among non-ended cars in a building (partial unique
   index). Ending a car sets ended_on, ends its schedules on that date, and
   creates a proration credit.
3. **Plans.** Building level catalog with name, size class and monthly
   price in integer cents. A price change takes effect on the first day of
   a future billing month and is stored as a dated price row. Archiving a
   plan keeps existing cars on it.
4. **Billing period.** Calendar month in the building's time zone. One
   invoice per resident per period with one line per car. Invoices are
   issued on the 20th at 09:00 local for the next month, due on the 1st.
   Autopay charges on the 1st at 06:00 local. Retries run 3 and 7 days
   after a failure. The invoice is past due from the 2nd when unpaid.
5. **Proration.** Cents for a partial month equal round half to even of
   monthly_cents times days_active over days_in_month, where days_active
   counts the start day and the last day. A car added after the next
   month's invoice was issued adds its lines to that invoice when it is
   still open and unpaid, otherwise to a new adjustment invoice due
   immediately. Ending a car credits unused days to the resident's credit
   balance, which applies automatically to the next invoice. Credits never
   exceed the invoice total. A final credit with no next invoice becomes a
   refund proposal for a manager.
6. **Money.** Integer cents, USD, one currency per building. Totals derive
   from lines. The server computes every amount and clients never send one.
7. **Ledger.** Append only ledger_entries with account (receivable, cash,
   revenue, credits, refunds), debit_cents, credit_cents, invoice_id,
   payment_id, memo and actor. Each transaction balances to zero. Entries
   join the audit hash chain used for request events, through a parallel
   per-subject chain described below. Balances and invoice paid totals
   derive from the ledger and the stored totals are checked against it by
   `make reconcile`.
8. **Payments.** A PaymentProvider interface with FakeProvider (default,
   deterministic, can simulate decline, requires_action and delayed bank
   settlement) and StripeProvider (test keys). The provider is chosen by
   PAYMENTS_PROVIDER. Card and bank details never touch our servers or
   database. Stored per method: provider customer id, provider method id,
   kind, brand, last four, expiry. The resident saves a method through a
   setup flow (Stripe SetupIntent with the Payment Element), and autopay
   charges use off session PaymentIntents.
9. **Autopay.** On by default after the first successful payment, with one
   switch. A resident cannot remove the only method while autopay is on.
10. **Webhooks.** POST /webhooks/stripe verifies the signature, stores each
    provider event id once (replays are ignored) and handles setup
    success, payment success, payment failure and refund events. The API
    response to the client and the webhook may arrive in any order, and
    both paths converge on the same idempotent state transition.
11. **Idempotency.** Every outbound charge carries the key
    invoice_id:attempt_no. Every money moving client endpoint requires an
    Idempotency-Key header and stores the response for 24 hours. A double
    click produces one charge.
12. **Dunning.** Notifications through the existing adapters: invoice
    ready (day 20), reminder 3 days before due when autopay is off,
    receipt on payment, failure notice with a link on each failed attempt,
    past due notice on day 5 and a final notice on day 10. Nothing after
    day 10 except the manager's list. At most one notification per
    resident per day.
13. **No lockouts.** Payment status never blocks a request for a car. Past
    due state is visible to the resident and the manager and changes no
    dispatch behavior.
14. **Manager money actions.** Record offline payment (cash, check,
    transfer, reference, date), issue credit (reason required), refund
    (amount, reason, original method) and void (draft or open invoices
    only). A refund or credit at or above REFUND_APPROVAL_THRESHOLD_CENTS
    (default 20000) creates an ApprovalRequest that a different manager
    must approve. The requester cannot approve their own request. Staff
    money actions require a TOTP step-up within the last 10 minutes,
    through a new `POST /auth/totp/stepup` endpoint that stamps the
    session with `totp_verified_at`.
15. **Roles.** Manager: full fleet and billing. Support: read only billing
    and fleet, can resend receipts. Valet: none. Resident: only their own
    invoices, methods and cars.
16. **Car requests.** A resident submits a structured request (add, remove
    or change; plate, make, model, color, note) that creates a ticket of
    type car_request. The manager inbox converts it with one call that
    prefills the add-car payload.
17. **Left out on purpose.** See Limitations below.

## Audit chain for fleet and money events

The existing `request_events` hash chain (`app/audit.py`) is keyed to a
`Request` row and stays untouched. Fleet and money actions are not always
tied to a request, so a parallel table, `audit_events`, carries the same
hash construction (sha256 over canonical JSON of subject, type, payload and
prev_hash, chained per subject) keyed by `(subject_type, subject_id)`
instead of `request_id`. `app.audit.append_audit_event` and
`verify_audit_chain` mirror `append_event` and `verify_request_chain`
exactly. `python -m app.audit verify` (and so `make audit`) now verifies
both chains and fails if either is broken.

## Car lifecycle

```
            start date in the future
  (none) ----------------------------> pending
                                           |
                                           | start date reached
                                           v
                                        active -----------> ended
                                           ^   end car         |
                                           |                   |
                                           +-------------------+
                                       (a car is never reactivated;
                                        a new car row is created instead)
```

A car is created `pending` when `started_on` is in the future (relative to
the building's local today), `active` when `started_on` has arrived, and
`ended` once a manager ends it. `ended_on` is set exactly once. Schedules
tied to an ended car get `active_until = ended_on` so they stop
materializing future requests.

## Invoice lifecycle

```
  draft --> open --> processing --> paid
              |          |            
              |          +----------> past_due --> paid
              |                           |
              +-----------> void <--------+ (void only from draft or open)
```

- `draft`: being assembled by `issue_invoices`, not yet visible to the
  resident (used only mid-generation; invoices are created directly as
  `open` in this implementation since generation is a single transaction,
  but the state exists for the month-close workflow and for manual
  adjustment invoices a manager starts and does not immediately open).
- `open`: issued, due on the 1st, visible to the resident, autopay and
  manual payment both apply here.
- `processing`: a payment attempt is in flight (covers Stripe's
  `requires_action`/`processing` intent states and FakeProvider's delayed
  bank settlement).
- `past_due`: open past the 1st with an unpaid balance; `mark_past_due`
  sets this starting the 2nd. Not a lockout: dispatch behavior is
  unaffected.
  `paid`: the ledger's receivable credits for this invoice equal its
  total.
- `void`: cancelled by a manager; only legal from `draft` or `open`. A
  voided invoice's receivable and revenue lines are reversed in the
  ledger.

## Limitations (left out on purpose)

- Taxes are not modeled; totals are plan price only.
- No deposits.
- No late fees.
- Multi-currency is not supported; one currency (USD) per building.
- No payouts to the building or the operator; the building's own banking
  is out of scope.
- No dispute or chargeback handling; a chargeback would need to be
  recorded manually as a refund by a manager in this version.
- The Stripe integration is written against the real `stripe` SDK shapes
  (SetupIntent, off session PaymentIntent, webhook signature
  verification) but has never been exercised against the live Stripe test
  API in this environment (no network egress, no test API keys
  available). See docs/KNOWN-ISSUES.md. FakeProvider is the fully
  exercised, fully tested default.
- The in-memory rate limiter and in-process event bus documented in
  earlier prompts still apply to billing endpoints; no new scaling
  concerns are introduced here.
