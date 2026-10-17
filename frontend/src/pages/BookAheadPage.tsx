import { useEffect, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import * as api from "../lib/apiClient"
import { ApiError } from "../lib/apiClient"
import { useAuth } from "../context/AuthContext"
import { Icon } from "../components/Icon"
import { TopbarBack } from "../components/PhoneFrame"
import { ResidentTabbar } from "../components/ResidentTabbar"
import { formatTime } from "../lib/format"
import { WheelColumn } from "./SchedulePage"

// Mirroring backend/app/settings.py's min_lead_minutes (10): the server is
// the real gate, this only disables the button early so the error never
// has to round trip
const MIN_LEAD_MINUTES = 10

type DayChoice = "today" | "tomorrow" | "pick"

const HOURS = Array.from({ length: 12 }, (_, i) => i + 1)
const MINUTES = Array.from({ length: 60 }, (_, i) => String(i).padStart(2, "0"))
const MERIDIEMS = ["AM", "PM"] as const

function toLocalIsoDate(date: Date): string {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, "0")
  const day = String(date.getDate()).padStart(2, "0")
  return `${year}-${month}-${day}`
}

function hour24From(hour: number, meridiem: (typeof MERIDIEMS)[number]): number {
  if (meridiem === "AM") return hour === 12 ? 0 : hour
  return hour === 12 ? 12 : hour + 12
}

// Building the chosen day and wheel time into one local Date
function buildReadyBy(
  dayChoice: DayChoice,
  pickedDate: string,
  hour: number,
  minute: string,
  meridiem: (typeof MERIDIEMS)[number],
): Date {
  const target = new Date()
  if (dayChoice === "tomorrow") {
    target.setDate(target.getDate() + 1)
  } else if (dayChoice === "pick" && pickedDate) {
    const [year, month, day] = pickedDate.split("-").map(Number)
    target.setFullYear(year, month - 1, day)
  }
  target.setHours(hour24From(hour, meridiem), Number(minute), 0, 0)
  return target
}

function dayPhrase(dayChoice: DayChoice, pickedDate: string): string {
  if (dayChoice === "today") return "today"
  if (dayChoice === "tomorrow") return "tomorrow"
  if (pickedDate) {
    const d = new Date(`${pickedDate}T00:00:00`)
    return `on ${d.toLocaleDateString([], { month: "long", day: "numeric" })}`
  }
  return ""
}

function requestStatusLine(request: api.CarRequest): { cls: string; text: string } {
  if (request.state === "scheduled") {
    return { cls: "c-sched", text: `Scheduled for ${formatTime(request.ready_by)}` }
  }
  return { cls: "c-called", text: `Ready by ${formatTime(request.ready_by)}` }
}

function stopIndexForState(state: string): number {
  if (state === "en_route") return 2
  if (state === "delivered") return 3
  if (state === "queued" || state === "assigned" || state === "retrieving") return 0
  return -1
}

function Confirmed({
  request,
  car,
  onDone,
  onChangeTime,
  onCancelled,
}: {
  request: api.CarRequest
  car: api.Car | undefined
  onDone: () => void
  onChangeTime: () => void
  onCancelled: () => void
}) {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const [error, setError] = useState<string | null>(null)
  const stopIndex = stopIndexForState(request.state)
  const status = requestStatusLine(request)

  const cancelMutation = useMutation({
    mutationFn: () => api.cancelRequest(user!.csrf_token, request.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["requests"] })
      onCancelled()
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : "Something went wrong"),
  })

  const changeTimeMutation = useMutation({
    mutationFn: () => api.cancelRequest(user!.csrf_token, request.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["requests"] })
      onChangeTime()
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : "Something went wrong"),
  })

  const callTime = new Date(new Date(request.ready_by).getTime() - 15 * 60_000)

  return (
    <>
      <header className="topbar">
        <div className="ibtn" aria-hidden="true" />
        <h1 className="ttl">Book ahead</h1>
        <div className="ibtn" aria-hidden="true" />
      </header>
      <main className="pbody">
        <div className="col g4 py2">
          <div className="toast" role="status">
            <Icon name="check" />
            <span>Booked</span>
          </div>

          <section className="card col g4" aria-label="Booking">
            <p className={`stx ${status.cls}`}>{status.text}</p>
            <ol className="pl" aria-label="Progress">
              <li className={stopIndex === 0 ? "cur" : stopIndex > 0 ? "done" : ""}>Called</li>
              <li className={stopIndex === 1 ? "cur" : stopIndex > 1 ? "done" : ""}>Retrieving</li>
              <li className={stopIndex === 2 ? "cur" : stopIndex > 2 ? "done" : ""}>On the way</li>
              <li className={stopIndex === 3 ? "done" : ""}>Delivered</li>
            </ol>
            <div className="col">
              <div className="kv">
                <span className="k">Car</span>
                <span className="v">
                  {car ? `${car.color} ${car.model} ${car.license_plate}` : "Your car"}
                </span>
              </div>
              <div className="kv">
                <span className="k">Ready by</span>
                <span className="v">{formatTime(request.ready_by)}</span>
              </div>
              <div className="kv">
                <span className="k">Latest</span>
                <span className="v">{request.eta_latest ? formatTime(request.eta_latest) : "-"}</span>
              </div>
              <div className="kv">
                <span className="k">Pickup</span>
                <span className="v">Lobby</span>
              </div>
            </div>
          </section>

          <p className="t16 c-ink2">
            We will call your car at {formatTime(callTime.toISOString())} so it is ready by{" "}
            {formatTime(request.ready_by)}.
          </p>

          {error && (
            <p className="hint err" data-testid="book-ahead-error">
              {error}
            </p>
          )}

          <div className="col g2">
            <button className="btn btn-primary btn-xl" type="button" onClick={onDone}>
              Done
            </button>
            <button
              className="btn btn-secondary btn-block"
              type="button"
              disabled={changeTimeMutation.isPending}
              onClick={() => changeTimeMutation.mutate()}
            >
              Change time
            </button>
            <button
              className="btn btn-quiet btn-block"
              type="button"
              disabled={cancelMutation.isPending}
              onClick={() => cancelMutation.mutate()}
            >
              Cancel booking
            </button>
          </div>
        </div>
      </main>
      <ResidentTabbar active="home" onChange={onDone} />
    </>
  )
}

export function BookAheadPage({ onBack }: { onBack: () => void }) {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const carsQuery = useQuery({ queryKey: ["cars"], queryFn: api.listCars })
  const cars = carsQuery.data ?? []

  const [dayChoice, setDayChoice] = useState<DayChoice>("today")
  const [pickedDate, setPickedDate] = useState("")
  const [hour, setHour] = useState(7)
  const [minute, setMinute] = useState("00")
  const [meridiem, setMeridiem] = useState<(typeof MERIDIEMS)[number]>("PM")
  const [carId, setCarId] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [booked, setBooked] = useState<api.CarRequest | null>(null)

  useEffect(() => {
    if (!carId && cars.length > 0) setCarId(cars[0].id)
  }, [cars, carId])

  const readyBy = buildReadyBy(dayChoice, pickedDate, hour, minute, meridiem)
  const leadOk = readyBy.getTime() - Date.now() >= MIN_LEAD_MINUTES * 60_000
  const datePending = dayChoice === "pick" && !pickedDate
  const timeLabel = `${hour}:${minute} ${meridiem}`

  const createBooking = useMutation({
    mutationFn: () =>
      api.createRequest(user!.csrf_token, { car_id: carId, ready_by: readyBy.toISOString() }),
    onSuccess: (request) => {
      queryClient.invalidateQueries({ queryKey: ["requests"] })
      setBooked(request)
      setError(null)
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : "Something went wrong"),
  })

  if (booked) {
    return (
      <Confirmed
        request={booked}
        car={cars.find((c) => c.id === booked.car_id)}
        onDone={onBack}
        onChangeTime={() => setBooked(null)}
        onCancelled={onBack}
      />
    )
  }

  // A simple client side estimate for the live preview, shown before the
  // request exists: the real eta comes back from the server once booked
  // (see Confirmed above), this is only a few minutes of buffer so the
  // preview has a latest time to show
  const previewLatest = new Date(readyBy.getTime() + 4 * 60_000)

  return (
    <>
      <TopbarBack title="Book ahead" onBack={onBack} />
      <main className="pbody">
        <div className="col g4 py2">
          <h2 className="t28 w7">When do you need it?</h2>

          <div className="seg" role="group" aria-label="Day">
            <button
              type="button"
              className={`seg-i${dayChoice === "today" ? " on" : ""}`}
              aria-pressed={dayChoice === "today"}
              onClick={() => setDayChoice("today")}
            >
              Today
            </button>
            <button
              type="button"
              className={`seg-i${dayChoice === "tomorrow" ? " on" : ""}`}
              aria-pressed={dayChoice === "tomorrow"}
              onClick={() => setDayChoice("tomorrow")}
            >
              Tomorrow
            </button>
            <button
              type="button"
              className={`seg-i${dayChoice === "pick" ? " on" : ""}`}
              aria-pressed={dayChoice === "pick"}
              onClick={() => setDayChoice("pick")}
            >
              Pick a date
            </button>
          </div>

          {dayChoice === "pick" && (
            <input
              type="date"
              className="inp"
              aria-label="Date"
              data-testid="book-ahead-date-input"
              min={toLocalIsoDate(new Date())}
              value={pickedDate}
              onChange={(e) => setPickedDate(e.target.value)}
            />
          )}

          <div className="tp" role="group" aria-label="Time">
            <WheelColumn options={HOURS} value={hour} onChange={setHour} label="Hour" />
            <WheelColumn options={MINUTES} value={minute} onChange={setMinute} label="Minute" />
            <WheelColumn options={MERIDIEMS} value={meridiem} onChange={setMeridiem} label="AM or PM" />
          </div>

          <div className="cp" role="group" aria-label="Car">
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
                  <span className="w7">{c.color} {c.model}</span>
                  <span className="t14 c-ink2">{c.license_plate}</span>
                </span>
                {carId === c.id && <Icon name="check" className="g cp-ck" />}
              </button>
            ))}
          </div>

          <section className="card-flat col g1" aria-live="polite">
            <p className="t28 w7">
              Ready by {timeLabel} {dayPhrase(dayChoice, pickedDate)}
            </p>
            <p className="t14 c-ink2">Latest {formatTime(previewLatest.toISOString())}</p>
          </section>

          {!leadOk && !datePending && (
            <p className="hint err" data-testid="book-ahead-lead-hint">
              Pick a time at least {MIN_LEAD_MINUTES} minutes from now.
            </p>
          )}
          {error && (
            <p className="hint err" data-testid="book-ahead-error">
              {error}
            </p>
          )}

          <button
            className="btn btn-primary btn-xl"
            type="button"
            disabled={!carId || datePending || !leadOk || createBooking.isPending}
            onClick={() => createBooking.mutate()}
          >
            Book for {timeLabel}
          </button>
        </div>
      </main>
      <ResidentTabbar active="home" onChange={onBack} />
    </>
  )
}
