import { useMutation, useQueryClient } from "@tanstack/react-query"
import * as api from "../../lib/apiClient"
import type { InvoiceStatus, PaymentMethod } from "../../lib/apiClient"
import { useAuth } from "../../context/AuthContext"

// Naming the resident facing words for each invoice state, bold text per
// the design, never an outline
export function invoiceStatusLabel(status: InvoiceStatus): string {
  if (status === "processing") return "Processing"
  if (status === "paid") return "Paid"
  if (status === "past_due") return "Past due"
  if (status === "void") return "Void"
  return "Due"
}

// Matching the color classes vk.css already defines for invoice status text
// (.sw-due, .sw-proc, .sw-paid, .sw-past, .sw-void): these set color only,
// so they are combined with a size and weight utility class, never with the
// unrelated ".sw" swatch class used on the manager demand chart
export function invoiceStatusClass(status: InvoiceStatus): string {
  if (status === "processing") return "sw-proc"
  if (status === "paid") return "sw-paid"
  if (status === "past_due") return "sw-past"
  if (status === "void") return "sw-void"
  return "sw-due"
}

// Naming the month from an invoice's period, the way the design shows
// "November" rather than a full date
export function monthLabel(iso: string): string {
  return new Date(iso).toLocaleDateString([], { month: "long" })
}

// Dev mode only. Card and bank details never reach our servers
// (docs/BILLING.md decision 8), so there is nothing real to tokenize here.
// A small set of documented test numbers picks the FakeProvider behavior
// client side instead (see backend/app/payments/fake_provider.py). The
// mapping is shown to the resident in the add payment method form.
export function fakeTokenForCardNumber(digits: string): string {
  const last4 = digits.replace(/\D/g, "").slice(-4)
  if (last4 === "0002") return "decline"
  if (last4 === "0001") return "requires_action"
  return "ok"
}

export function fakeTokenForBankNumber(digits: string): string {
  const last4 = digits.replace(/\D/g, "").slice(-4)
  if (last4 === "0002") return "decline"
  if (last4 === "0001") return "requires_action"
  if (last4 === "0003") return "delayed_settle"
  return "ok"
}

export function methodLabel(method: Pick<PaymentMethod, "kind" | "brand" | "last4">): string {
  if (method.kind === "card") {
    const brand = method.brand ? method.brand[0].toUpperCase() + method.brand.slice(1) : "Card"
    return `${brand} ending ${method.last4}`
  }
  return `Bank account ending ${method.last4}`
}

// Shared autopay switch, used from the billing overview, the pay sheet and
// the payment methods screen
export function useAutopayToggle() {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (enabled: boolean) => api.updateAutopay(user!.csrf_token, enabled),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["billing"] })
    },
  })
}

// A small inline glyph set for the two payment method kinds, since Icon.tsx
// has no card or bank icon and is not a file this slice may edit
export function CardGlyph() {
  return (
    <svg className="g" viewBox="0 0 24 24" aria-hidden="true">
      <rect x="3" y="6" width="18" height="12" rx="2" />
      <path d="M3 10h18" />
    </svg>
  )
}

export function BankGlyph() {
  return (
    <svg className="g" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M3 10l9-6 9 6" />
      <path d="M5 10v8" />
      <path d="M12 10v8" />
      <path d="M19 10v8" />
      <path d="M3 20h18" />
    </svg>
  )
}

export function MethodGlyph({ kind }: { kind: "card" | "bank" }) {
  return kind === "card" ? <CardGlyph /> : <BankGlyph />
}
