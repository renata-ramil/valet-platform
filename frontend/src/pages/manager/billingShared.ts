import { useQuery } from "@tanstack/react-query"
import * as api from "../../lib/apiClient"
import { ApiError } from "../../lib/apiClient"
import type { InvoiceStatus } from "../../lib/apiClient"

// Giving every billing screen the same month string helpers
export function currentMonthString(): string {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`
}

export function shiftMonthString(month: string, delta: number): string {
  const [year, mon] = month.split("-").map(Number)
  const date = new Date(Date.UTC(year, mon - 1 + delta, 1))
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}`
}

export function monthIsAfterCurrent(month: string): boolean {
  return month > currentMonthString()
}

// Formatting a "YYYY-MM" month string as a long label, reusing formatMonthYear
export function monthLabel(month: string): string {
  const date = new Date(`${month}-01T00:00:00`)
  return date.toLocaleDateString([], { month: "long", year: "numeric" })
}

// Parsing a dollars string like "90.00" or "$90" into integer cents, or null
// when the text does not describe a positive amount. The server still does
// the real validation; this only keeps the form honest before it submits.
export function parseDollarsToCents(text: string): number | null {
  const cleaned = text.replace(/[^0-9.-]/g, "")
  if (!cleaned) return null
  const dollars = Number(cleaned)
  if (!Number.isFinite(dollars)) return null
  const cents = Math.round(dollars * 100)
  if (cents <= 0) return null
  return cents
}

// Showing cents as a plain dollars string for an editable amount field
export function centsToDollarsInput(cents: number): string {
  return (cents / 100).toFixed(2)
}

const STATUS_LABELS: Record<InvoiceStatus, string> = {
  draft: "Draft",
  open: "Due",
  processing: "Processing",
  paid: "Paid",
  past_due: "Past due",
  void: "Void",
}

const STATUS_CLASSES: Record<InvoiceStatus, string> = {
  draft: "sw-due",
  open: "sw-due",
  processing: "sw-proc",
  paid: "sw-paid",
  past_due: "sw-past",
  void: "sw-void",
}

export function invoiceStatusLabel(status: InvoiceStatus): string {
  return STATUS_LABELS[status]
}

export function invoiceStatusClass(status: InvoiceStatus): string {
  return STATUS_CLASSES[status]
}

// Telling a payment provider outage (a 5xx or a network failure) apart from
// an ordinary 4xx (bad input, not found, forbidden), which should still show
// its own message instead of the outage banner
export function isOutageError(error: unknown): boolean {
  if (error instanceof ApiError) {
    return error.status >= 500
  }
  return error instanceof Error
}

export function isStepupError(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    error.status === 403 &&
    error.message.includes("fresh TOTP step-up")
  )
}

// Looking up a resident's name and unit from one shared query, used on every
// screen that only gets a resident_id back from a billing endpoint
export function useResidentDirectory() {
  const query = useQuery({
    queryKey: ["manager-residents"],
    queryFn: () => api.managerListResidents(),
  })
  const residents = query.data ?? []
  const byId = new Map(residents.map((r) => [r.id, r]))
  return { residents, byId, isLoading: query.isLoading }
}

export function residentDisplayName(
  byId: Map<string, { full_name: string; unit: string | null }>,
  residentId: string,
): string {
  const resident = byId.get(residentId)
  if (!resident) return "Resident"
  return resident.unit ? `${resident.full_name}, unit ${resident.unit}` : resident.full_name
}
