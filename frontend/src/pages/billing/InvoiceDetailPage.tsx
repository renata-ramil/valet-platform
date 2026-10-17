import { useQuery } from "@tanstack/react-query"
import * as api from "../../lib/apiClient"
import { formatCents, formatDate } from "../../lib/format"
import { TopbarBack } from "../../components/PhoneFrame"
import { invoiceStatusClass, invoiceStatusLabel } from "./helpers"

// Describing one line the way R30 does, using only fields the API actually
// returns. The design mock shows a specific active date range per line
// ("Oct 19 to Oct 31"), but InvoiceLineResponse only carries day counts, not
// per car start and end dates, so a prorated line states its day count
// instead of a date range it cannot honestly show
function lineDetail(invoice: api.Invoice, line: api.InvoiceLine): string {
  if (line.days_active !== null && line.days_in_month !== null && line.days_active < line.days_in_month) {
    return `${line.description} (${line.days_active} of ${line.days_in_month} days)`
  }
  return `${line.description}, ${formatDate(invoice.period_start)} to ${formatDate(invoice.period_end)}`
}

function paymentStatusDetail(invoice: api.Invoice): string {
  if (invoice.status === "paid") {
    return invoice.paid_at ? `Paid in full on ${formatDate(invoice.paid_at)}` : "Paid in full"
  }
  if (invoice.status === "processing") return "A payment is processing"
  if (invoice.status === "past_due") return `Past due since ${formatDate(invoice.due_at)}`
  if (invoice.status === "void") return "Voided, no balance owed"
  return `Due ${formatDate(invoice.due_at)}`
}

export function InvoiceDetailPage({
  invoiceId,
  onBack,
  onPay,
}: {
  invoiceId: string
  onBack: () => void
  onPay: (invoiceId: string) => void
}) {
  const invoiceQuery = useQuery({
    queryKey: ["billing", "invoice", invoiceId],
    queryFn: () => api.getInvoice(invoiceId),
  })
  const invoice = invoiceQuery.data

  return (
    <>
      <TopbarBack title="Invoice" onBack={onBack} />
      <main className="pbody">
        <div className="col g4 py2">
          {invoice && (
            <>
              <section className="col" aria-label="Invoice">
                <h2 className="t20 w7">{invoice.id}</h2>
                <p className="t16 c-ink2">
                  {invoice.issued_at ? `Issued ${formatDate(invoice.issued_at)}, due ${formatDate(invoice.due_at)}` : `Due ${formatDate(invoice.due_at)}`}
                </p>
              </section>
              <section className="col" aria-label="Lines">
                {invoice.lines.map((line) => (
                  <div className="inv-line" key={line.id}>
                    <span className="d t16">{lineDetail(invoice, line)}</span>
                    <span className="v t16">{formatCents(line.amount_cents)}</span>
                  </div>
                ))}
                <div className="inv-line tot">
                  <span className="d t16 w7">Total</span>
                  <span className="v t16">{formatCents(invoice.total_cents)}</span>
                </div>
              </section>
              <section className="col" aria-label="Payment status">
                <h2 className="t16 w7 py2">Payment status</h2>
                <div className="inv-row">
                  <span className="m">
                    <span className={`t16 w7 ${invoiceStatusClass(invoice.status)}`}>
                      {invoiceStatusLabel(invoice.status)}
                    </span>
                    <span className="t14 c-ink2">{paymentStatusDetail(invoice)}</span>
                  </span>
                </div>
                {invoice.paid_cents > 0 && invoice.paid_cents < invoice.total_cents && (
                  <p className="t14 c-ink2">
                    {formatCents(invoice.paid_cents)} of {formatCents(invoice.total_cents)} paid so far.
                  </p>
                )}
              </section>
              {(invoice.status === "open" || invoice.status === "past_due") && (
                <button type="button" className="btn btn-primary btn-xl" onClick={() => onPay(invoice.id)}>
                  Pay {formatCents(invoice.total_cents - invoice.paid_cents)}
                </button>
              )}
              <a
                className="btn btn-secondary btn-block"
                href={api.receiptUrl(invoice.id)}
                target="_blank"
                rel="noreferrer"
              >
                Download receipt
              </a>
            </>
          )}
        </div>
      </main>
    </>
  )
}
