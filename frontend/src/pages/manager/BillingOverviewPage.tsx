import { useQuery } from "@tanstack/react-query"
import * as api from "../../lib/apiClient"
import { formatCents, formatDate } from "../../lib/format"
import {
  isOutageError,
  monthIsAfterCurrent,
  monthLabel,
  residentDisplayName,
  shiftMonthString,
  useResidentDirectory,
} from "./billingShared"
import { OutageBanner, ReadOnlyNotice } from "./StateScreens"

const CHART_WIDTH = 660
const CHART_HEIGHT = 320
const CHART_LEFT = 56
const CHART_RIGHT = 20
const CHART_TOP = 16
const CHART_BOTTOM = 32

function CollectionCurve({
  curve,
  billedCents,
  month,
}: {
  curve: { day: number; collected_cents: number }[]
  billedCents: number
  month: string
}) {
  if (curve.length === 0) {
    return <div className="t14 c-ink2">No collections recorded yet this month.</div>
  }
  const daysInMonth = new Date(Number(month.slice(0, 4)), Number(month.slice(5, 7)), 0).getDate()
  const maxValue = Math.max(billedCents, ...curve.map((c) => c.collected_cents), 1)
  const plotWidth = CHART_WIDTH - CHART_LEFT - CHART_RIGHT
  const plotHeight = CHART_HEIGHT - CHART_TOP - CHART_BOTTOM

  function x(day: number): number {
    return CHART_LEFT + (plotWidth * (day - 1)) / Math.max(daysInMonth - 1, 1)
  }
  function y(cents: number): number {
    return CHART_TOP + plotHeight - (plotHeight * cents) / maxValue
  }

  const points = curve.map((c) => `${x(c.day).toFixed(1)},${y(c.collected_cents).toFixed(1)}`).join(" ")
  const last = curve[curve.length - 1]
  const gridLines = [0, 0.25, 0.5, 0.75, 1]

  return (
    <svg
      width={CHART_WIDTH}
      height={CHART_HEIGHT}
      viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
      role="img"
      aria-label={`Collection curve for ${monthLabel(month)}. Billed ${formatCents(billedCents)}. Collected ${formatCents(last.collected_cents)} through day ${last.day}.`}
    >
      {gridLines.map((frac) => (
        <line
          key={frac}
          x1={CHART_LEFT}
          x2={CHART_WIDTH - CHART_RIGHT}
          y1={CHART_TOP + plotHeight - plotHeight * frac}
          y2={CHART_TOP + plotHeight - plotHeight * frac}
          stroke="var(--line)"
          strokeWidth={1}
        />
      ))}
      <line
        x1={CHART_LEFT}
        x2={CHART_WIDTH - CHART_RIGHT}
        y1={y(billedCents)}
        y2={y(billedCents)}
        stroke="var(--accent)"
        strokeOpacity={0.4}
        strokeWidth={2}
        strokeDasharray="6 4"
      />
      <polyline
        points={points}
        fill="none"
        stroke="var(--accent)"
        strokeWidth={4}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      <circle cx={x(last.day)} cy={y(last.collected_cents)} r={6} fill="var(--accent)" />
      <text x={CHART_LEFT} y={CHART_HEIGHT - 8} fontSize={12} fill="var(--ink2)">
        Day 1
      </text>
      <text x={CHART_WIDTH - CHART_RIGHT} y={CHART_HEIGHT - 8} fontSize={12} fill="var(--ink2)" textAnchor="end">
        Day {daysInMonth}
      </text>
      <text x={CHART_WIDTH - CHART_RIGHT} y={y(billedCents) - 6} fontSize={13} fontWeight={700} fill="var(--ink2)" textAnchor="end">
        Billed {formatCents(billedCents)}
      </text>
      <text x={x(last.day) + 10} y={y(last.collected_cents) - 8} fontSize={13} fontWeight={700} fill="var(--ink)">
        Collected {formatCents(last.collected_cents)}
      </text>
    </svg>
  )
}

export function BillingOverviewPage({
  month,
  onMonthChange,
  readOnly,
  onOpenInvoice,
}: {
  month: string
  onMonthChange: (month: string) => void
  readOnly: boolean
  onOpenInvoice: (invoiceId: string) => void
}) {
  const overviewQuery = useQuery({
    queryKey: ["manager-billing-overview", month],
    queryFn: () => api.managerBillingOverview(month),
  })
  const { byId } = useResidentDirectory()
  const overview = overviewQuery.data

  const pastDue = overview?.needs_attention.filter((i) => i.status === "past_due") ?? []
  const processing = overview?.needs_attention.filter((i) => i.status === "processing") ?? []

  return (
    <>
      <header className="row between">
        <div>
          <h1 className="t28 w7">Billing</h1>
          <div className="t14 c-ink2">Overview for {monthLabel(month)}</div>
        </div>
        <div className="row g2">
          <button
            type="button"
            className="btn btn-secondary"
            aria-label="Previous month"
            onClick={() => onMonthChange(shiftMonthString(month, -1))}
          >
            Back
          </button>
          <div className="t16 w7 px4">{monthLabel(month)}</div>
          <button
            type="button"
            className="btn btn-secondary"
            aria-label="Next month"
            disabled={monthIsAfterCurrent(shiftMonthString(month, 1))}
            onClick={() => onMonthChange(shiftMonthString(month, 1))}
          >
            Next
          </button>
        </div>
      </header>
      {readOnly && <ReadOnlyNotice />}
      {overviewQuery.isError && isOutageError(overviewQuery.error) && <OutageBanner />}
      {overview && (
        <>
          <div className="figs">
            <div className="mfig">
              <div className="l">Billed</div>
              <div className="n">{formatCents(overview.billed_cents)}</div>
              <div className="c c-ink2">This billing month</div>
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
              <div className="c c-ink2">
                {overview.billed_cents > 0
                  ? `${Math.round((overview.outstanding_cents / overview.billed_cents) * 100)} percent of billed`
                  : "Nothing outstanding"}
              </div>
            </div>
            <div className="mfig">
              <div className="l">Past due</div>
              <div className="n">{overview.past_due_count}</div>
              <div className="c c-late">
                {overview.past_due_count === 1 ? "invoice" : "invoices"}
              </div>
            </div>
            <div className="mfig">
              <div className="l">Autopay</div>
              <div className="n">{Math.round(overview.autopay_share * 100)}%</div>
              <div className="c c-ink2">of residents use autopay</div>
            </div>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "660px minmax(0, 1fr)", gap: "var(--sp-8)", alignItems: "start" }}>
            <section className="tile" aria-label="Collection curve">
              <h2 className="t20 w7" style={{ marginBottom: "var(--sp-2)" }}>
                Collection curve
              </h2>
              <CollectionCurve curve={overview.collection_curve} billedCents={overview.billed_cents} month={month} />
            </section>
            <section className="tile col g3" aria-label="Needs attention">
              <h2 className="t20 w7">Needs attention</h2>
              {pastDue.length === 0 && processing.length === 0 && (
                <div className="t16 c-ink2">Nothing needs attention this month.</div>
              )}
              {processing.length > 0 && (
                <div>
                  <div className="t14 w7 c-ink2 attn-h">Processing</div>
                  {processing.map((inv) => (
                    <button
                      key={inv.invoice_id}
                      type="button"
                      className="inv-row"
                      style={{ width: "100%", textAlign: "left", background: "transparent", border: 0, cursor: "pointer" }}
                      onClick={() => onOpenInvoice(inv.invoice_id)}
                    >
                      <div className="m">
                        <div className="t14 w7">{residentDisplayName(byId, inv.resident_id)}</div>
                        <div className="t14 c-ink2">Due {formatDate(inv.due_at)}</div>
                      </div>
                      <div className="a">
                        <div className="t14 w7">{formatCents(inv.total_cents - inv.paid_cents)} left</div>
                      </div>
                    </button>
                  ))}
                </div>
              )}
              {pastDue.length > 0 && (
                <div>
                  <div className="t14 w7 c-ink2 attn-h">Past due invoices</div>
                  {pastDue.map((inv) => (
                    <button
                      key={inv.invoice_id}
                      type="button"
                      className="inv-row"
                      style={{ width: "100%", textAlign: "left", background: "transparent", border: 0, cursor: "pointer" }}
                      onClick={() => onOpenInvoice(inv.invoice_id)}
                    >
                      <div className="m">
                        <div className="t14 w7">{residentDisplayName(byId, inv.resident_id)}</div>
                        <div className="t14 c-ink2">{formatCents(inv.total_cents)}, due {formatDate(inv.due_at)}</div>
                      </div>
                      <div className="a">
                        <div className="t14 w7 c-late">{formatCents(inv.total_cents - inv.paid_cents)} owed</div>
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </section>
          </div>
        </>
      )}
    </>
  )
}
