import { useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import * as api from "../../lib/apiClient"
import type { ApprovalRequestOut } from "../../lib/apiClient"
import { useAuth } from "../../context/AuthContext"
import { formatCents } from "../../lib/format"
import { isOutageError } from "./billingShared"
import { OutageBanner, ReadOnlyNotice } from "./StateScreens"
import { useMoneyStepup, StepUpPrompt } from "./MoneyStepUp"
import { ApiError } from "../../lib/apiClient"

function statusWord(status: ApprovalRequestOut["status"]): { label: string; cls: string } {
  if (status === "approved") return { label: "Approved", cls: "sw-paid" }
  if (status === "rejected") return { label: "Declined", cls: "sw-void" }
  return { label: "Waiting", cls: "sw-due" }
}

function ApprovalCard({
  approval,
  readOnly,
  onDecided,
}: {
  approval: ApprovalRequestOut
  readOnly: boolean
  onDecided: () => void
}) {
  const { user } = useAuth()
  const step = useMoneyStepup()
  const [deciding, setDeciding] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const isOwnRequest = user?.id === approval.requested_by
  const isPending = approval.status === "pending"

  async function decide(approve: boolean) {
    if (!user) return
    setDeciding(true)
    setError(null)
    try {
      await step.withStepup(() => api.managerDecideApproval(user.csrf_token, approval.id, approve))
      onDecided()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That did not work. Try again.")
    } finally {
      setDeciding(false)
    }
  }

  const word = statusWord(approval.status)

  return (
    <section className="tile col g4" aria-label={`${approval.kind} request`}>
      <div className="row between astart g4">
        <div>
          <h2 className="t20 w7">
            {approval.kind === "refund" ? "Refund" : "Credit"} of {formatCents(approval.amount_cents)}
          </h2>
          <div className="t14 c-ink2">Requested on {new Date(approval.created_at).toLocaleString()}</div>
        </div>
        <div className={`t16 w7 ${approval.status === "approved" ? "c-done" : approval.status === "rejected" ? "c-ink2" : "c-called"}`}>
          {word.label}
        </div>
      </div>
      <div className="col g1">
        <div className="lbl">Reason given</div>
        <div className="t16">{approval.reason}</div>
      </div>
      {isPending && (
        <>
          <div className="row g3">
            <button
              type="button"
              className="btn btn-primary"
              disabled={readOnly || isOwnRequest || deciding}
              onClick={() => decide(true)}
            >
              Approve {approval.kind}
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              disabled={readOnly || isOwnRequest || deciding}
              onClick={() => decide(false)}
            >
              Decline
            </button>
          </div>
          {isOwnRequest && (
            <div className="t14 c-ink2">
              You requested this {approval.kind}, so you cannot approve or decline it. Another
              manager needs to decide.
            </div>
          )}
          {!isOwnRequest && (
            <div className="t14 c-ink2">
              You did not request this {approval.kind}, so you can decide it.
            </div>
          )}
        </>
      )}
      {error && (
        <div className="card-late">
          <div className="t14 w7 c-late">{error}</div>
        </div>
      )}
      <StepUpPrompt
        open={step.stepupOpen}
        code={step.stepupCode}
        onCodeChange={step.setStepupCode}
        submitting={step.stepupSubmitting}
        error={step.stepupError}
        onSubmit={step.submitStepup}
        onCancel={step.cancelStepup}
      />
    </section>
  )
}

export function ApprovalsPage({ readOnly }: { readOnly: boolean }) {
  const queryClient = useQueryClient()
  const approvalsQuery = useQuery({ queryKey: ["manager-approvals"], queryFn: api.managerListApprovals })
  const approvals = approvalsQuery.data ?? []
  const pending = approvals.filter((a) => a.status === "pending")
  const decided = approvals.filter((a) => a.status !== "pending")

  function refresh() {
    queryClient.invalidateQueries({ queryKey: ["manager-approvals"] })
    queryClient.invalidateQueries({ queryKey: ["manager-invoices"] })
    queryClient.invalidateQueries({ queryKey: ["manager-billing-overview"] })
  }

  return (
    <>
      <header className="row between">
        <div>
          <h1 className="t28 w7">Approvals</h1>
          <div className="t14 c-ink2">
            {pending.length === 0 ? "None for you to decide" : `${pending.length} waiting`}
          </div>
        </div>
      </header>
      {readOnly && <ReadOnlyNotice />}
      {approvalsQuery.isError && isOutageError(approvalsQuery.error) && <OutageBanner />}
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 400px", gap: "var(--sp-6)", alignItems: "start" }}>
        <div className="col g4">
          {pending.map((approval) => (
            <ApprovalCard key={approval.id} approval={approval} readOnly={readOnly} onDecided={refresh} />
          ))}
          {pending.length === 0 && (
            <section className="tile">
              <div className="t16 c-ink2">No refund or credit requests are waiting on a decision.</div>
            </section>
          )}
        </div>
        <section className="tile col g2" aria-label="Decided approvals">
          <h2 className="t20 w7">Decided</h2>
          {decided.length === 0 && <div className="t14 c-ink2">Nothing decided yet.</div>}
          {decided.map((a) => {
            const word = statusWord(a.status)
            return (
              <div className="apr-row" key={a.id}>
                <div className="grow">
                  <div className="t16 w7">
                    {a.kind === "refund" ? "Refund" : "Credit"} {formatCents(a.amount_cents)}
                  </div>
                  <div className="t14 c-ink2">{new Date(a.created_at).toLocaleDateString()}</div>
                </div>
                <span className={`sw ${word.cls}`}>{word.label}</span>
              </div>
            )
          })}
          <div className="t14 c-ink2">Refunds and credits of $200.00 or more need a second manager.</div>
        </section>
      </div>
    </>
  )
}
