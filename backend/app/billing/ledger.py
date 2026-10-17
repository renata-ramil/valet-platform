"""Double-entry ledger posting helpers.

Five accounts, per docs/BILLING.md decision 7: receivable and cash are
debit-normal (assets); revenue and credits are credit-normal (revenue and a
liability to residents); refunds is debit-normal (a contra-revenue account).
Every helper here posts a balanced transaction: total debit_cents equals
total credit_cents across the rows it writes, grouped by a shared
transaction_id. Nothing here ever issues an UPDATE or DELETE against
ledger_entries; the table's append-only trigger (app.audit.install_append_only_trigger)
backs that up at the database level.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Invoice, LedgerAccount, LedgerEntry, Payment


class UnbalancedTransactionError(Exception):
    def __init__(self, debit_total: int, credit_total: int):
        super().__init__(
            f"Ledger transaction does not balance: debits={debit_total} credits={credit_total}"
        )


def post_transaction(
    db: Session,
    building_id: str,
    lines: list[tuple[LedgerAccount, int, int]],
    memo: str,
    actor_id: str | None,
    invoice_id: str | None = None,
    payment_id: str | None = None,
    billing_account_id: str | None = None,
) -> str:
    """Writes a balanced set of ledger_entries rows sharing one transaction_id.

    lines is a list of (account, debit_cents, credit_cents) tuples.
    """
    debit_total = sum(d for _, d, _ in lines)
    credit_total = sum(c for _, _, c in lines)
    if debit_total != credit_total:
        raise UnbalancedTransactionError(debit_total, credit_total)

    transaction_id = str(uuid.uuid4())
    for account, debit_cents, credit_cents in lines:
        entry = LedgerEntry(
            building_id=building_id,
            transaction_id=transaction_id,
            account=account,
            debit_cents=debit_cents,
            credit_cents=credit_cents,
            invoice_id=invoice_id,
            payment_id=payment_id,
            billing_account_id=billing_account_id,
            memo=memo,
            actor_id=actor_id,
        )
        db.add(entry)
    db.flush()
    return transaction_id


def post_invoice_issued(db: Session, invoice: Invoice, actor_id: str | None) -> str:
    # Recognizing revenue and the matching receivable at issuance
    return post_transaction(
        db,
        invoice.building_id,
        [
            (LedgerAccount.receivable, invoice.total_cents, 0),
            (LedgerAccount.revenue, 0, invoice.total_cents),
        ],
        memo=f"Invoice {invoice.id} issued for {invoice.period_start}",
        actor_id=actor_id,
        invoice_id=invoice.id,
        billing_account_id=invoice.billing_account_id,
    )


def post_invoice_voided(db: Session, invoice: Invoice, actor_id: str | None) -> str:
    # Reversing the issuance entry; only legal for draft/open invoices (never paid)
    return post_transaction(
        db,
        invoice.building_id,
        [
            (LedgerAccount.revenue, invoice.total_cents, 0),
            (LedgerAccount.receivable, 0, invoice.total_cents),
        ],
        memo=f"Invoice {invoice.id} voided",
        actor_id=actor_id,
        invoice_id=invoice.id,
        billing_account_id=invoice.billing_account_id,
    )


def post_payment_succeeded(db: Session, payment: Payment, actor_id: str | None) -> str:
    return post_transaction(
        db,
        payment.building_id,
        [
            (LedgerAccount.cash, payment.amount_cents, 0),
            (LedgerAccount.receivable, 0, payment.amount_cents),
        ],
        memo=f"Payment {payment.id} for invoice {payment.invoice_id}",
        actor_id=actor_id,
        invoice_id=payment.invoice_id,
        payment_id=payment.id,
        billing_account_id=payment.billing_account_id,
    )


def post_credit_issued(
    db: Session,
    building_id: str,
    billing_account_id: str,
    amount_cents: int,
    memo: str,
    actor_id: str | None,
    invoice_id: str | None = None,
) -> str:
    # A credit reduces previously recognized revenue and raises the
    # liability owed back to the resident
    return post_transaction(
        db,
        building_id,
        [
            (LedgerAccount.revenue, amount_cents, 0),
            (LedgerAccount.credits, 0, amount_cents),
        ],
        memo=memo,
        actor_id=actor_id,
        invoice_id=invoice_id,
        billing_account_id=billing_account_id,
    )


def post_credit_applied(
    db: Session, invoice: Invoice, amount_cents: int, actor_id: str | None
) -> str:
    return post_transaction(
        db,
        invoice.building_id,
        [
            (LedgerAccount.credits, amount_cents, 0),
            (LedgerAccount.receivable, 0, amount_cents),
        ],
        memo=f"Credit applied to invoice {invoice.id}",
        actor_id=actor_id,
        invoice_id=invoice.id,
        billing_account_id=invoice.billing_account_id,
    )


def post_refund(
    db: Session,
    building_id: str,
    billing_account_id: str,
    amount_cents: int,
    memo: str,
    actor_id: str | None,
    invoice_id: str | None = None,
    payment_id: str | None = None,
) -> str:
    return post_transaction(
        db,
        building_id,
        [
            (LedgerAccount.refunds, amount_cents, 0),
            (LedgerAccount.cash, 0, amount_cents),
        ],
        memo=memo,
        actor_id=actor_id,
        invoice_id=invoice_id,
        payment_id=payment_id,
        billing_account_id=billing_account_id,
    )


def account_net_debit(
    db: Session,
    account: LedgerAccount,
    building_id: str | None = None,
    billing_account_id: str | None = None,
    invoice_id: str | None = None,
) -> int:
    """Sum(debit_cents) - sum(credit_cents) for an account under the given filters."""
    query = select(LedgerEntry).where(LedgerEntry.account == account)
    if building_id is not None:
        query = query.where(LedgerEntry.building_id == building_id)
    if billing_account_id is not None:
        query = query.where(LedgerEntry.billing_account_id == billing_account_id)
    if invoice_id is not None:
        query = query.where(LedgerEntry.invoice_id == invoice_id)
    rows = db.scalars(query).all()
    return sum(r.debit_cents for r in rows) - sum(r.credit_cents for r in rows)


def invoice_paid_cents(db: Session, invoice_id: str) -> int:
    """Cents credited to receivable for this invoice: payments plus applied credits.

    Only the credit side counts: the one debit entry against receivable is
    the original issuance of the invoice (raising what's owed), not a
    payment, so it is deliberately excluded here.
    """
    rows = db.scalars(
        select(LedgerEntry).where(
            LedgerEntry.invoice_id == invoice_id, LedgerEntry.account == LedgerAccount.receivable
        )
    ).all()
    return sum(r.credit_cents for r in rows)


def now_utc() -> datetime:
    return datetime.now(UTC)
