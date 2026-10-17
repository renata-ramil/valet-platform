import { useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import * as api from "../../lib/apiClient"
import { useAuth } from "../../context/AuthContext"
import { formatCents, formatDate } from "../../lib/format"
import {
  invoiceStatusClass,
  invoiceStatusLabel,
  isOutageError,
  residentDisplayName,
  useResidentDirectory,
} from "./billingShared"
import { OutageBanner, ReadOnlyNotice } from "./StateScreens"
import { IssueCreditDialog, RecordPaymentDialog, RefundDialog, VoidDialog } from "./MoneyDialogs"

type OpenDialog = "payment" | "credit" | "refund" | "void" | null

function formatTimestamp(iso: string): string {
  return new Date(iso).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  })
}

// Turning one invoice-scoped audit event into a short sentence, since the
// chain stores a type and a raw payload rather than finished prose
function describeAuditEvent(event: { type: string; payload: Record<string, unknown> }): string {
  const payload = event.payload
  const cents = (key: string): string =>
    typeof payload[key] === "number" ? formatCents(payload[key] as number) : "an amount"
  switch (event.type) {
    case "issued":
      return `Invoice issued for ${cents("total_cents")}.`
    case "line_added":
      return `A line for ${cents("amount_cents")} was added for a car.`
    case "issued_adjustment":
      return `Issued as an adjustment invoice for ${cents("amount_cents")}.`
    case "voided":
      return `Voided. Reason: ${typeof payload.reason === "string" ? payload.reason : "none given"}.`
    case "credit_applied":
      return `A credit of ${cents("amount_cents")} was applied.`
    case "receipt_resent":
      return "A receipt was resent."
    default:
      return event.type.replace(/_/g, " ")
  }
}

export function InvoiceDetailPage({
  invoiceId,
  readOnly,
  onBack,
}: {
  invoiceId: string
  readOnly: boolean
  onBack: () => void
}) {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const { byId } = useResidentDirectory()
  const [openDialog, setOpenDialog] = useState<OpenDialog>(null)
  const [resendStatus, setResendStatus] = useState<string | null>(null)

  const detailQuery = useQuery({
    queryKey: ["manager-invoice", invoiceId],
    queryFn: () => api.managerInvoiceDetail(invoiceId),
  })
  const invoice = detailQuery.data

  function refreshAfterMoneyAction() {
    queryClient.invalidateQueries({ queryKey: ["manager-invoice", invoiceId] })
    queryClient.invalidateQueries({ queryKey: ["manager-invoices"] })
    queryClient.invalidateQueries({ queryKey: ["manager-billing-overview"] })
    queryClient.invalidateQueries({ queryKey: ["manager-approvals"] })
    setOpenDialog(null)
  }

  async function resendReceipt() {
    if (!user) return
    setResendStatus(null)
    try {
      await api.managerResendReceipt(user.csrf_token, invoiceId)
      setResendStatus("Receipt sent.")
    } catch {
      setResendStatus("Could not send the receipt. Try again.")
    }
  }

  if (detailQuery.isError && isOutageError(detailQuery.error)) {
    return (
      <>
        <header className="row between">
          <div>
            <h1 className="t28 w7">Invoice</h1>
          </div>
        </header>
        <OutageBanner />
        <button type="button" className="btn btn-secondary" onClick={onBack}>
          Back to invoices
        </button>
      </>
    )
  }

  if (!invoice) {
    return (
      <>
        <header className="row between">
          <div>
            <h1 className="t28 w7">Invoice</h1>
          </div>
        </header>
        <div className="t16 c-ink2">Loading invoice...</div>
      </>
    )
  }

  const canRecordPayment = invoice.status !== "paid" && invoice.status !== "void"
  const canVoid = invoice.status === "draft" || invoice.status === "open"
  const canRefund = invoice.payments.some((p) => p.status === "succeeded" && !p.is_refund)
  const disabledAll = readOnly

  return (
    <>
      <header className="row between">
        <div>
          <h1 className="t28 w7">Invoice {invoice.id}</h1>
          <div className="t14 c-ink2">
            {residentDisplayName(byId, invoice.resident_id)}, due {formatDate(invoice.due_at)}
          </div>
        </div>
        <div className="row g3">
          <span className={`sw ${invoiceStatusClass(invoice.status)}`}>
            {invoiceStatusLabel(invoice.status)}
          </span>
        </div>
      </header>
      {readOnly && <ReadOnlyNotice />}
      <div className="col g2">
        <div className="row g3">
          <button
            type="button"
            className="btn btn-secondary"
            disabled={disabledAll || !canRecordPayment}
            onClick={() => setOpenDialog("payment")}
          >
            Record payment
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            disabled={disabledAll}
            onClick={() => setOpenDialog("credit")}
          >
            Issue credit
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            disabled={disabledAll || !canRefund}
            onClick={() => setOpenDialog("refund")}
          >
            Refund
          </button>
          <button type="button" className="btn btn-secondary" onClick={resendReceipt}>
            Resend receipt
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            disabled={disabledAll || !canVoid}
            onClick={() => setOpenDialog("void")}
          >
            Void
          </button>
        </div>
        {resendStatus && <div className="t14 c-ink2">{resendStatus}</div>}
        <div className="hint">
          Record payment and Void only apply to a draft or open invoice. Refunds of $200.00 or more
          need a second manager.
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "420px minmax(0, 1fr)", gap: "var(--sp-8)", alignItems: "start" }}>
        <div className="col g6">
          <section className="tile" aria-label="Invoice lines">
            <h2 className="t20 w7">Lines</h2>
            {invoice.lines.map((line) => (
              <div className="inv-line" key={line.id}>
                <div className="d t16">{line.description}</div>
                <div className="v t16">{formatCents(line.amount_cents)}</div>
              </div>
            ))}
            <div className="inv-line tot">
              <div className="d t16 w7">Total</div>
              <div className="v t20">{formatCents(invoice.total_cents)}</div>
            </div>
          </section>
          <section className="tile" aria-label="Payments">
            <h2 className="t20 w7">Payments</h2>
            {invoice.payments.length === 0 && <div className="t14 c-ink2">No payments yet.</div>}
            {invoice.payments.map((p) => (
              <div className="inv-row" key={p.id}>
                <div className="m">
                  <div className="t16 w7">
                    {formatDate(p.created_at)}, {p.method} {p.is_refund ? "refund" : "payment"}
                  </div>
                  <div className="t14 c-ink2">Via {p.provider}</div>
                </div>
                <div className="a">
                  <div className="t16 w7">{formatCents(p.amount_cents)}</div>
                  <span className={`sw ${p.status === "succeeded" ? "sw-paid" : p.status === "failed" ? "sw-past" : "sw-proc"}`}>
                    {p.status}
                  </span>
                </div>
              </div>
            ))}
          </section>
        </div>
        <div className="col g6">
          <section className="tile" aria-label="Ledger entries">
            <h2 className="t20 w7 py2">Ledger entries behind this invoice</h2>
            <div className="tbl">
              <div className="tr th" style={{ gridTemplateColumns: "56px 1.2fr 1fr 72px", padding: "0 var(--sp-4)" }}>
                <div>Date</div>
                <div>Entry</div>
                <div>Account</div>
                <div className="tr-r">Amount</div>
              </div>
              {invoice.ledger_entries.map((entry) => (
                <div
                  key={entry.id}
                  className="tr"
                  style={{ gridTemplateColumns: "56px 1.2fr 1fr 72px", padding: "0 var(--sp-4)", cursor: "default" }}
                >
                  <div>{formatDate(entry.created_at)}</div>
                  <div className="w7">{entry.memo}</div>
                  <div>{entry.account}</div>
                  <div className="tr-r w7">
                    {formatCents(entry.debit_cents > 0 ? entry.debit_cents : entry.credit_cents)}
                  </div>
                </div>
              ))}
            </div>
          </section>
          <section className="tile" aria-label="Audit trail">
            <h2 className="t20 w7 py2">Audit trail</h2>
            {invoice.audit_events.map((event, index) => (
              <div className="inv-row" style={{ minHeight: 56 }} key={index}>
                <div style={{ width: 128, flex: "none" }} className="t14 c-ink2">
                  {formatTimestamp(event.created_at)}
                </div>
                <div className="m">
                  <div className="t14">{describeAuditEvent(event)}</div>
                </div>
              </div>
            ))}
            {invoice.audit_events.length === 0 && <div className="t14 c-ink2">No audit events yet.</div>}
          </section>
        </div>
      </div>
      {openDialog === "payment" && user && (
        <RecordPaymentDialog
          invoice={invoice}
          csrf={user.csrf_token}
          onClose={() => setOpenDialog(null)}
          onDone={refreshAfterMoneyAction}
        />
      )}
      {openDialog === "credit" && user && (
        <IssueCreditDialog
          invoice={invoice}
          csrf={user.csrf_token}
          onClose={() => setOpenDialog(null)}
          onDone={refreshAfterMoneyAction}
        />
      )}
      {openDialog === "refund" && user && (
        <RefundDialog
          invoice={invoice}
          csrf={user.csrf_token}
          onClose={() => setOpenDialog(null)}
          onDone={refreshAfterMoneyAction}
        />
      )}
      {openDialog === "void" && user && (
        <VoidDialog
          invoice={invoice}
          csrf={user.csrf_token}
          onClose={() => setOpenDialog(null)}
          onDone={refreshAfterMoneyAction}
        />
      )}
      <button type="button" className="btn btn-quiet" onClick={onBack}>
        Back to invoices
      </button>
    </>
  )
}
