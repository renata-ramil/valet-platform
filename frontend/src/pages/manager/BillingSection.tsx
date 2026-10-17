import { useState } from "react"
import { useAuth } from "../../context/AuthContext"
import { currentMonthString } from "./billingShared"
import { BillingOverviewPage } from "./BillingOverviewPage"
import { InvoicesListPage } from "./InvoicesListPage"
import { InvoiceDetailPage } from "./InvoiceDetailPage"
import { ApprovalsPage } from "./ApprovalsPage"
import { MonthClosePage } from "./MonthClosePage"

type BillingView =
  | { kind: "overview" }
  | { kind: "invoices" }
  | { kind: "invoice"; invoiceId: string }
  | { kind: "approvals" }
  | { kind: "month-close" }

// Billing covers M20-M26 and the M29/M30 state screens, all behind one nav
// item. The design has no sub-navigation drawing for this, so this
// bar is a deliberate addition: without it, Invoices, Approvals and Month
// close would have no way to be reached from the Billing nav item.
const TABS: { key: BillingView["kind"]; label: string }[] = [
  { key: "overview", label: "Overview" },
  { key: "invoices", label: "Invoices" },
  { key: "approvals", label: "Approvals" },
  { key: "month-close", label: "Month close" },
]

export function BillingSection() {
  const { user } = useAuth()
  const readOnly = user?.role === "support"
  const [month, setMonth] = useState(currentMonthString())
  const [view, setView] = useState<BillingView>({ kind: "overview" })

  function openInvoice(invoiceId: string) {
    setView({ kind: "invoice", invoiceId })
  }

  return (
    <>
      <div className="fbar" aria-label="Billing sections">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            className={`fl${view.kind === tab.key ? " on" : ""}`}
            aria-pressed={view.kind === tab.key}
            onClick={() => setView({ kind: tab.key } as BillingView)}
          >
            {tab.label}
          </button>
        ))}
      </div>
      {view.kind === "overview" && (
        <BillingOverviewPage
          month={month}
          onMonthChange={setMonth}
          readOnly={readOnly}
          onOpenInvoice={openInvoice}
        />
      )}
      {view.kind === "invoices" && (
        <InvoicesListPage
          month={month}
          onOpenInvoice={openInvoice}
          onMonthClose={() => setView({ kind: "month-close" })}
        />
      )}
      {view.kind === "invoice" && (
        <InvoiceDetailPage
          invoiceId={view.invoiceId}
          readOnly={readOnly}
          onBack={() => setView({ kind: "invoices" })}
        />
      )}
      {view.kind === "approvals" && <ApprovalsPage readOnly={readOnly} />}
      {view.kind === "month-close" && <MonthClosePage month={month} />}
    </>
  )
}
