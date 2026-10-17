import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import * as api from "../lib/apiClient"
import { useAuth } from "../context/AuthContext"
import { Icon } from "../components/Icon"
import { TopbarBack } from "../components/PhoneFrame"
import { ApiError } from "../lib/apiClient"
import { formatCents } from "../lib/format"

function formatStarted(iso: string): string {
  return new Date(iso).toLocaleDateString([], { month: "short", day: "numeric" })
}

function CarRow({ car, planName, monthlyCents }: { car: api.Car; planName: string | null; monthlyCents: number | null }) {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [nickname, setNickname] = useState(car.nickname ?? "")

  const save = useMutation({
    mutationFn: () => api.updateCarNickname(user!.csrf_token, car.id, nickname),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["cars"] })
      setEditing(false)
    },
  })

  const title = car.nickname || `${car.color} ${car.make} ${car.model}`

  return (
    <div className="car-row" style={{ minHeight: 96, alignItems: "flex-start", padding: "var(--sp-3) 0" }}>
      <span className="cp-ic">
        <Icon name="car" />
      </span>
      <span className="m g1">
        {editing ? (
          <>
            <label className="lbl" htmlFor={`nick-${car.id}`}>
              Nickname
            </label>
            <span className="row g2">
              <input
                id={`nick-${car.id}`}
                className="inp foc grow"
                value={nickname}
                onChange={(e) => setNickname(e.target.value)}
                aria-label={`Nickname for car ${car.license_plate}`}
              />
              <button
                className="btn btn-quiet"
                type="button"
                disabled={save.isPending}
                onClick={() => save.mutate()}
              >
                Save
              </button>
            </span>
          </>
        ) : (
          <span className="t20 w7">{title}</span>
        )}
        <span className="t16 w5">{car.license_plate}</span>
        <span className="t16">
          {planName ? (
            <>
              {planName} plan, <b>{monthlyCents !== null ? formatCents(monthlyCents) : "--"}</b> a month,
              started {formatStarted(car.started_on)}
            </>
          ) : (
            "No plan yet"
          )}
        </span>
        {!editing && (
          <span className="row">
            <button className="btn btn-quiet r14b" type="button" onClick={() => setEditing(true)}>
              Edit nickname
            </button>
          </span>
        )}
      </span>
    </div>
  )
}

function CarChangeSheet({ cars, onClose }: { cars: api.Car[]; onClose: () => void }) {
  const { user } = useAuth()
  const [action, setAction] = useState<api.CarRequestAction>("add")
  const [carId, setCarId] = useState(cars[0]?.id ?? "")
  const [plate, setPlate] = useState("")
  const [make, setMake] = useState("")
  const [model, setModel] = useState("")
  const [color, setColor] = useState("")
  const [note, setNote] = useState("")
  const [sent, setSent] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const existingCar = cars.find((c) => c.id === carId)

  const send = useMutation({
    mutationFn: () =>
      api.submitCarRequest(user!.csrf_token, {
        action,
        car_id: action !== "add" ? carId || null : null,
        plate: action === "add" ? plate : existingCar?.license_plate ?? null,
        make: action === "add" ? make : existingCar?.make ?? make,
        model: action === "add" ? model : existingCar?.model ?? model,
        color: action === "add" ? color : existingCar?.color ?? color,
        note: note || null,
      }),
    onSuccess: () => setSent(true),
    onError: (err: unknown) =>
      setError(err instanceof ApiError ? err.message : "Could not send the request"),
  })

  if (sent) {
    return (
      <>
        <header className="topbar">
          <div className="ibtn" aria-hidden="true" />
          <h1 className="ttl">Request sent</h1>
          <div className="ibtn" aria-hidden="true" />
        </header>
        <main className="pbody-full col g4 py2" data-testid="car-change-sent">
          <p className="t20 w7">The front desk has your request</p>
          <p className="t16 c-ink2">
            They will make the change and reply to you from a ticket in Help.
          </p>
          <button className="btn btn-primary btn-xl" type="button" onClick={onClose}>
            Done
          </button>
        </main>
      </>
    )
  }

  return (
    <>
      <header className="topbar">
        <button className="btn btn-quiet ibtn" type="button" aria-label="Back" onClick={onClose}>
          <Icon name="arrow" rotate={180} />
        </button>
        <h1 className="ttl">Request a car change</h1>
        <div className="ibtn" aria-hidden="true" />
      </header>
      <main className="pbody-full">
        <div className="col g4 py2">
          <p className="t16 c-ink2">The front desk makes the change and replies to you.</p>

          <div className="col g2">
            <span className="lbl" id="l-what">
              What would you like to do
            </span>
            <div className="seg" role="radiogroup" aria-labelledby="l-what">
              {(["add", "remove", "change"] as const).map((a) => (
                <button
                  key={a}
                  type="button"
                  className={`seg-i${action === a ? " on" : ""}`}
                  role="radio"
                  aria-checked={action === a}
                  onClick={() => setAction(a)}
                >
                  {a === "add" ? "Add" : a === "remove" ? "Remove" : "Change"}
                </button>
              ))}
            </div>
          </div>

          {action !== "add" && (
            <div className="col g2">
              <span className="lbl" id="l-car">
                Which car
              </span>
              <div className="cp" role="group" aria-labelledby="l-car">
                {cars.map((c) => (
                  <button
                    key={c.id}
                    type="button"
                    className={`cp-i${carId === c.id ? " on" : ""}`}
                    aria-pressed={carId === c.id}
                    onClick={() => setCarId(c.id)}
                  >
                    <span className="cp-ic">
                      <Icon name="car" />
                    </span>
                    <span className="grow col">
                      <span className="w7">
                        {c.color} {c.model}
                      </span>
                      <span className="t14 c-ink2">{c.license_plate}</span>
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {action === "add" && (
            <div className="field">
              <label className="lbl" htmlFor="plate">
                Plate
              </label>
              <input className="inp" id="plate" value={plate} onChange={(e) => setPlate(e.target.value.toUpperCase())} />
            </div>
          )}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--sp-3)" }}>
            <div className="field">
              <label className="lbl" htmlFor="make">
                Make
              </label>
              <input className="inp" id="make" value={make} onChange={(e) => setMake(e.target.value)} />
            </div>
            <div className="field">
              <label className="lbl" htmlFor="model">
                Model
              </label>
              <input className="inp" id="model" value={model} onChange={(e) => setModel(e.target.value)} />
            </div>
          </div>
          <div className="field">
            <label className="lbl" htmlFor="color">
              Color
            </label>
            <input className="inp" id="color" value={color} onChange={(e) => setColor(e.target.value)} />
          </div>
          <div className="field">
            <label className="lbl" htmlFor="note">
              Note
            </label>
            <input
              className="inp"
              id="note"
              placeholder="Anything the front desk should know"
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </div>
          {error && <p className="hint err">{error}</p>}
        </div>
      </main>
      <div className="pin">
        <button
          className="btn btn-primary btn-xl"
          type="button"
          disabled={send.isPending}
          onClick={() => send.mutate()}
        >
          Send request
        </button>
      </div>
    </>
  )
}

// Residents can only read their cars and edit the nickname: every other car
// action (plate, make, model, plan, ending it) is a manager action, so this
// page has no add or delete path, only a request the front desk acts on
export function CarsPage({ onBack }: { onBack: () => void }) {
  const carsQuery = useQuery({ queryKey: ["cars"], queryFn: api.listCars })
  const summaryQuery = useQuery({ queryKey: ["billing", "summary"], queryFn: api.getBillingSummary })
  const [requestingChange, setRequestingChange] = useState(false)

  const cars = carsQuery.data ?? []
  const billingByCarId = Object.fromEntries((summaryQuery.data?.cars ?? []).map((c) => [c.car_id, c]))

  if (requestingChange) {
    return <CarChangeSheet cars={cars} onClose={() => setRequestingChange(false)} />
  }

  return (
    <>
      <TopbarBack title="Cars" onBack={onBack} />
      <main className="pbody">
        <div className="col g4 py2" data-testid="cars-page">
          <section className="col" aria-label="Cars">
            {cars.map((car) => (
              <CarRow
                key={car.id}
                car={car}
                planName={billingByCarId[car.id]?.plan_name ?? null}
                monthlyCents={billingByCarId[car.id]?.monthly_cents ?? null}
              />
            ))}
          </section>
          <p className="t16 c-ink2">
            Your building adds and ends cars and sets each plan. You can rename a car here.
          </p>
          <button
            className="btn btn-secondary btn-block r14ask"
            type="button"
            data-testid="request-car-change"
            onClick={() => setRequestingChange(true)}
          >
            Ask the front desk to add or change a car
          </button>
        </div>
      </main>
    </>
  )
}
