import { useCallback, useState } from "react"
import * as api from "../../lib/apiClient"
import { ApiError } from "../../lib/apiClient"
import { useAuth } from "../../context/AuthContext"
import { isStepupError } from "./billingShared"

interface PendingStepup<T> {
  retry: () => Promise<T>
  resolve: (value: T) => void
  reject: (reason: unknown) => void
}

// Wrapping a money-moving call so a fresh TOTP step-up is asked for exactly
// when the backend needs one, then the original call is retried once with no
// extra click from the manager. Every money dialog shares this one hook.
export function useMoneyStepup() {
  const { user } = useAuth()
  const [pending, setPending] = useState<PendingStepup<unknown> | null>(null)
  const [code, setCode] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [stepupError, setStepupError] = useState<string | null>(null)

  const withStepup = useCallback(function withStepup<T>(action: () => Promise<T>): Promise<T> {
    return action().catch((err: unknown) => {
      if (!isStepupError(err)) {
        throw err
      }
      return new Promise<T>((resolve, reject) => {
        setCode("")
        setStepupError(null)
        setPending({
          retry: action,
          resolve: resolve as (value: unknown) => void,
          reject,
        })
      })
    })
  }, [])

  const submitStepup = useCallback(async () => {
    if (!pending || !user) return
    setSubmitting(true)
    setStepupError(null)
    try {
      await api.totpStepup(code, user.csrf_token)
      const result = await pending.retry()
      pending.resolve(result)
      setPending(null)
    } catch (err) {
      setStepupError(err instanceof ApiError ? err.message : "That did not work. Try again.")
    } finally {
      setSubmitting(false)
    }
  }, [pending, code, user])

  const cancelStepup = useCallback(() => {
    pending?.reject(new Error("Step-up cancelled"))
    setPending(null)
  }, [pending])

  return {
    withStepup,
    stepupOpen: pending !== null,
    stepupCode: code,
    setStepupCode: setCode,
    stepupSubmitting: submitting,
    stepupError,
    submitStepup,
    cancelStepup,
  }
}

// A single plain text input for the code, not six boxes: the design
// specifies the only code fields left anywhere are two-factor setup and
// bank verification, both plain inputs
export function StepUpPrompt({
  open,
  code,
  onCodeChange,
  submitting,
  error,
  onSubmit,
  onCancel,
}: {
  open: boolean
  code: string
  onCodeChange: (value: string) => void
  submitting: boolean
  error: string | null
  onSubmit: () => void
  onCancel: () => void
}) {
  if (!open) return null
  return (
    <div className="money-modal">
      <div className="scrim" />
      <section className="dlg" role="dialog" aria-label="Confirm with your authenticator code">
        <div>
          <h2 className="t20 w7">Confirm it is you</h2>
          <div className="t14 c-ink2">
            This action moves money, so it needs a fresh code from your authenticator app.
          </div>
        </div>
        <div className="field">
          <label className="lbl" htmlFor="stepup-code">
            Enter the 6-digit code
          </label>
          <input
            className="inp"
            id="stepup-code"
            inputMode="numeric"
            autoComplete="one-time-code"
            value={code}
            onChange={(e) => onCodeChange(e.target.value)}
            autoFocus
          />
        </div>
        {error && (
          <div className="card-late">
            <div className="t14 w7 c-late">{error}</div>
          </div>
        )}
        <div className="row g3" style={{ justifyContent: "flex-end" }}>
          <button type="button" className="btn btn-quiet" onClick={onCancel}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={submitting || code.length < 6}
            onClick={onSubmit}
          >
            {submitting ? "Checking..." : "Confirm"}
          </button>
        </div>
      </section>
    </div>
  )
}
