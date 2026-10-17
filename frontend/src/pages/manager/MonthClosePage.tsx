import { useQuery } from "@tanstack/react-query"
import * as api from "../../lib/apiClient"
import { formatCents } from "../../lib/format"
import { isOutageError, monthLabel } from "./billingShared"
import { OutageBanner } from "./StateScreens"

export function MonthClosePage({ month }: { month: string }) {
  const overviewQuery = useQuery({
    queryKey: ["manager-billing-overview", month],
    queryFn: () => api.managerBillingOverview(month),
  })
  const approvalsQuery = useQuery({ queryKey: ["manager-approvals"], queryFn: api.managerListApprovals })
  const overview = overviewQuery.data
  const pendingApprovals = (approvalsQuery.data ?? []).filter((a) => a.status === "pending")
  const csvUrl = api.monthCloseCsvUrl(month)

  return (
    <>
      <header className="row between">
        <div>
          <h1 className="t28 w7">Month close</h1>
          <div className="t14 c-ink2">
            Figures for {monthLabel(month)} so far. The month stays open until it ends.
          </div>
        </div>
        <div className="row g3">
          <a className="btn btn-primary" href={csvUrl} download>
            Export CSV
          </a>
        </div>
      </header>
      {overviewQuery.isError && isOutageError(overviewQuery.error) && <OutageBanner />}
      {overview && (
        <>
          <div className="figs">
            <div className="mfig">
              <div className="l">Billed</div>
              <div className="n">{formatCents(overview.billed_cents)}</div>
            </div>
            <div className="mfig">
              <div className="l">Collected</div>
              <div className="n">{formatCents(overview.collected_cents)}</div>
              <div className="c c-done">
                {overview.billed_cents > 0
                  ? `${Math.round((overview.collected_cents / overview.billed_cents) * 100)} percent of billed`
                  : "No invoices billed"}
              </div>
            </div>
            <div className="mfig">
              <div className="l">Outstanding</div>
              <div className="n">{formatCents(overview.outstanding_cents)}</div>
            </div>
            <div className="mfig">
              <div className="l">Past due</div>
              <div className="n">{overview.past_due_count}</div>
              <div className="c c-late">{overview.past_due_count === 1 ? "invoice" : "invoices"}</div>
            </div>
          </div>
          <div className="t14 c-ink2">
            Outstanding is billed less collected: {formatCents(overview.billed_cents)} less{" "}
            {formatCents(overview.collected_cents)} leaves {formatCents(overview.outstanding_cents)}.
          </div>
          <section aria-label="Close steps" style={{ maxWidth: 880 }}>
            <h2 className="t20 w7" style={{ marginBottom: "var(--sp-2)" }}>
              Close steps
            </h2>
            <div className="inv-row">
              <div className="m">
                <div className="t16 w7">Approve pending refunds and credits</div>
                <div className="t14 c-ink2">
                  {pendingApprovals.length === 0
                    ? "Nothing is waiting on a manager."
                    : `${pendingApprovals.length} waiting under Approvals.`}
                </div>
              </div>
              <div className={`t16 w7 ${pendingApprovals.length === 0 ? "c-done" : "c-called"}`}>
                {pendingApprovals.length === 0 ? "Done" : "Waiting"}
              </div>
            </div>
            <div className="inv-row">
              <div className="m">
                <div className="t16 w7">Review past due invoices</div>
                <div className="t14 c-ink2">
                  {overview.past_due_count === 0
                    ? "No invoice is past due."
                    : `${overview.past_due_count} invoice${overview.past_due_count === 1 ? "" : "s"} past due.`}
                </div>
              </div>
              <div className={`t16 w7 ${overview.past_due_count === 0 ? "c-done" : "c-late"}`}>
                {overview.past_due_count === 0 ? "Done" : "Not started"}
              </div>
            </div>
            <div className="inv-row">
              <div className="m">
                <div className="t16 w7">Export the CSV</div>
                <div className="t14 c-ink2">
                  Includes every invoice, payment, credit and refund for {monthLabel(month)}.
                </div>
              </div>
              <div className="t16 c-ink2">Not started</div>
            </div>
          </section>
        </>
      )}
    </>
  )
}
