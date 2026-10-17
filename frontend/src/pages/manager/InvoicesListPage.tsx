import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import * as api from "../../lib/apiClient"
import type { InvoiceStatus } from "../../lib/apiClient"
import { formatCents } from "../../lib/format"
import {
  invoiceStatusClass,
  invoiceStatusLabel,
  isOutageError,
  monthLabel,
  useResidentDirectory,
} from "./billingShared"
import { OutageBanner } from "./StateScreens"

const STATUS_FILTERS: { key: InvoiceStatus | "all"; label: string }[] = [
  { key: "all", label: "All" },
  { key: "open", label: "Due" },
  { key: "processing", label: "Processing" },
  { key: "paid", label: "Paid" },
  { key: "past_due", label: "Past due" },
  { key: "void", label: "Void" },
]

export function InvoicesListPage({
  month,
  onOpenInvoice,
  onMonthClose,
}: {
  month: string
  onOpenInvoice: (invoiceId: string) => void
  onMonthClose: () => void
}) {
  const [statusFilter, setStatusFilter] = useState<InvoiceStatus | "all">("all")
  const [search, setSearch] = useState("")
  const invoicesQuery = useQuery({
    queryKey: ["manager-invoices", statusFilter],
    queryFn: () => api.managerListInvoices(statusFilter === "all" ? undefined : statusFilter),
  })
  const { byId } = useResidentDirectory()
  const invoices = (invoicesQuery.data ?? []).filter((inv) => inv.period_start.slice(0, 7) === month)

  const needle = search.trim().toLowerCase()
  const filtered = needle
    ? invoices.filter((inv) => {
        const resident = byId.get(inv.resident_id)
        return (
          inv.id.toLowerCase().includes(needle) ||
          resident?.full_name.toLowerCase().includes(needle) ||
          resident?.unit?.toLowerCase().includes(needle)
        )
      })
    : invoices

  return (
    <>
      <header className="row between">
        <div>
          <h1 className="t28 w7">Invoices</h1>
          <div className="t14 c-ink2">
            {monthLabel(month)}, showing {filtered.length} invoice{filtered.length === 1 ? "" : "s"}
          </div>
        </div>
        <div className="row g3">
          <button type="button" className="btn btn-secondary" onClick={onMonthClose}>
            Month close
          </button>
        </div>
      </header>
      {invoicesQuery.isError && isOutageError(invoicesQuery.error) && <OutageBanner />}
      <div className="col g2">
        <div className="fbar">
          <input
            className="inp"
            style={{ width: 360 }}
            aria-label="Search invoices"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by resident, unit or invoice number"
          />
        </div>
        <div className="fbar" aria-label="Status filters">
          {STATUS_FILTERS.map((f) => (
            <button
              key={f.key}
              type="button"
              className={`fl${statusFilter === f.key ? " on" : ""}`}
              aria-pressed={statusFilter === f.key}
              onClick={() => setStatusFilter(f.key)}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>
      <section aria-label="Invoice list">
        <div className="tbl">
          <div
            className="tr th"
            style={{ gridTemplateColumns: "1.5fr 1.6fr .6fr 1fr .8fr .8fr", padding: "0 var(--sp-4)" }}
          >
            <div>Invoice</div>
            <div>Resident</div>
            <div>Unit</div>
            <div>Month</div>
            <div className="tr-r">Total</div>
            <div className="tr-r">Status</div>
          </div>
          {filtered.map((inv) => {
            const resident = byId.get(inv.resident_id)
            return (
              <button
                key={inv.id}
                type="button"
                className="tr"
                style={{
                  gridTemplateColumns: "1.5fr 1.6fr .6fr 1fr .8fr .8fr",
                  padding: "0 var(--sp-4)",
                  width: "100%",
                  textAlign: "left",
                  background: "transparent",
                  border: 0,
                }}
                onClick={() => onOpenInvoice(inv.id)}
              >
                <div className="w7">{inv.id}</div>
                <div>{resident?.full_name ?? "Resident"}</div>
                <div>{resident?.unit ?? "-"}</div>
                <div>{monthLabel(inv.period_start.slice(0, 7))}</div>
                <div className="tr-r w7">{formatCents(inv.total_cents)}</div>
                <div className="tr-r">
                  <span className={`sw ${invoiceStatusClass(inv.status)}`}>{invoiceStatusLabel(inv.status)}</span>
                </div>
              </button>
            )
          })}
          {filtered.length === 0 && !invoicesQuery.isLoading && (
            <div className="tr" style={{ gridTemplateColumns: "1fr", padding: "0 var(--sp-4)", cursor: "default" }}>
              <div className="t14 c-ink2">No invoices match these filters for {monthLabel(month)}.</div>
            </div>
          )}
        </div>
      </section>
    </>
  )
}
