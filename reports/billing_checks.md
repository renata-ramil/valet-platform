# Billing reconciliation

Run on 2026-10-10 (simulated data; no pilot building exists yet).
Payments provider at run time: `fake`.

Provider-side comparison skipped: PAYMENTS_PROVIDER is not `stripe`, so there is no external ledger to compare against (FakeProvider keeps no records outside this database).

| Check | Rows checked | Discrepancies |
|---|---|---|
| Invoice totals equal the sum of their lines | 120 | 0 |
| Every ledger transaction balances to zero | 234 | 0 |
| Credit balances match the ledger's credits account | 40 | 0 |
| Invoice paid totals are consistent with status | 120 | 0 |
| No refund exceeds what was paid | 114 | 0 |
| The cash account matches successful payments | 1 | 0 |

Total rows checked (simulated): 629
Total discrepancies (simulated): 0

All checks passed with zero discrepancies.
