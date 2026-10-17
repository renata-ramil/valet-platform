import { useState } from "react"
import * as api from "../../lib/apiClient"
import { ApiError } from "../../lib/apiClient"
import type { ManagerInvoiceDetail } from "../../lib/apiClient"
import { formatCents, formatDate } from "../../lib/format"
import { centsToDollarsInput, parseDollarsToCents } from "./billingShared"
import { useMoneyStepup, StepUpPrompt } from "./MoneyStepUp"

const REFUND_APPROVAL_THRESHOLD_CENTS = 20_000

function ErrorNotice({ message }: { message: string }) {
  return (
    <div className="card-late">
      <div className="t14 w7 c-late">{message}</div>
    </div>
  )
}

function errorMessage(err: unknown): string {
  return err instanceof ApiError ? err.message : "That did not work. Try again."
}

// Record offline payment: M23's first dialog
export function RecordPaymentDialog({
  invoice,
  csrf,
  onClose,
  onDone,
}: {
  invoice: ManagerInvoiceDetail
  csrf: string
  onClose: () => void
  onDone: () => void
}) {
  const step = useMoneyStepup()
  const outstanding = invoice.total_cents - invoice.paid_cents
  const [amount, setAmount] = useState(centsToDollarsInput(Math.max(outstanding, 0)))
  const [method, setMethod] = useState<"cash" | "check" | "transfer">("check")
  const [reference, setReference] = useState("")
  const [paidOn, setPaidOn] = useState(new Date().toISOString().slice(0, 10))
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [idempotencyKey] = useState(() => api.newIdempotencyKey())

  const amountCents = parseDollarsToCents(amount)
  const canSubmit = amountCents !== null && !submitting

  async function submit() {
    if (amountCents === null) return
    setSubmitting(true)
    setError(null)
    try {
      await step.withStepup(() =>
        api.managerRecordPayment(csrf, idempotencyKey, invoice.id, {
          amount_cents: amountCents,
          method,
          reference: reference || undefined,
          paid_on: paidOn || undefined,
        }),
      )
      onDone()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <>
      <div className="money-modal">
        <div className="scrim" />
        <section className="dlg" role="dialog" aria-label="Record offline payment">
        <div>
          <h2 className="t20 w7">Record offline payment</h2>
          <div className="t14 c-ink2">
            This marks invoice {invoice.id} as paid by money received outside the card system.
          </div>
        </div>
        <div className="field">
          <span className="lbl">Method</span>
          <div className="seg">
            {(["cash", "check", "transfer"] as const).map((m) => (
              <button
                key={m}
                type="button"
                className={`seg-i${method === m ? " on" : ""}`}
                onClick={() => setMethod(m)}
              >
                {m[0].toUpperCase() + m.slice(1)}
              </button>
            ))}
          </div>
        </div>
        <div className="field">
          <label className="lbl" htmlFor="rp-reference">
            Reference
          </label>
          <input
            className="inp"
            id="rp-reference"
            value={reference}
            onChange={(e) => setReference(e.target.value)}
            placeholder="Check number or transfer id"
          />
        </div>
        <div className="field">
          <label className="lbl" htmlFor="rp-date">
            Date received
          </label>
          <input
            className="inp"
            id="rp-date"
            type="date"
            value={paidOn}
            onChange={(e) => setPaidOn(e.target.value)}
          />
        </div>
        <div className="field">
          <label className="lbl" htmlFor="rp-amount">
            Amount
          </label>
          <input
            className="inp"
            id="rp-amount"
            inputMode="decimal"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
          />
        </div>
        {error && <ErrorNotice message={error} />}
        <div className="row g3" style={{ justifyContent: "flex-end" }}>
          <button type="button" className="btn btn-quiet" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="btn btn-primary" disabled={!canSubmit} onClick={submit}>
            {submitting ? "Recording..." : "Record payment"}
          </button>
        </div>
        </section>
      </div>
      <StepUpPrompt
        open={step.stepupOpen}
        code={step.stepupCode}
        onCodeChange={step.setStepupCode}
        submitting={step.stepupSubmitting}
        error={step.stepupError}
        onSubmit={step.submitStepup}
        onCancel={step.cancelStepup}
      />
    </>
  )
}

// Issue credit: M23's second dialog. A credit at or above the approval
// threshold comes back pending_approval instead of applied, so both
// confirmations are shown depending on what the server answers.
export function IssueCreditDialog({
  invoice,
  csrf,
  onClose,
  onDone,
}: {
  invoice: ManagerInvoiceDetail
  csrf: string
  onClose: () => void
  onDone: () => void
}) {
  const step = useMoneyStepup()
  const [amount, setAmount] = useState("")
  const [reason, setReason] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<"applied" | "pending_approval" | null>(null)
  const [idempotencyKey] = useState(() => api.newIdempotencyKey())

  const amountCents = parseDollarsToCents(amount)
  const canSubmit = amountCents !== null && reason.trim().length > 0 && !submitting

  async function submit() {
    if (amountCents === null) return
    setSubmitting(true)
    setError(null)
    try {
      const response = await step.withStepup(() =>
        api.managerIssueCredit(csrf, idempotencyKey, invoice.id, {
          amount_cents: amountCents,
          reason: reason.trim(),
        }),
      )
      setResult(response.status === "pending_approval" ? "pending_approval" : "applied")
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  if (result) {
    return (
      <div className="money-modal">
        <div className="scrim" />
        <section className="dlg" role="dialog" aria-label="Credit result">
          <h2 className="t20 w7">
            {result === "applied" ? "Credit issued" : "Credit sent for approval"}
          </h2>
          <div className="t16">
            {result === "applied"
              ? `The credit reduces the next invoice for this resident and shows as its own line.`
              : `This credit is $${(amountCents! / 100).toFixed(2)} or more, so another manager must approve it before it applies. Find it under Approvals.`}
          </div>
          <div className="row g3" style={{ justifyContent: "flex-end" }}>
            <button type="button" className="btn btn-primary" onClick={onDone}>
              Done
            </button>
          </div>
        </section>
      </div>
    )
  }

  return (
    <>
      <div className="money-modal">
        <div className="scrim" />
        <section className="dlg" role="dialog" aria-label="Issue credit">
        <div>
          <h2 className="t20 w7">Issue credit</h2>
          <div className="t14 c-ink2">
            The credit reduces the next invoice for this resident and shows as its own line.
          </div>
        </div>
        <div className="field">
          <label className="lbl" htmlFor="cr-amount">
            Amount
          </label>
          <input
            className="inp"
            id="cr-amount"
            inputMode="decimal"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            placeholder="0.00"
          />
        </div>
        <div className="field">
          <label className="lbl" htmlFor="cr-reason">
            Reason
          </label>
          <input
            className="inp"
            id="cr-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Nine unused days after a car ended"
          />
        </div>
        {amountCents !== null && amountCents >= REFUND_APPROVAL_THRESHOLD_CENTS && (
          <div className="t14 w7">
            Credits of $200.00 or more need a second manager. This one will be sent for approval.
          </div>
        )}
        {error && <ErrorNotice message={error} />}
        <div className="row g3" style={{ justifyContent: "flex-end" }}>
          <button type="button" className="btn btn-quiet" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="btn btn-primary" disabled={!canSubmit} onClick={submit}>
            {submitting ? "Working..." : "Issue credit"}
          </button>
        </div>
        </section>
      </div>
      <StepUpPrompt
        open={step.stepupOpen}
        code={step.stepupCode}
        onCodeChange={step.setStepupCode}
        submitting={step.stepupSubmitting}
        error={step.stepupError}
        onSubmit={step.submitStepup}
        onCancel={step.cancelStepup}
      />
    </>
  )
}

// Refund: M23's third dialog. The payment_id must be an existing succeeded,
// not-already-a-refund payment on this invoice, so the resident picks one
// from the invoice detail's own payments list.
export function RefundDialog({
  invoice,
  csrf,
  onClose,
  onDone,
}: {
  invoice: ManagerInvoiceDetail
  csrf: string
  onClose: () => void
  onDone: () => void
}) {
  const step = useMoneyStepup()
  const refundablePayments = invoice.payments.filter(
    (p) => p.status === "succeeded" && !p.is_refund,
  )
  const [paymentId, setPaymentId] = useState(refundablePayments[0]?.id ?? "")
  const selectedPayment = refundablePayments.find((p) => p.id === paymentId)
  const [amount, setAmount] = useState(
    selectedPayment ? centsToDollarsInput(selectedPayment.amount_cents) : "",
  )
  const [reason, setReason] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<"refunded" | "pending_approval" | null>(null)
  const [idempotencyKey] = useState(() => api.newIdempotencyKey())

  const amountCents = parseDollarsToCents(amount)
  const needsApproval = amountCents !== null && amountCents >= REFUND_APPROVAL_THRESHOLD_CENTS
  const canSubmit =
    amountCents !== null && reason.trim().length > 0 && Boolean(paymentId) && !submitting

  function pickPayment(id: string) {
    setPaymentId(id)
    const payment = refundablePayments.find((p) => p.id === id)
    if (payment) setAmount(centsToDollarsInput(payment.amount_cents))
  }

  async function submit() {
    if (amountCents === null || !paymentId) return
    setSubmitting(true)
    setError(null)
    try {
      const response = await step.withStepup(() =>
        api.managerRefund(csrf, idempotencyKey, invoice.id, {
          amount_cents: amountCents,
          reason: reason.trim(),
          payment_id: paymentId,
        }),
      )
      setResult(response.status === "pending_approval" ? "pending_approval" : "refunded")
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  if (result) {
    return (
      <div className="money-modal">
        <div className="scrim" />
        <section className="dlg" role="dialog" aria-label="Refund result">
          <h2 className="t20 w7">{result === "refunded" ? "Refund sent" : "Refund sent for approval"}</h2>
          <div className="t16">
            {result === "refunded"
              ? "The money goes back to the original payment method."
              : "This refund is $200.00 or more, so another manager must approve it. Find it under Approvals."}
          </div>
          <div className="row g3" style={{ justifyContent: "flex-end" }}>
            <button type="button" className="btn btn-primary" onClick={onDone}>
              Done
            </button>
          </div>
        </section>
      </div>
    )
  }

  if (refundablePayments.length === 0) {
    return (
      <div className="money-modal">
        <div className="scrim" />
        <section className="dlg" role="dialog" aria-label="Refund">
          <h2 className="t20 w7">Refund</h2>
          <div className="t16 c-ink2">This invoice has no successful payment to refund yet.</div>
          <div className="row g3" style={{ justifyContent: "flex-end" }}>
            <button type="button" className="btn btn-primary" onClick={onClose}>
              Close
            </button>
          </div>
        </section>
      </div>
    )
  }

  return (
    <>
      <div className="money-modal">
        <div className="scrim" />
        <section className="dlg" role="dialog" aria-label="Refund">
        <div>
          <h2 className="t20 w7">Refund</h2>
          <div className="t14 c-ink2">
            The money goes back to the original payment method once any needed approval clears.
          </div>
        </div>
        <div className="field">
          <span className="lbl">Original payment</span>
          <select
            className="inp"
            aria-label="Original payment"
            value={paymentId}
            onChange={(e) => pickPayment(e.target.value)}
          >
            {refundablePayments.map((p) => (
              <option key={p.id} value={p.id}>
                {formatDate(p.created_at)}, {p.method} payment, {formatCents(p.amount_cents)}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label className="lbl" htmlFor="rf-amount">
            Amount
          </label>
          <input
            className="inp"
            id="rf-amount"
            inputMode="decimal"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
          />
        </div>
        <div className="field">
          <label className="lbl" htmlFor="rf-reason">
            Reason
          </label>
          <input
            className="inp"
            id="rf-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Charged for a request that was cancelled"
          />
        </div>
        {needsApproval && (
          <div className="t16 w7">Needs a second manager. The request will wait for their approval.</div>
        )}
        {error && <ErrorNotice message={error} />}
        <div className="row g3" style={{ justifyContent: "flex-end" }}>
          <button type="button" className="btn btn-quiet" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="btn btn-primary" disabled={!canSubmit} onClick={submit}>
            {submitting ? "Working..." : needsApproval ? "Request approval" : "Refund"}
          </button>
        </div>
        </section>
      </div>
      <StepUpPrompt
        open={step.stepupOpen}
        code={step.stepupCode}
        onCodeChange={step.setStepupCode}
        submitting={step.stepupSubmitting}
        error={step.stepupError}
        onSubmit={step.submitStepup}
        onCancel={step.cancelStepup}
      />
    </>
  )
}

// Void: only legal from draft or open, and the backend's 409 is shown
// honestly instead of hidden, since the UI's own canVoid guess can be stale
export function VoidDialog({
  invoice,
  csrf,
  onClose,
  onDone,
}: {
  invoice: ManagerInvoiceDetail
  csrf: string
  onClose: () => void
  onDone: () => void
}) {
  const step = useMoneyStepup()
  const [reason, setReason] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const canSubmit = reason.trim().length > 0 && !submitting

  async function submit() {
    setSubmitting(true)
    setError(null)
    try {
      await step.withStepup(() => api.managerVoidInvoice(csrf, invoice.id, reason.trim()))
      onDone()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <>
      <div className="money-modal">
        <div className="scrim" />
        <section className="dlg" role="dialog" aria-label="Void invoice">
        <div>
          <h2 className="t20 w7">Void invoice</h2>
          <div className="t14 c-ink2">
            Voiding reverses this invoice's receivable and revenue lines. Only legal while it is a
            draft or open.
          </div>
        </div>
        <div className="field">
          <label className="lbl" htmlFor="vd-reason">
            Reason
          </label>
          <input
            className="inp"
            id="vd-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Issued to the wrong resident"
          />
        </div>
        {error && <ErrorNotice message={error} />}
        <div className="row g3" style={{ justifyContent: "flex-end" }}>
          <button type="button" className="btn btn-quiet" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="btn btn-primary" disabled={!canSubmit} onClick={submit}>
            {submitting ? "Voiding..." : "Void invoice"}
          </button>
        </div>
        </section>
      </div>
      <StepUpPrompt
        open={step.stepupOpen}
        code={step.stepupCode}
        onCodeChange={step.setStepupCode}
        submitting={step.stepupSubmitting}
        error={step.stepupError}
        onSubmit={step.submitStepup}
        onCancel={step.cancelStepup}
      />
    </>
  )
}
