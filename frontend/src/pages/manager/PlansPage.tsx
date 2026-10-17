import { useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import * as api from "../../lib/apiClient"
import type { Plan } from "../../lib/apiClient"
import { ApiError } from "../../lib/apiClient"
import { useAuth } from "../../context/AuthContext"
import { formatCents } from "../../lib/format"
import { centsToDollarsInput, isOutageError, parseDollarsToCents, shiftMonthString } from "./billingShared"
import { OutageBanner, ReadOnlyNotice } from "./StateScreens"

function firstOfNextMonth(): string {
  const next = shiftMonthString(
    `${new Date().getFullYear()}-${String(new Date().getMonth() + 1).padStart(2, "0")}`,
    1,
  )
  return `${next}-01`
}

function NewPlanDialog({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const { user } = useAuth()
  const [name, setName] = useState("")
  const [sizeClass, setSizeClass] = useState("")
  const [price, setPrice] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const priceCents = parseDollarsToCents(price)
  const canSubmit =
    name.trim().length > 0 && sizeClass.trim().length > 0 && priceCents !== null && !submitting

  async function submit() {
    if (!user || priceCents === null) return
    setSubmitting(true)
    setError(null)
    try {
      await api.managerCreatePlan(user.csrf_token, {
        name: name.trim(),
        size_class: sizeClass.trim(),
        monthly_cents: priceCents,
      })
      onCreated()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That did not work. Try again.")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="money-modal">
      <div className="scrim" />
      <section className="dlg" role="dialog" aria-label="New plan">
        <div>
          <h2 className="t20 w7">New plan</h2>
          <div className="t14 c-ink2">A plan sets the monthly price a resident pays for one car on it.</div>
        </div>
        <div className="field">
          <label className="lbl" htmlFor="pl-name">
            Name
          </label>
          <input className="inp" id="pl-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Standard" />
        </div>
        <div className="field">
          <label className="lbl" htmlFor="pl-size">
            Size class
          </label>
          <input
            className="inp"
            id="pl-size"
            value={sizeClass}
            onChange={(e) => setSizeClass(e.target.value)}
            placeholder="sedan, suv, truck"
          />
        </div>
        <div className="field">
          <label className="lbl" htmlFor="pl-price">
            Price a month
          </label>
          <input className="inp" id="pl-price" inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} placeholder="250.00" />
        </div>
        {error && (
          <div className="card-late">
            <div className="t14 w7 c-late">{error}</div>
          </div>
        )}
        <div className="row g3" style={{ justifyContent: "flex-end" }}>
          <button type="button" className="btn btn-quiet" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="btn btn-primary" disabled={!canSubmit} onClick={submit}>
            {submitting ? "Creating..." : "Create plan"}
          </button>
        </div>
      </section>
    </div>
  )
}

function PriceChangePanel({ plan, readOnly, onChanged }: { plan: Plan; readOnly: boolean; onChanged: () => void }) {
  const { user } = useAuth()
  const [price, setPrice] = useState(centsToDollarsInput(plan.current_monthly_cents))
  const [effectiveMonth, setEffectiveMonth] = useState(firstOfNextMonth().slice(0, 7))
  const [preview, setPreview] = useState<{
    affected_car_count: number
    current_monthly_cents: number
    new_monthly_cents: number
  } | null>(null)
  const [previewing, setPreviewing] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [archiveConfirm, setArchiveConfirm] = useState(false)

  const priceCents = parseDollarsToCents(price)
  const effectiveDate = `${effectiveMonth}-01`

  async function runPreview() {
    if (!user || priceCents === null) return
    setPreviewing(true)
    setError(null)
    try {
      const result = await api.managerPreviewPriceChange(user.csrf_token, plan.id, priceCents, effectiveDate)
      setPreview(result as typeof preview)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That did not work. Try again.")
    } finally {
      setPreviewing(false)
    }
  }

  async function confirmSchedule() {
    if (!user || priceCents === null) return
    setSubmitting(true)
    setError(null)
    try {
      await api.managerSchedulePriceChange(user.csrf_token, plan.id, priceCents, effectiveDate)
      setPreview(null)
      onChanged()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That did not work. Try again.")
    } finally {
      setSubmitting(false)
    }
  }

  async function archive() {
    if (!user) return
    setSubmitting(true)
    setError(null)
    try {
      await api.managerArchivePlan(user.csrf_token, plan.id)
      onChanged()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That did not work. Try again.")
    } finally {
      setSubmitting(false)
      setArchiveConfirm(false)
    }
  }

  const delta =
    preview && typeof preview.new_monthly_cents === "number" && typeof preview.current_monthly_cents === "number"
      ? (preview.new_monthly_cents - preview.current_monthly_cents) * preview.affected_car_count
      : null

  return (
    <section className="tile col g4" aria-label={`Price change for ${plan.name}`}>
      <div>
        <h2 className="t20 w7">Change the price of {plan.name}</h2>
        <div className="t14 c-ink2">Today the price is {formatCents(plan.current_monthly_cents)} a month.</div>
      </div>
      <div className="row g4">
        <div className="field grow">
          <label className="lbl" htmlFor="pc-price">
            New price a month
          </label>
          <input
            className="inp"
            id="pc-price"
            inputMode="decimal"
            value={price}
            disabled={readOnly || plan.archived}
            onChange={(e) => {
              setPrice(e.target.value)
              setPreview(null)
            }}
          />
        </div>
        <div className="field grow">
          <label className="lbl" htmlFor="pc-month">
            Effective month
          </label>
          <input
            className="inp"
            id="pc-month"
            type="month"
            min={firstOfNextMonth().slice(0, 7)}
            value={effectiveMonth}
            disabled={readOnly || plan.archived}
            onChange={(e) => {
              setEffectiveMonth(e.target.value)
              setPreview(null)
            }}
          />
        </div>
      </div>
      <div className="hint">
        Plan price changes apply from the next billing month. The current month's invoices keep today's
        price.
      </div>
      {preview && delta !== null && (
        <div className="card-tint col g2">
          <div className="t14 c-ink2">Monthly revenue change from {effectiveMonth}</div>
          <div className="amt">
            <div className="n md">
              {delta >= 0 ? "+" : ""}
              {formatCents(delta)}
            </div>
            <div className="u">a month, for {preview.affected_car_count} affected cars</div>
          </div>
        </div>
      )}
      {error && (
        <div className="card-late">
          <div className="t14 w7 c-late">{error}</div>
        </div>
      )}
      {!archiveConfirm ? (
        <div className="row between">
          <div className="row g3">
            {!preview ? (
              <button
                type="button"
                className="btn btn-secondary"
                disabled={readOnly || plan.archived || priceCents === null || previewing}
                onClick={runPreview}
              >
                {previewing ? "Previewing..." : "Preview impact"}
              </button>
            ) : (
              <button type="button" className="btn btn-primary" disabled={readOnly || submitting} onClick={confirmSchedule}>
                {submitting ? "Scheduling..." : "Schedule price change"}
              </button>
            )}
            {preview && (
              <button type="button" className="btn btn-quiet" onClick={() => setPreview(null)}>
                Cancel
              </button>
            )}
          </div>
          {!plan.archived && (
            <button type="button" className="btn btn-quiet" disabled={readOnly} onClick={() => setArchiveConfirm(true)}>
              Archive plan
            </button>
          )}
        </div>
      ) : (
        <div className="col g2">
          <div className="t16 w7">
            Archive {plan.name}? Cars already on it keep this plan and their price until you move them.
          </div>
          <div className="row g3">
            <button type="button" className="btn btn-primary" disabled={submitting} onClick={archive}>
              {submitting ? "Archiving..." : "Archive plan"}
            </button>
            <button type="button" className="btn btn-quiet" onClick={() => setArchiveConfirm(false)}>
              Cancel
            </button>
          </div>
        </div>
      )}
      <div className="hint">Archiving a plan stops new cars from choosing it. Cars already on it keep their plan until you move them.</div>
    </section>
  )
}

export function PlansPage() {
  const { user } = useAuth()
  const readOnly = user?.role === "support"
  const queryClient = useQueryClient()
  const plansQuery = useQuery({ queryKey: ["manager-plans"], queryFn: api.managerListPlans })
  const plans = plansQuery.data ?? []
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)

  const selected = plans.find((p) => p.id === selectedId) ?? plans[0] ?? null

  function refresh() {
    queryClient.invalidateQueries({ queryKey: ["manager-plans"] })
    setCreating(false)
  }

  if (plansQuery.isError && isOutageError(plansQuery.error)) {
    return (
      <>
        <header>
          <h1 className="t28 w7">Plans</h1>
        </header>
        <OutageBanner />
      </>
    )
  }

  if (plansQuery.isSuccess && plans.length === 0) {
    return (
      <>
        <header className="row between">
          <div>
            <h1 className="t28 w7">Plans</h1>
          </div>
        </header>
        {readOnly && <ReadOnlyNotice />}
        <section className="empty" style={{ gap: "var(--sp-4)", padding: "var(--sp-8) var(--sp-6)" }} aria-label="No plans">
          <h2 className="t20 w7">No plans yet</h2>
          <div className="t16 c-ink2" style={{ maxWidth: 560 }}>
            Plans set the monthly price a resident pays for each car. Create your first plan and
            residents can start choosing it when they add a car.
          </div>
          <button type="button" className="btn btn-primary" disabled={readOnly} onClick={() => setCreating(true)}>
            Create a plan
          </button>
        </section>
        <section className="tile col g2" aria-label="How plans work">
          <h2 className="t20 w7">How plans work</h2>
          <div className="t16 c-ink2" style={{ maxWidth: 640 }}>
            Each car gets one plan and one invoice line a month. Price changes apply from the next
            billing month, so current invoices stay the same.
          </div>
        </section>
        {creating && <NewPlanDialog onClose={() => setCreating(false)} onCreated={refresh} />}
      </>
    )
  }

  return (
    <>
      <header className="row between">
        <div>
          <h1 className="t28 w7">Plans</h1>
          <div className="t14 c-ink2">
            {plans.filter((p) => !p.archived).length} active plan
            {plans.filter((p) => !p.archived).length === 1 ? "" : "s"}
          </div>
        </div>
        <div className="row g3">
          <button type="button" className="btn btn-secondary" disabled={readOnly} onClick={() => setCreating(true)}>
            New plan
          </button>
        </div>
      </header>
      {readOnly && <ReadOnlyNotice />}
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)", gap: "var(--sp-8)", alignItems: "start" }}>
        <section className="tile" aria-label="Plan catalog">
          <h2 className="t20 w7 px4 py3">Catalog</h2>
          <div className="tbl">
            <div className="tr th" style={{ gridTemplateColumns: "1.4fr 1fr 1fr", padding: "0 var(--sp-4)" }}>
              <div>Plan</div>
              <div className="tr-r">Price a month</div>
              <div className="tr-r">Status</div>
            </div>
            {plans.map((p) => (
              <button
                key={p.id}
                type="button"
                className={`tr${selected?.id === p.id ? " sel" : ""}`}
                aria-current={selected?.id === p.id}
                style={{ gridTemplateColumns: "1.4fr 1fr 1fr", minHeight: 64, padding: "0 var(--sp-4)", width: "100%", textAlign: "left", background: "transparent", border: 0 }}
                onClick={() => setSelectedId(p.id)}
              >
                <div>
                  <div className="t16 w7">{p.name}</div>
                  <div className="t14 c-ink2">Size class: {p.size_class}</div>
                </div>
                <div className="t16 w7 tr-r">{formatCents(p.current_monthly_cents)}</div>
                <div className="t16 w7 tr-r">{p.archived ? "Archived" : "Active"}</div>
              </button>
            ))}
          </div>
          <div className="t14 c-ink2 px4 py3">
            {selected ? `Select a plan to change its price or archive it. ${selected.name} is selected.` : "Select a plan."}
          </div>
        </section>
        {selected && <PriceChangePanel plan={selected} readOnly={readOnly} onChanged={refresh} />}
      </div>
      {creating && <NewPlanDialog onClose={() => setCreating(false)} onCreated={refresh} />}
    </>
  )
}
