import { useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import * as api from "../../lib/apiClient"
import { ApiError } from "../../lib/apiClient"
import { formatCents, formatDate } from "../../lib/format"
import { Icon } from "../../components/Icon"
import { useAuth } from "../../context/AuthContext"
import { AddMethodForm } from "./AddMethodForm"
import { MethodGlyph, methodLabel, monthLabel, useAutopayToggle } from "./helpers"

type Phase = "form" | "processing" | "succeeded" | "failed" | "bank_processing" | "requires_action"

// The pay sheet covers R24 through R29: card form, processing, success,
// declined, bank pending and the extra verification step. Which of these
// shows is decided entirely by the status POST /billing/invoices/{id}/pay
// returns (see backend/app/billing/charge.py), never guessed client side.
export function PaySheet({ invoiceId, onClose }: { invoiceId: string; onClose: () => void }) {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const autopay = useAutopayToggle()

  const invoiceQuery = useQuery({
    queryKey: ["billing", "invoice", invoiceId],
    queryFn: () => api.getInvoice(invoiceId),
  })
  const methodsQuery = useQuery({ queryKey: ["billing", "methods"], queryFn: api.listPaymentMethods })
  const summaryQuery = useQuery({ queryKey: ["billing", "summary"], queryFn: api.getBillingSummary })

  const [selectedMethodIdOverride, setSelectedMethodId] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [phase, setPhase] = useState<Phase | null>(null)
  const [declinedMethodId, setDeclinedMethodId] = useState<string | null>(null)
  const [payError, setPayError] = useState<string | null>(null)
  const [verifyCode, setVerifyCode] = useState("")

  const methods = methodsQuery.data ?? []
  const invoice = invoiceQuery.data
  const summary = summaryQuery.data

  // Defaulting to the first method without an effect: the pick is derived
  // at render time, and only overridden once the resident taps a row
  const selectedMethodId = selectedMethodIdOverride ?? methods[0]?.id ?? null

  const remainingCents = invoice ? invoice.total_cents - invoice.paid_cents : 0
  const effectivePhase: Phase =
    phase ?? (invoice?.status === "processing" ? "bank_processing" : "form")

  function selectMethod(id: string) {
    setSelectedMethodId(id)
    if (phase === "failed") setPhase("form")
  }

  function methodAdded(method: api.PaymentMethod) {
    setAdding(false)
    setSelectedMethodId(method.id)
    queryClient.invalidateQueries({ queryKey: ["billing", "methods"] })
    if (phase === "failed") setPhase("form")
  }

  async function submitPayment(methodId: string) {
    if (!user) return
    setPhase("processing")
    setPayError(null)
    try {
      const payment = await api.payInvoice(user.csrf_token, api.newIdempotencyKey(), invoiceId, methodId)
      queryClient.invalidateQueries({ queryKey: ["billing"] })
      if (payment.status === "succeeded") {
        setPhase("succeeded")
      } else if (payment.status === "failed") {
        setDeclinedMethodId(methodId)
        setPhase("failed")
      } else if (payment.status === "requires_action") {
        setPhase("requires_action")
      } else {
        setPhase("bank_processing")
      }
    } catch (err) {
      setPayError(err instanceof ApiError ? err.message : "Could not reach the payment processor")
      setPhase("form")
    }
  }

  if (!invoice) {
    return (
      <>
        <div className="scrim" />
        <section className="sheet p-sheet" role="dialog" aria-label="Loading invoice">
          <div className="grab" />
          <p className="t16 c-ink2">Loading the invoice.</p>
        </section>
      </>
    )
  }

  if (invoice.status === "paid" || invoice.status === "void") {
    return (
      <>
        <div className="scrim" />
        <section className="sheet p-sheet" role="dialog" aria-label="Invoice status">
          <div className="row between">
            <h2 className="t20 w7">{invoice.status === "paid" ? "Already paid" : "Voided"}</h2>
            <button className="btn btn-quiet ibtn" type="button" aria-label="Close" onClick={onClose}>
              <Icon name="plus" rotate={45} />
            </button>
          </div>
          <p className="t16">
            {invoice.status === "paid" ? "This invoice is paid in full." : "This invoice was voided, no balance owed."}
          </p>
          <button type="button" className="btn btn-primary btn-xl" onClick={onClose}>
            Done
          </button>
        </section>
      </>
    )
  }

  const disabledDuringCharge = effectivePhase === "processing" || effectivePhase === "bank_processing"
  const busy = effectivePhase === "processing"

  return (
    <>
      <div className="scrim" />
      <section className="sheet p-sheet" role="dialog" aria-label={`Pay ${monthLabel(invoice.period_start)} invoice`}>
        <div className="grab" />
        <div className="row between">
          <h2 className="t20 w7">Pay {monthLabel(invoice.period_start)} invoice</h2>
          <button
            className="btn btn-quiet ibtn p-dis"
            type="button"
            aria-label="Close"
            onClick={onClose}
            disabled={busy}
          >
            <Icon name="plus" rotate={45} />
          </button>
        </div>

        {effectivePhase === "succeeded" ? (
          <div className="col g2" role="status">
            <p className="t16 w7 c-done">Paid. Receipt sent to {user?.email}.</p>
            <div className="amt">
              <p className="n md count-up">{formatCents(invoice.total_cents)}</p>
              <p className="u t14">Invoice {invoice.id}, due {formatDate(invoice.due_at)}</p>
            </div>
          </div>
        ) : (
          <div className="amt">
            <p className="n md">{formatCents(remainingCents)}</p>
            <p className="u t14">
              Invoice {invoice.id}, due {formatDate(invoice.due_at)}
            </p>
          </div>
        )}

        {effectivePhase === "processing" && (
          <p className="t16 w7 c-way" role="status">
            Charging {selectedMethodId ? methodLabel(methods.find((m) => m.id === selectedMethodId) ?? { kind: "card", brand: null, last4: "" }) : "your payment method"}.
          </p>
        )}
        {effectivePhase === "failed" && (
          <p className="t16 w7 c-late" role="alert">
            Card declined. Try another card.
          </p>
        )}
        {effectivePhase === "bank_processing" && (
          <div className="col g1" role="status">
            <p className="t16 w7 c-way">Processing. Bank payments take about 3 business days.</p>
            <p className="t16 c-ink2">
              The invoice will show Processing until it clears. Bring my car keeps working in the meantime.
            </p>
          </div>
        )}
        {effectivePhase === "requires_action" && (
          <div className="col g2">
            <p className="t16">Enter the code your bank sent to confirm this payment.</p>
            <div className="field">
              <label className="lbl" htmlFor="verify-code">
                Verification code
              </label>
              <input
                className="inp is-focus"
                id="verify-code"
                inputMode="numeric"
                autoComplete="one-time-code"
                value={verifyCode}
                onChange={(e) => setVerifyCode(e.target.value)}
              />
            </div>
          </div>
        )}
        {payError && (
          <p className="hint err" role="alert">
            {payError}
          </p>
        )}

        {!adding && (
          <div className="pay-pm" role="radiogroup" aria-label="Payment method">
            {methods.map((m) => (
              <button
                key={m.id}
                type="button"
                className={`pm-row${selectedMethodId === m.id ? " on" : ""}${disabledDuringCharge && selectedMethodId !== m.id ? " p-dis" : ""}`}
                role="radio"
                aria-checked={selectedMethodId === m.id}
                disabled={disabledDuringCharge}
                onClick={() => selectMethod(m.id)}
              >
                <span className="pm-ic">
                  <MethodGlyph kind={m.kind} />
                </span>
                <span className="m">
                  <span className="t16 w7">{methodLabel(m)}</span>
                </span>
                {effectivePhase === "failed" && declinedMethodId === m.id && (
                  <span className="t16 w7 c-late">Declined</span>
                )}
                {effectivePhase === "succeeded" && selectedMethodId === m.id && (
                  <span className="t16 w7 c-done">Paid</span>
                )}
                <span className="pm-sel" />
              </button>
            ))}
          </div>
        )}

        {!adding && effectivePhase === "form" && (
          <button type="button" className="btn btn-quiet p-addrow" onClick={() => setAdding(true)}>
            <Icon name="plus" /> Add a payment method
          </button>
        )}
        {adding && <AddMethodForm onCancel={() => setAdding(false)} onAdded={methodAdded} />}

        {!adding && (
          <div className="ap-row">
            <div className="m col" style={{ flex: 1, minWidth: 0 }}>
              <p className="t16 w7">Autopay</p>
              <p className="t14 c-ink2">
                {summary?.autopay_enabled ? "Charges your payment method on the 1st" : "Off, pay each invoice yourself"}
              </p>
            </div>
            <button
              className={`tgl${summary?.autopay_enabled ? " on" : ""}`}
              role="switch"
              aria-checked={!!summary?.autopay_enabled}
              aria-label="Autopay"
              disabled={disabledDuringCharge || autopay.isPending}
              onClick={() => autopay.mutate(!summary?.autopay_enabled)}
            />
          </div>
        )}

        {effectivePhase === "form" && !adding && (
          <button
            type="button"
            className="btn btn-primary btn-xl"
            disabled={!selectedMethodId}
            onClick={() => selectedMethodId && submitPayment(selectedMethodId)}
          >
            Pay {formatCents(remainingCents)}
          </button>
        )}
        {effectivePhase === "processing" && (
          <button type="button" className="btn btn-primary btn-xl is-loading" aria-busy="true" disabled>
            Processing
          </button>
        )}
        {effectivePhase === "succeeded" && (
          <button type="button" className="btn btn-primary btn-xl" onClick={onClose}>
            Done
          </button>
        )}
        {effectivePhase === "failed" && !adding && (
          <>
            <button type="button" className="btn btn-secondary btn-block" onClick={() => setAdding(true)}>
              Try another card
            </button>
            <button type="button" className="btn btn-primary btn-xl is-disabled" disabled>
              Pay {formatCents(remainingCents)}
            </button>
          </>
        )}
        {effectivePhase === "bank_processing" && (
          <button type="button" className="btn btn-primary btn-xl" onClick={onClose}>
            Done
          </button>
        )}
        {effectivePhase === "requires_action" && (
          <>
            <button
              type="button"
              className="btn btn-primary btn-xl"
              onClick={() => selectedMethodId && submitPayment(selectedMethodId)}
            >
              Verify
            </button>
            <button type="button" className="btn btn-quiet btn-block" onClick={() => setVerifyCode("")}>
              Send a new code
            </button>
          </>
        )}
      </section>
    </>
  )
}
