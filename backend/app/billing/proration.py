"""Pure proration math. No database access, so the hypothesis property tests run fast.

Money is always integer cents. Rounding is round-half-to-even (banker's rounding),
per decision 5 in docs/BILLING.md.
"""

import calendar
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal


def days_in_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def month_bounds(year: int, month: int) -> tuple[date, date]:
    # Returning the first and last calendar day of a billing month
    last_day = days_in_month(year, month)
    return date(year, month, 1), date(year, month, last_day)


def next_month(year: int, month: int) -> tuple[int, int]:
    if month == 12:
        return year + 1, 1
    return year, month + 1


def prev_month(year: int, month: int) -> tuple[int, int]:
    if month == 1:
        return year - 1, 12
    return year, month - 1


def prorate_cents(monthly_cents: int, days_active: int, days_in_billing_month: int) -> int:
    """Cents for days_active out of days_in_billing_month, round half to even.

    Clamping days_active to [0, days_in_billing_month] so a caller error
    (an active range that overruns the period) never produces more than a
    full month's charge or a negative one.
    """
    if days_in_billing_month <= 0:
        raise ValueError("days_in_billing_month must be positive")
    clamped = max(0, min(days_active, days_in_billing_month))
    if clamped == 0:
        return 0
    if clamped == days_in_billing_month:
        return monthly_cents
    value = Decimal(monthly_cents) * Decimal(clamped) / Decimal(days_in_billing_month)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_EVEN))


def active_days_in_period(
    started_on: date, ended_on: date | None, period_start: date, period_end: date
) -> int:
    """Days a car counts as active within [period_start, period_end], both inclusive.

    Counts the start day and the last day, per docs/BILLING.md decision 5.
    """
    active_start = max(started_on, period_start)
    active_end = min(ended_on, period_end) if ended_on is not None else period_end
    if active_end < active_start:
        return 0
    return (active_end - active_start).days + 1


def prorate_car_charge(
    monthly_cents: int,
    started_on: date,
    ended_on: date | None,
    period_start: date,
    period_end: date,
) -> tuple[int, int, int]:
    """Returns (amount_cents, days_active, days_in_period) for one car for one period."""
    days_in_period = (period_end - period_start).days + 1
    days_active = active_days_in_period(started_on, ended_on, period_start, period_end)
    amount = prorate_cents(monthly_cents, days_active, days_in_period)
    return amount, days_active, days_in_period
