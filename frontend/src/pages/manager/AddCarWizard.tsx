import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import * as api from "../../lib/apiClient"
import { useAuth } from "../../context/AuthContext"
import { Icon } from "../../components/Icon"
import { formatCents, formatDate } from "../../lib/format"

// Giving the wizard its own local date helper since it needs the browser's
// local date, not UTC midnight
function toLocalIsoDate(date: Date): string {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, "0")
  const day = String(date.getDate()).padStart(2, "0")
  return `${year}-${month}-${day}`
}

export interface AddCarWizardInitial {
  residentId?: string | null
  make?: string | null
  model?: string | null
  color?: string | null
  licensePlate?: string | null
}

// Matching M11-M14: a three step right sheet (pick the resident, describe the
// vehicle, choose a plan and start date) ending in a success step. Reused from
// ResidentsCarsPage, ResidentDetailPage and the car requests tab in Tickets.
export function AddCarWizard({
  onClose,
  onCreated,
  initial,
}: {
  onClose: () => void
  onCreated?: (car: api.Car) => void
  initial?: AddCarWizardInitial
}) {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const [step, setStep] = useState<1 | 2 | 3 | 4>(1)

  const [residentSearch, setResidentSearch] = useState("")
  const [selectedResidentId, setSelectedResidentId] = useState<string | null>(
    initial?.residentId ?? null,
  )
  const [inviteUnit, setInviteUnit] = useState("")

  const [plate, setPlate] = useState(initial?.licensePlate ?? "")
  const [make, setMake] = useState(initial?.make ?? "")
  const [model, setModel] = useState(initial?.model ?? "")
  const [color, setColor] = useState(initial?.color ?? "")
  const [sizeClass, setSizeClass] = useState("")
  const [nickname, setNickname] = useState("")
  const [plateError, setPlateError] = useState<string | null>(null)

  const [planId, setPlanId] = useState<string | null>(null)
  const [startedOn, setStartedOn] = useState(toLocalIsoDate(new Date()))
  const [createdCar, setCreatedCar] = useState<api.Car | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)

  const residentsQuery = useQuery({
    queryKey: ["manager-residents", residentSearch],
    queryFn: () => api.managerListResidents(residentSearch || undefined),
  })
  const residents = residentsQuery.data ?? []
  const selectedResident =
    residents.find((r) => r.id === selectedResidentId) ??
    (initial?.residentId && initial.residentId === selectedResidentId
      ? { id: initial.residentId, full_name: "Loading", email: "", unit: null, car_count: 0 }
      : undefined)

  const plansQuery = useQuery({ queryKey: ["manager-plans"], queryFn: api.managerListPlans })
  const plans = (plansQuery.data ?? []).filter((p) => !p.archived)
  const sizeOptions = Array.from(new Set(plans.map((p) => p.size_class))).filter(Boolean)
  const effectiveSizeOptions = sizeOptions.length > 0 ? sizeOptions : ["Standard", "Oversize"]
  const selectedPlan = plans.find((p) => p.id === planId)

  const inviteMutation = useMutation({
    mutationFn: () => api.managerInviteResident(user!.csrf_token, inviteUnit),
  })

  const createCar = useMutation({
    mutationFn: () =>
      api.managerCreateCar(user!.csrf_token, {
        resident_id: selectedResidentId!,
        make,
        model,
        color,
        license_plate: plate,
        plan_id: planId,
        started_on: startedOn || null,
        size_class: sizeClass || null,
        nickname: nickname || null,
      }),
    onSuccess: (car) => {
      queryClient.invalidateQueries({ queryKey: ["manager-residents"] })
      queryClient.invalidateQueries({ queryKey: ["manager-resident-detail", selectedResidentId] })
      setCreatedCar(car)
      setSubmitError(null)
      setStep(4)
      onCreated?.(car)
    },
    onError: (err: unknown) => {
      if (err instanceof api.ApiError && err.status === 409) {
        setPlateError(err.message)
        setStep(2)
      } else {
        setSubmitError(err instanceof Error ? err.message : "Could not add the car")
      }
    },
  })

  const resetForAnother = () => {
    setStep(1)
    setSelectedResidentId(null)
    setResidentSearch("")
    setPlate("")
    setMake("")
    setModel("")
    setColor("")
    setSizeClass("")
    setNickname("")
    setPlateError(null)
    setPlanId(null)
    setStartedOn(toLocalIsoDate(new Date()))
    setCreatedCar(null)
    setSubmitError(null)
  }

  const residentLine = selectedResident
    ? `${selectedResident.full_name}${selectedResident.unit ? `, unit ${selectedResident.unit}` : ""}`
    : ""

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <section className="rsheet m-sh" role="dialog" aria-label="Add car">
        <div className="row between astart">
          <div>
            <h2 className="t20 w7">Add car</h2>
            <div className="t14 c-ink2">
              {step === 1 && "Step 1 of 3, choose the resident"}
              {step === 2 && "Step 2 of 3, describe the vehicle"}
              {step === 3 && "Step 3 of 3, choose the plan and start"}
              {step === 4 && "Complete"}
            </div>
          </div>
          <button
            className="btn btn-quiet"
            type="button"
            aria-label="Close"
            style={{ padding: "0 var(--sp-3)" }}
            onClick={onClose}
          >
            <Icon name="plus" rotate={45} />
          </button>
        </div>

        <div className="stp" aria-label="Add car steps">
          <div className={`stp-i${step === 1 ? " on" : step > 1 ? " done" : ""}`}>
            <span className="n">{step > 1 ? "✓" : "1"}</span>Resident
          </div>
          <div className={`stp-i${step === 2 ? " on" : step > 2 ? " done" : ""}`}>
            <span className="n">{step > 2 ? "✓" : "2"}</span>Vehicle
          </div>
          <div className={`stp-i${step === 3 ? " on" : step > 3 ? " done" : ""}`}>
            <span className="n">{step > 3 ? "✓" : "3"}</span>Plan and start
          </div>
        </div>

        {step === 1 && (
          <div className="step-body">
            <div className="field">
              <label className="lbl" htmlFor="ac-rs">
                Find a resident by name, unit or email
              </label>
              <input
                className="inp"
                id="ac-rs"
                value={residentSearch}
                onChange={(e) => setResidentSearch(e.target.value)}
                placeholder="Name, unit or email"
                data-testid="ac-resident-search"
              />
            </div>
            <div className="tbl">
              {residents.map((r) => (
                <button
                  key={r.id}
                  type="button"
                  className={`tr${r.id === selectedResidentId ? " sel" : ""}`}
                  style={{
                    gridTemplateColumns: "24px minmax(0, 1fr) auto",
                    minHeight: 64,
                    width: "100%",
                    textAlign: "left",
                    background: "transparent",
                    border: 0,
                  }}
                  data-testid="ac-resident-option"
                  onClick={() => setSelectedResidentId(r.id)}
                >
                  <span className="sel-ic" />
                  <div>
                    <div className="t16 w7">{r.full_name}</div>
                    <div className="t14 c-ink2">
                      {r.email}, {r.car_count} car{r.car_count === 1 ? "" : "s"}
                    </div>
                  </div>
                  <div className="t14 w7">{r.unit ? `Unit ${r.unit}` : "No unit"}</div>
                </button>
              ))}
              {residentsQuery.isSuccess && residents.length === 0 && (
                <p className="t14 c-ink2 py2">No resident matches that search.</p>
              )}
            </div>
            <div>
              <h3 className="t16 w7">Invite a new resident</h3>
              <div className="t14 c-ink2">
                Send an invite code to someone who is not in the building yet. Add their car once
                they sign up.
              </div>
            </div>
            <div className="row g3">
              <div className="field grow">
                <label className="lbl" htmlFor="ac-iu">
                  Unit
                </label>
                <input
                  className="inp"
                  id="ac-iu"
                  value={inviteUnit}
                  onChange={(e) => setInviteUnit(e.target.value)}
                  placeholder="Unit"
                />
              </div>
              <button
                className="btn btn-secondary"
                type="button"
                disabled={!inviteUnit || inviteMutation.isPending}
                onClick={() => inviteMutation.mutate()}
              >
                Send invite
              </button>
            </div>
            {inviteMutation.data && (
              <div className="hint">
                Invite code {inviteMutation.data.code} is ready for unit {inviteMutation.data.unit}.
              </div>
            )}
          </div>
        )}

        {step === 2 && (
          <div className="step-body">
            <div className="card-tint row between g3">
              <div className="t14 c-ink2">Adding a car for</div>
              <div className="t16 w7">{residentLine}</div>
            </div>
            <div className="field">
              <label className="lbl" htmlFor="ac-pl">
                Plate
              </label>
              <input
                className="inp"
                id="ac-pl"
                value={plate}
                onChange={(e) => {
                  setPlate(e.target.value.toUpperCase())
                  setPlateError(null)
                }}
                placeholder="Plate"
                data-testid="ac-plate-input"
              />
              {plateError && (
                <div className="hint err" role="alert">
                  {plateError}
                </div>
              )}
            </div>
            <div className="row g3">
              <div className="field grow">
                <label className="lbl" htmlFor="ac-mk">
                  Make
                </label>
                <input
                  className="inp"
                  id="ac-mk"
                  value={make}
                  onChange={(e) => setMake(e.target.value)}
                  data-testid="ac-make-input"
                />
              </div>
              <div className="field grow">
                <label className="lbl" htmlFor="ac-md">
                  Model
                </label>
                <input
                  className="inp"
                  id="ac-md"
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  data-testid="ac-model-input"
                />
              </div>
            </div>
            <div className="row g3">
              <div className="field grow">
                <label className="lbl" htmlFor="ac-co">
                  Color
                </label>
                <input
                  className="inp"
                  id="ac-co"
                  value={color}
                  onChange={(e) => setColor(e.target.value)}
                  data-testid="ac-color-input"
                />
              </div>
              <div className="field grow">
                <div className="lbl">Size class</div>
                <div className="seg">
                  {effectiveSizeOptions.map((s) => (
                    <button
                      key={s}
                      type="button"
                      className={`seg-i${sizeClass === s ? " on" : ""}`}
                      onClick={() => setSizeClass(s)}
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            </div>
            <div className="field">
              <label className="lbl" htmlFor="ac-nk">
                Nickname
              </label>
              <input
                className="inp"
                id="ac-nk"
                value={nickname}
                onChange={(e) => setNickname(e.target.value)}
                placeholder="Optional"
              />
              <div className="hint">
                The resident sees this name in their app. They can change it later.
              </div>
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="step-body">
            <div className="card-tint row between g3">
              <div className="t14 c-ink2">
                {`${color} ${model} ${plate}`.trim()} for
              </div>
              <div className="t16 w7">{residentLine}</div>
            </div>
            <div>
              <div className="lbl" style={{ marginBottom: "var(--sp-2)" }}>
                Monthly plan
              </div>
              {plans.length === 0 ? (
                <div className="banner">
                  <span className="t">No plans yet.</span>
                  <span>Create one in Plans, or add this car without billing for now.</span>
                </div>
              ) : (
                <div className="col g2">
                  {plans.map((p) => (
                    <button
                      key={p.id}
                      type="button"
                      className={`pm-row${planId === p.id ? " on" : ""}`}
                      style={{ width: "100%", textAlign: "left", border: 0, cursor: "pointer" }}
                      data-testid="ac-plan-option"
                      onClick={() => setPlanId(p.id)}
                    >
                      <span className="pm-sel" />
                      <div className="m">
                        <span className="t16 w7">{p.name}</span>
                        <span className="t14 c-ink2">{p.size_class}</span>
                      </div>
                      <span className="t16 w7">{formatCents(p.current_monthly_cents)} a month</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
            <div className="field">
              <label className="lbl" htmlFor="ac-sd">
                Start date
              </label>
              <input
                type="date"
                className="inp"
                id="ac-sd"
                value={startedOn}
                onChange={(e) => setStartedOn(e.target.value)}
              />
            </div>
            <div className="hint">
              The server calculates the plan price and the first invoice once the car is added.
            </div>
            {submitError && (
              <div className="hint err" role="alert">
                {submitError}
              </div>
            )}
          </div>
        )}

        {step === 4 && createdCar && (
          <div className="step-body">
            <div>
              <h3 className="t20 w7">
                {`${createdCar.color} ${createdCar.model}`} added for {residentLine}. The resident
                has been notified.
              </h3>
            </div>
            <div className="tile-flat col g1" style={{ padding: "var(--sp-4)" }}>
              <div className="kv">
                <span className="k">Plate</span>
                <span className="v">{createdCar.license_plate}</span>
              </div>
              <div className="kv">
                <span className="k">Plan</span>
                <span className="v">
                  {selectedPlan ? `${selectedPlan.name}, ${formatCents(selectedPlan.current_monthly_cents)} a month` : "No plan set"}
                </span>
              </div>
              <div className="kv">
                <span className="k">Starts</span>
                <span className="v">{formatDate(createdCar.started_on)}</span>
              </div>
            </div>
            <div className="t14 c-ink2">
              The resident sees this car in their app, and billing starts on the plan you chose.
            </div>
          </div>
        )}

        <div className="grow" />

        {step === 1 && (
          <div className="row g3">
            <button
              className="btn btn-primary grow"
              type="button"
              disabled={!selectedResidentId}
              data-testid="ac-step1-continue"
              onClick={() => setStep(2)}
            >
              {selectedResident ? `Continue with ${selectedResident.full_name}` : "Choose a resident"}
            </button>
            <button className="btn btn-quiet" type="button" onClick={onClose}>
              Cancel
            </button>
          </div>
        )}
        {step === 2 && (
          <div className="row g3">
            <button className="btn btn-secondary" type="button" onClick={() => setStep(1)}>
              Back
            </button>
            <button
              className="btn btn-primary grow"
              type="button"
              disabled={!plate || !make || !model || !color}
              data-testid="ac-step2-continue"
              onClick={() => setStep(3)}
            >
              Continue
            </button>
          </div>
        )}
        {step === 3 && (
          <div className="row g3">
            <button className="btn btn-secondary" type="button" onClick={() => setStep(2)}>
              Back
            </button>
            <button
              className="btn btn-primary grow"
              type="button"
              disabled={createCar.isPending}
              data-testid="ac-submit"
              onClick={() => createCar.mutate()}
            >
              Add car
            </button>
          </div>
        )}
        {step === 4 && (
          <div className="row g3">
            <button className="btn btn-primary grow" type="button" data-testid="ac-done" onClick={onClose}>
              Done
            </button>
            <button className="btn btn-secondary grow" type="button" onClick={resetForAnother}>
              Add another car
            </button>
          </div>
        )}
      </section>
    </>
  )
}
