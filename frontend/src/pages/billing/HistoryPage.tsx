import { useQuery } from "@tanstack/react-query"
import * as api from "../../lib/apiClient"
import { formatCents } from "../../lib/format"
import { TopbarBack } from "../../components/PhoneFrame"
import { invoiceStatusClass, invoiceStatusLabel, monthLabel } from "./helpers"

export function HistoryPage({
  onBack,
  onOpenInvoice,
}: {
  onBack: () => void
  onOpenInvoice: (invoiceId: string) => void
}) {
  const invoicesQuery = useQuery({ queryKey: ["billing", "invoices"], queryFn: api.listInvoices })
  const invoices = invoicesQuery.data ?? []

  return (
    <>
      <TopbarBack title="History" onBack={onBack} />
      <main className="pbody">
        <div className="col g4 py2">
          <section className="col" aria-label="Invoices by month">
            {invoices.map((invoice) => (
              <button
                type="button"
                key={invoice.id}
                className="inv-row"
                onClick={() => onOpenInvoice(invoice.id)}
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
            {invoices.length === 0 && <p className="t16 c-ink2">No invoices yet.</p>}
          </section>
        </div>
      </main>
    </>
  )
}
