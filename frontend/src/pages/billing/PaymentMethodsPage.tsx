import { useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import * as api from "../../lib/apiClient"
import { ApiError } from "../../lib/apiClient"
import { formatDate } from "../../lib/format"
import { TopbarBack } from "../../components/PhoneFrame"
import { useAuth } from "../../context/AuthContext"
import { AddMethodForm } from "./AddMethodForm"
import { MethodGlyph, methodLabel, useAutopayToggle } from "./helpers"

export function PaymentMethodsPage({ onBack }: { onBack: () => void }) {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const autopay = useAutopayToggle()
  const methodsQuery = useQuery({ queryKey: ["billing", "methods"], queryFn: api.listPaymentMethods })
  const summaryQuery = useQuery({ queryKey: ["billing", "summary"], queryFn: api.getBillingSummary })
  const methods = methodsQuery.data ?? []
  const summary = summaryQuery.data

  const [confirmingId, setConfirmingId] = useState<string | null>(null)
  const [removing, setRemoving] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)

  async function doRemove(methodId: string) {
    if (!user) return
    setRemoving(true)
    setDeleteError(null)
    try {
      await api.deletePaymentMethod(user.csrf_token, methodId)
      setConfirmingId(null)
      queryClient.invalidateQueries({ queryKey: ["billing", "methods"] })
    } catch (err) {
      // The backend 409s when this is the only method and autopay is on;
      // that message is surfaced here rather than hidden, per the task
      setDeleteError(err instanceof ApiError ? err.message : "Could not remove the payment method")
    } finally {
      setRemoving(false)
    }
  }

  return (
    <>
      <TopbarBack title="Payment methods" onBack={onBack} />
      <main className="pbody">
        <div className="col g4 py2">
          <section className="col" aria-label="Payment methods">
            {methods.map((m) =>
              confirmingId === m.id ? (
                <div className="confirm" role="alertdialog" aria-label={`Remove ${methodLabel(m)}`} key={m.id}>
                  <p className="t16 w7">Remove {methodLabel(m)}?</p>
                  {deleteError && (
                    <p className="hint err" role="alert">
                      {deleteError}
                    </p>
                  )}
                  <div className="row g2">
                    <button
                      type="button"
                      className="btn btn-secondary grow"
                      disabled={removing}
                      onClick={() => doRemove(m.id)}
                    >
                      Remove
                    </button>
                    <button
                      type="button"
                      className="btn btn-primary grow"
                      onClick={() => {
                        setConfirmingId(null)
                        setDeleteError(null)
                      }}
                    >
                      Keep
                    </button>
                  </div>
                </div>
              ) : (
                <div className="pm-row" key={m.id}>
                  <span className="pm-ic">
                    <MethodGlyph kind={m.kind} />
                  </span>
                  <span className="m">
                    <span className="t16 w7">{methodLabel(m)}</span>
                  </span>
                  <button
                    type="button"
                    className="btn btn-quiet"
                    aria-label={`Remove ${methodLabel(m)}`}
                    onClick={() => {
                      setConfirmingId(m.id)
                      setDeleteError(null)
                    }}
                  >
                    Remove
                  </button>
                </div>
              ),
            )}
            {methods.length === 0 && <p className="t16 c-ink2">No payment methods yet.</p>}
          </section>

          {adding ? (
            <AddMethodForm
              onCancel={() => setAdding(false)}
              onAdded={() => {
                setAdding(false)
                queryClient.invalidateQueries({ queryKey: ["billing", "methods"] })
              }}
            />
          ) : (
            <button type="button" className="btn btn-secondary btn-block" onClick={() => setAdding(true)}>
              Add payment method
            </button>
          )}

          <div className="ap-row">
            <div className="grow col">
              <p className="t16 w7">Autopay</p>
              <p className="t16 c-ink2">
                {summary?.due_date ? `Charges on ${formatDate(summary.due_date)}` : "Charges your payment method each month"}
              </p>
            </div>
            <button
              className={`tgl${summary?.autopay_enabled ? " on" : ""}`}
              role="switch"
              aria-checked={!!summary?.autopay_enabled}
              aria-label="Autopay"
              disabled={autopay.isPending}
              onClick={() => autopay.mutate(!summary?.autopay_enabled)}
            />
          </div>
          <p className="t16 c-ink2">
            Autopay needs one method on file, so the last method stays until you turn autopay off.
          </p>
        </div>
      </main>
    </>
  )
}
