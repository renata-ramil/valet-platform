"""`make reconcile`: recomputes every balance from the ledger and compares it
against the stored invoices and payments, printing any discrepancy and
writing reports/billing_checks.md with the pass counts and the date.

All figures here come from a live run against whatever database
DATABASE_URL points at; in this project that is simulated demo data
(backend/scripts/seed_demo.py) until a pilot building exists, so the
report labels every count as simulated.
"""

import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.billing.ledger import invoice_paid_cents
from app.models import (
    CreditBalance,
    Invoice,
    InvoiceLine,
    InvoiceStatus,
    LedgerAccount,
    LedgerEntry,
    Payment,
    PaymentStatus,
)
from app.settings import settings


class Discrepancy:
    def __init__(self, category: str, detail: str):
        self.category = category
        self.detail = detail

    def __str__(self) -> str:
        return f"[{self.category}] {self.detail}"


def check_invoice_totals_match_lines(db: Session) -> tuple[int, list[Discrepancy]]:
    invoices = list(db.scalars(select(Invoice)))
    discrepancies = []
    for invoice in invoices:
        line_total = sum(
            line.amount_cents
            for line in db.scalars(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id))
        )
        if line_total != invoice.total_cents:
            discrepancies.append(
                Discrepancy(
                    "invoice_total_vs_lines",
                    f"invoice {invoice.id}: total_cents={invoice.total_cents} "
                    f"but lines sum to {line_total}",
                )
            )
    return len(invoices), discrepancies


def check_ledger_transactions_balance(db: Session) -> tuple[int, list[Discrepancy]]:
    rows = list(db.scalars(select(LedgerEntry)))
    by_transaction: dict[str, list[LedgerEntry]] = defaultdict(list)
    for row in rows:
        by_transaction[row.transaction_id].append(row)

    discrepancies = []
    for transaction_id, entries in by_transaction.items():
        debit_total = sum(e.debit_cents for e in entries)
        credit_total = sum(e.credit_cents for e in entries)
        if debit_total != credit_total:
            discrepancies.append(
                Discrepancy(
                    "ledger_transaction_balance",
                    f"transaction {transaction_id}: debits={debit_total} credits={credit_total}",
                )
            )
    return len(by_transaction), discrepancies


def check_credit_balances_match_ledger(db: Session) -> tuple[int, list[Discrepancy]]:
    balances = list(db.scalars(select(CreditBalance)))
    discrepancies = []
    for balance in balances:
        rows = list(
            db.scalars(
                select(LedgerEntry).where(
                    LedgerEntry.account == LedgerAccount.credits,
                    LedgerEntry.billing_account_id == balance.billing_account_id,
                )
            )
        )
        ledger_balance = sum(r.credit_cents for r in rows) - sum(r.debit_cents for r in rows)
        if ledger_balance != balance.balance_cents:
            discrepancies.append(
                Discrepancy(
                    "credit_balance_vs_ledger",
                    f"billing_account {balance.billing_account_id}: cached balance_cents="
                    f"{balance.balance_cents} but ledger computes {ledger_balance}",
                )
            )
    return len(balances), discrepancies


def check_invoice_paid_totals_consistent_with_status(db: Session) -> tuple[int, list[Discrepancy]]:
    invoices = list(db.scalars(select(Invoice).where(Invoice.status != InvoiceStatus.void)))
    discrepancies = []
    for invoice in invoices:
        paid = invoice_paid_cents(db, invoice.id)
        if paid > invoice.total_cents:
            discrepancies.append(
                Discrepancy(
                    "invoice_paid_exceeds_total",
                    f"invoice {invoice.id}: paid {paid} exceeds total {invoice.total_cents}",
                )
            )
        if invoice.status == InvoiceStatus.paid and paid < invoice.total_cents:
            discrepancies.append(
                Discrepancy(
                    "invoice_marked_paid_but_not",
                    f"invoice {invoice.id}: status=paid but only {paid}/{invoice.total_cents} paid",
                )
            )
    return len(invoices), discrepancies


def check_refunds_never_exceed_what_was_paid(db: Session) -> tuple[int, list[Discrepancy]]:
    originals = list(
        db.scalars(
            select(Payment).where(
                Payment.status == PaymentStatus.succeeded, Payment.is_refund.is_(False)
            )
        )
    )
    discrepancies = []
    for original in originals:
        refunded_total = sum(
            r.amount_cents
            for r in db.scalars(select(Payment).where(Payment.refunded_payment_id == original.id))
        )
        if refunded_total > original.amount_cents:
            discrepancies.append(
                Discrepancy(
                    "refund_exceeds_payment",
                    f"payment {original.id}: refunded {refunded_total} exceeds paid "
                    f"{original.amount_cents}",
                )
            )
    return len(originals), discrepancies


def check_cash_account_matches_payments(db: Session) -> tuple[int, list[Discrepancy]]:
    """The ledger's cash account should equal successful payments minus refunds."""
    payments = list(db.scalars(select(Payment).where(Payment.status == PaymentStatus.succeeded)))
    expected_cash = sum(p.amount_cents for p in payments if not p.is_refund) - sum(
        p.amount_cents for p in payments if p.is_refund
    )
    cash_rows = list(
        db.scalars(select(LedgerEntry).where(LedgerEntry.account == LedgerAccount.cash))
    )
    ledger_cash = sum(r.debit_cents for r in cash_rows) - sum(r.credit_cents for r in cash_rows)
    discrepancies = []
    if expected_cash != ledger_cash:
        discrepancies.append(
            Discrepancy(
                "cash_account_vs_payments",
                f"payments imply cash={expected_cash} but ledger cash account nets to "
                f"{ledger_cash}",
            )
        )
    return 1, discrepancies


def run_all_checks(db: Session) -> dict:
    checks = [
        ("Invoice totals equal the sum of their lines", check_invoice_totals_match_lines),
        ("Every ledger transaction balances to zero", check_ledger_transactions_balance),
        ("Credit balances match the ledger's credits account", check_credit_balances_match_ledger),
        (
            "Invoice paid totals are consistent with status",
            check_invoice_paid_totals_consistent_with_status,
        ),
        ("No refund exceeds what was paid", check_refunds_never_exceed_what_was_paid),
        ("The cash account matches successful payments", check_cash_account_matches_payments),
    ]
    results = {}
    for name, check_fn in checks:
        count, discrepancies = check_fn(db)
        results[name] = {"checked": count, "discrepancies": discrepancies}
        status = "OK" if not discrepancies else f"{len(discrepancies)} DISCREPANCIES"
        print(f"  {name}: checked {count}, {status}")
        for d in discrepancies:
            print(f"    {d}")
    return results


def write_report(results: dict, provider_name: str) -> Path:
    lines = [
        "# Billing reconciliation",
        "",
        f"Run on {datetime.now(UTC).date().isoformat()} (simulated data; "
        "no pilot building exists yet).",
        f"Payments provider at run time: `{provider_name}`.",
        "",
    ]
    if provider_name != "stripe":
        lines.append(
            "Provider-side comparison skipped: PAYMENTS_PROVIDER is not `stripe`, so there "
            "is no external ledger to compare against (FakeProvider keeps no records outside "
            "this database)."
        )
        lines.append("")

    total_checked = 0
    total_discrepancies = 0
    lines.append("| Check | Rows checked | Discrepancies |")
    lines.append("|---|---|---|")
    for name, result in results.items():
        count = result["checked"]
        bad = len(result["discrepancies"])
        total_checked += count
        total_discrepancies += bad
        lines.append(f"| {name} | {count} | {bad} |")
    lines.append("")
    lines.append(f"Total rows checked (simulated): {total_checked}")
    lines.append(f"Total discrepancies (simulated): {total_discrepancies}")
    lines.append("")
    if total_discrepancies == 0:
        lines.append("All checks passed with zero discrepancies.")
    else:
        lines.append("Discrepancies found:")
        for name, result in results.items():
            for d in result["discrepancies"]:
                lines.append(f"- {name}: {d}")

    reports_dir = Path(__file__).resolve().parents[2] / "reports"
    reports_dir.mkdir(exist_ok=True)
    report_path = reports_dir / "billing_checks.md"
    report_path.write_text("\n".join(lines) + "\n")
    return report_path


def _main() -> int:
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        print("Running billing reconciliation")
        results = run_all_checks(db)
    finally:
        db.close()

    report_path = write_report(results, settings.payments_provider)
    print(f"Wrote {report_path}")

    total_discrepancies = sum(len(r["discrepancies"]) for r in results.values())
    if total_discrepancies == 0:
        print("Reconcile OK: zero discrepancies")
        return 0
    print(f"Reconcile FAILED: {total_discrepancies} discrepancies found")
    return 1


if __name__ == "__main__":
    sys.exit(_main())
