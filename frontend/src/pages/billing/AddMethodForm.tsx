import { useState } from "react"
import * as api from "../../lib/apiClient"
import { ApiError } from "../../lib/apiClient"
import { useAuth } from "../../context/AuthContext"
import { fakeTokenForBankNumber, fakeTokenForCardNumber } from "./helpers"

// Adding a payment method in dev mode. Card and bank details never touch our
// servers (docs/BILLING.md decision 8): the digits typed here only pick a
// fake_token for the FakeProvider, which is the only provider that runs in
// this environment (no live Stripe key, PAYMENTS_PROVIDER=fake). Reused by
// the pay sheet and the payment methods screen.
export function AddMethodForm({
  onAdded,
  onCancel,
}: {
  onAdded: (method: api.PaymentMethod) => void
  onCancel: () => void
}) {
  const { user } = useAuth()
  const [kind, setKind] = useState<api.PaymentMethodKind>("card")
  const [cardNumber, setCardNumber] = useState("4242 4242 4242 0000")
  const [expiry, setExpiry] = useState("08 / 29")
  const [cvc, setCvc] = useState("314")
  const [zip, setZip] = useState("94105")
  const [routing, setRouting] = useState("110000000")
  const [accountNumber, setAccountNumber] = useState("000000000")
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const valid =
    kind === "card"
      ? cardNumber.replace(/\D/g, "").length >= 4 && expiry.trim().length > 0 && cvc.trim().length > 0 && zip.trim().length > 0
      : accountNumber.replace(/\D/g, "").length >= 4 && routing.trim().length > 0

  async function save() {
    if (!user || !valid || saving) return
    setSaving(true)
    setError(null)
    try {
      const fakeToken =
        kind === "card" ? fakeTokenForCardNumber(cardNumber) : fakeTokenForBankNumber(accountNumber)
      const method = await api.setupPaymentMethod(user.csrf_token, { kind, fake_token: fakeToken })
      onAdded(method)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save the payment method")
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="col g3">
      <div className="seg" role="radiogroup" aria-label="Payment kind">
        <button
          type="button"
          className={`seg-i${kind === "card" ? " on" : ""}`}
          role="radio"
          aria-checked={kind === "card"}
          onClick={() => setKind("card")}
        >
          Card
        </button>
        <button
          type="button"
          className={`seg-i${kind === "bank" ? " on" : ""}`}
          role="radio"
          aria-checked={kind === "bank"}
          onClick={() => setKind("bank")}
        >
          Bank account
        </button>
      </div>
      {kind === "card" ? (
        <div className="p-form">
          <div className="field wide">
            <label className="lbl" htmlFor="am-cn">
              Card number
            </label>
            <input
              className="inp is-focus"
              id="am-cn"
              inputMode="numeric"
              autoComplete="cc-number"
              value={cardNumber}
              onChange={(e) => setCardNumber(e.target.value)}
            />
          </div>
          <div className="field">
            <label className="lbl" htmlFor="am-ex">
              Expiry
            </label>
            <input className="inp" id="am-ex" value={expiry} onChange={(e) => setExpiry(e.target.value)} />
          </div>
          <div className="field">
            <label className="lbl" htmlFor="am-cv">
              Security code
            </label>
            <input className="inp" id="am-cv" value={cvc} onChange={(e) => setCvc(e.target.value)} />
          </div>
          <div className="field">
            <label className="lbl" htmlFor="am-zp">
              ZIP
            </label>
            <input className="inp" id="am-zp" value={zip} onChange={(e) => setZip(e.target.value)} />
          </div>
        </div>
      ) : (
        <div className="col g2">
          <div className="field">
            <label className="lbl" htmlFor="am-rt">
              Routing number
            </label>
            <input
              className="inp"
              id="am-rt"
              inputMode="numeric"
              value={routing}
              onChange={(e) => setRouting(e.target.value)}
            />
          </div>
          <div className="field">
            <label className="lbl" htmlFor="am-ac">
              Account number
            </label>
            <input
              className="inp"
              id="am-ac"
              inputMode="numeric"
              value={accountNumber}
              onChange={(e) => setAccountNumber(e.target.value)}
            />
          </div>
        </div>
      )}
      <p className="t14 c-ink2">
        {kind === "card"
          ? "Dev mode, nothing is charged for real. A card ending 0000 succeeds, 0002 shows a decline, and 0001 asks for verification."
          : "Dev mode, nothing is charged for real. A bank account ending 0000 succeeds, 0002 shows a decline, and 0003 shows bank processing."}
      </p>
      {error && (
        <p className="hint err" role="alert">
          {error}
        </p>
      )}
      <div className="row g2">
        <button type="button" className="btn btn-secondary grow" onClick={onCancel}>
          Cancel
        </button>
        <button type="button" className="btn btn-primary grow" disabled={!valid || saving} onClick={save}>
          {saving ? "Saving" : "Save"}
        </button>
      </div>
    </div>
  )
}
