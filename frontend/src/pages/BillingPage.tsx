import { useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import * as api from "../lib/apiClient"
import { formatCents, formatDate } from "../lib/format"
import { ResidentTabbar } from "../components/ResidentTabbar"
import type { ResidentTab } from "../components/ResidentTabbar"
import { Avatar } from "../components/PhoneFrame"
import { Icon } from "../components/Icon"
import { useAuth } from "../context/AuthContext"
import { CarsPage } from "./CarsPage"
import { PaySheet } from "./billing/PaySheet"
import { InvoiceDetailPage } from "./billing/InvoiceDetailPage"
import { PaymentMethodsPage } from "./billing/PaymentMethodsPage"
import { HistoryPage } from "./billing/HistoryPage"
import { invoiceStatusClass, invoiceStatusLabel, monthLabel, useAutopayToggle } from "./billing/helpers"

type BillingView =
  | { kind: "overview" }
  | { kind: "cars" }
  | { kind: "methods" }
  | { kind: "history" }
  | { kind: "invoice"; invoiceId: string }

// Billing covers four overview states (R21 due, R22 paid, R23 first
// invoice, R33 past due), the pay sheet (R24-R29), invoice detail (R30),
// payment methods (R31) and history (R32). CarsPage (R14, R36, R37) stays
// exactly as wired in before this rewrite.
export function BillingPage({
  onNavigate,
  onOpenAccount,
}: {
  onNavigate: (tab: ResidentTab) => void
  onOpenAccount: () => void
}) {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const autopay = useAutopayToggle()
  const summaryQuery = useQuery({ queryKey: ["billing", "summary"], queryFn: api.getBillingSummary })
  const invoicesQuery = useQuery({ queryKey: ["billing", "invoices"], queryFn: api.listInvoices })
  const summary = summaryQuery.data
  const invoices = invoicesQuery.data ?? []

  const [view, setView] = useState<BillingView>({ kind: "overview" })
  const [payInvoiceId, setPayInvoiceId] = useState<string | null>(null)

  function closePaySheet() {
    setPayInvoiceId(null)
    queryClient.invalidateQueries({ queryKey: ["billing"] })
  }

  if (view.kind === "cars") {
    return <CarsPage onBack={() => setView({ kind: "overview" })} />
  }

  const pastDueInvoice = invoices.find((inv) => inv.status === "past_due")
  const openInvoice = invoices.find((inv) => inv.status === "open")
  const payableInvoice = pastDueInvoice ?? openInvoice ?? invoices[0]
  const amountDue = summary?.amount_due_cents ?? 0
  const isFirstTime = invoices.length <= 1 && amountDue > 0 && !pastDueInvoice
  const isPaidUp = !pastDueInvoice && amountDue === 0
  const recentInvoices = invoices.slice(0, 3)

  let body: React.ReactNode
  if (view.kind === "methods") {
    body = <PaymentMethodsPage onBack={() => setView({ kind: "overview" })} />
  } else if (view.kind === "history") {
    body = (
      <HistoryPage
        onBack={() => setView({ kind: "overview" })}
        onOpenInvoice={(invoiceId) => setView({ kind: "invoice", invoiceId })}
      />
    )
  } else if (view.kind === "invoice") {
    body = (
      <InvoiceDetailPage
        invoiceId={view.invoiceId}
        onBack={() => setView({ kind: "history" })}
        onPay={(invoiceId) => setPayInvoiceId(invoiceId)}
      />
    )
  } else {
    body = (
      <>
        <header className="topbar">
          <h1 className="ttl">Billing</h1>
          {user && <Avatar name={user.full_name} onClick={onOpenAccount} />}
        </header>
        <main className="pbody" data-testid="billing-page">
          <div className="col g4 py2">
            {summary &&
              (pastDueInvoice ? (
                <section className="col g2" aria-label="Payment needs attention">
                  <h2 className="t28 w7 c-late">
                    {monthLabel(pastDueInvoice.period_start)} payment of {formatCents(amountDue)} needs attention
                  </h2>
                  <p className="t16">We will retry automatically and tell you each time.</p>
                  <button
                    type="button"
                    className="btn btn-primary btn-xl"
                    onClick={() => payableInvoice && setPayInvoiceId(payableInvoice.id)}
                  >
                    Fix payment
                  </button>
                  <p className="t16 c-ink2">
                    We retry 3 and 7 days later and tell you each time. Bring my car keeps working.
                  </p>
                </section>
              ) : isFirstTime ? (
                <section className="col g2" aria-label="First payment">
                  <h2 className="t20 w7">Pay once and we handle every month after.</h2>
                  <div className="amt">
                    <span className="u">First invoice, amount due</span>
                    <span className="n">{formatCents(amountDue)}</span>
                  </div>
                  <button
                    type="button"
                    className="btn btn-primary btn-xl"
                    onClick={() => payableInvoice && setPayInvoiceId(payableInvoice.id)}
                  >
                    Pay {formatCents(amountDue)}
                  </button>
                </section>
              ) : isPaidUp ? (
                <section className="col g1" aria-label="Status">
                  <h2 className="t28 w7">
                    {summary.paid_through ? `Paid through ${formatDate(summary.paid_through)}` : "You are paid up"}
                  </h2>
                  <p className="t16 c-ink2">Bring my car keeps working whenever you need it.</p>
                </section>
              ) : (
                <section className="col g2" aria-label="Amount due">
                  <div className="amt">
                    <span className="u">Amount due</span>
                    <span className="n">{formatCents(amountDue)}</span>
                    {summary.due_date && <span className="u">Due {formatDate(summary.due_date)}</span>}
                  </div>
                  <button
                    type="button"
                    className="btn btn-primary btn-xl"
                    onClick={() => payableInvoice && setPayInvoiceId(payableInvoice.id)}
                  >
                    Pay {formatCents(amountDue)}
                  </button>
                </section>
              ))}

            <div className="ap-row">
              <p className="t16 grow">
                {summary?.autopay_enabled
                  ? summary.due_date
                    ? `Autopay is on. We charge your payment method on ${formatDate(summary.due_date)}.`
                    : "Autopay is on."
                  : "Autopay is off. Pay each invoice yourself."}
              </p>
              <button
                className={`tgl${summary?.autopay_enabled ? " on" : ""}`}
                role="switch"
                aria-checked={!!summary?.autopay_enabled}
                aria-label="Autopay"
                disabled={autopay.isPending}
                onClick={() => autopay.mutate(!summary?.autopay_enabled)}
              />
            </div>

            <section className="col" aria-label="Your cars">
              <h2 className="t16 w7 py2">Your cars</h2>
              {(summary?.cars ?? []).map((car) => (
                <div className="car-row" key={car.car_id}>
                  <span className="cp-ic">
                    <Icon name="car" />
                  </span>
                  <span className="m">
                    <span className="t16 w7">{car.license_plate}</span>
                    <span className="t14 c-ink2">{car.plan_name ?? "No plan"}</span>
                  </span>
                  <span className="a">
                    {car.monthly_cents !== null && (
                      <>
                        <span className="t16 w7">{formatCents(car.monthly_cents)}</span>
                        <span className="t14 c-ink2">a month</span>
                      </>
                    )}
                  </span>
                </div>
              ))}
            </section>

            {recentInvoices.length > 0 && (
              <section className="col" aria-label="Recent invoices">
                <div className="row between">
                  <h2 className="t16 w7 py2">Recent invoices</h2>
                  <button type="button" className="c-link t14" onClick={() => setView({ kind: "history" })}>
                    See all
                  </button>
                </div>
                {recentInvoices.map((invoice) => (
                  <button
                    type="button"
                    key={invoice.id}
                    className="inv-row"
                    onClick={() => setView({ kind: "invoice", invoiceId: invoice.id })}
                  >
                    <span className="m">
                      <span className="t16 w7">{monthLabel(invoice.period_start)}</span>
                    </span>
                    <span className="a">
                      <span className="t16 w7">{formatCents(invoice.total_cents)}</span>
                      <span className={`t14 w7 ${invoiceStatusClass(invoice.status)}`}>
                        {invoiceStatusLabel(invoice.status)}
                      </span>
                    </span>
                  </button>
                ))}
              </section>
            )}

            <button
              type="button"
              className="btn btn-secondary btn-block"
              onClick={() => setView({ kind: "methods" })}
            >
              Payment methods
            </button>
            <button type="button" className="btn btn-secondary btn-block" onClick={() => setView({ kind: "cars" })}>
              Cars
            </button>
          </div>
        </main>
        <ResidentTabbar active="billing" onChange={onNavigate} />
      </>
    )
  }

  return (
    <>
      {body}
      {payInvoiceId && <PaySheet invoiceId={payInvoiceId} onClose={closePaySheet} />}
    </>
  )
}
