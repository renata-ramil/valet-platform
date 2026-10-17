import { useEffect, useMemo, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import * as api from "../lib/apiClient"
import type { CarRequest } from "../lib/apiClient"
import { useAuth } from "../context/AuthContext"
import { useLiveRequests } from "../lib/useLiveRequests"
import { useClock } from "../lib/useClock"
import { formatTime, formatMonthYear, describeWeekdays, formatLocalTimeString } from "../lib/format"
import { TopbarHome, TopbarBack, Avatar } from "../components/PhoneFrame"
import { Scene } from "../components/Scene"
import { Icon } from "../components/Icon"
import { ResidentTabbar } from "../components/ResidentTabbar"
import type { ResidentTab } from "../components/ResidentTabbar"

const LAST_CAR_KEY = "valet.lastCarId"

type ReadyChoice = "asap" | "in10" | "attime"

// A request is still "mine to show" on Home while it is in flight. Delivered
// has no successor state in the backend (app/lifecycle.py's TRANSITIONS for
// delivered is empty, by design: there is no more resident-initiated step),
// so nothing in the API ever tells the client a delivered request stopped
// being current. Home treats a delivered request as current for a short
// grace window after its last event, then quietly returns to "Bring my car"
// on its own, matching the R07 design screen's copy. This window is a
// documented client side heuristic, not a backend signal.
const DELIVERED_GRACE_MS = 30 * 60 * 1000

const ONGOING_STATES = new Set(["scheduled", "queued", "assigned", "retrieving", "en_route"])

const STOPS: { key: string; label: string; states: string[] }[] = [
  { key: "called", label: "Called", states: ["scheduled", "queued", "assigned"] },
  { key: "retrieving", label: "Retrieving", states: ["retrieving"] },
  { key: "way", label: "On the way", states: ["en_route"] },
  { key: "delivered", label: "Delivered", states: ["delivered"] },
]

function stopIndexFor(state: string): number {
  const i = STOPS.findIndex((s) => s.states.includes(state))
  return i === -1 ? 0 : i
}

function statusColorClass(state: string): string {
  if (state === "delivered") return "c-done"
  if (state === "en_route") return "c-way"
  return "c-called"
}

function greeting(hour: number): string {
  if (hour < 12) return "Good morning"
  if (hour < 17) return "Good afternoon"
  return "Good evening"
}

function lastEventAt(request: CarRequest): string {
  return request.events.length > 0
    ? request.events[request.events.length - 1].created_at
    : request.created_at
}

function EVENT_LABEL(type: string): { title: string; sub: string } {
  switch (type) {
    case "created":
      return { title: "Called", sub: "Requested from the app" }
    case "queued":
      return { title: "Queued", sub: "Waiting for a valet" }
    case "assigned":
      return { title: "Assigned", sub: "A valet took the request" }
    case "retrieving":
      return { title: "Retrieved", sub: "On the way from the spot" }
    case "en_route":
      return { title: "On the way", sub: "Heading to the lobby" }
    case "delivered":
      return { title: "Delivered at the lobby", sub: "Waiting at the lobby door" }
    case "cancelled":
      return { title: "Cancelled", sub: "Request cancelled" }
    case "failed":
      return { title: "Could not complete", sub: "Something went wrong" }
    default:
      return { title: type, sub: "" }
  }
}

function RequestDetail({
  request,
  car,
  onBack,
  onNavigate,
}: {
  request: CarRequest
  car: api.Car | undefined
  onBack: () => void
  onNavigate: (tab: ResidentTab) => void
}) {
  const stopIndex = stopIndexFor(request.state)
  const isDelivered = request.state === "delivered"
  return (
    <>
      <TopbarBack title="Request detail" onBack={onBack} />
      <main className="pbody">
        <div className="col g4 py2">
          <section className="card col g3" aria-label="Request summary">
            <div className="col">
              <p className="t20 w7">
                {car ? `${car.color} ${car.make} ${car.model} ${car.license_plate}` : "Your car"}
              </p>
              <p className="t14 c-ink2">
                {new Date(request.created_at).toLocaleDateString([], {
                  weekday: "long",
                  month: "long",
                  day: "numeric",
                })}
              </p>
            </div>
            <p className={`stx ${statusColorClass(request.state)}`}>
              {isDelivered ? `Delivered ${formatTime(lastEventAt(request))}` : request.resident_label}
            </p>
            <p className="t16 c-ink2">
              {isDelivered
                ? `Ready by ${formatTime(request.ready_by)}, delivered ${formatTime(lastEventAt(request))}.`
                : `Ready by ${formatTime(request.ready_by)}${
                    request.eta_latest ? `, latest ${formatTime(request.eta_latest)}` : ""
                  }.`}
            </p>
            <ol className="pl" aria-label="Progress">
              {STOPS.map((s, i) => (
                <li key={s.key} className={i < stopIndex ? "done" : i === stopIndex ? "cur" : ""}>
                  {s.label}
                </li>
              ))}
            </ol>
          </section>

          <section aria-label="Custody timeline">
            <h2 className="t16 w7 py2">Custody</h2>
            <ol className="tl">
              {request.events.map((event, i) => {
                const { title, sub } = EVENT_LABEL(event.type)
                const isLast = i === request.events.length - 1
                return (
                  <li key={i} className={isLast ? "tl-i cur" : "tl-i done"}>
                    <span className="tl-t">{formatTime(event.created_at)}</span>
                    <span className="tl-dot" />
                    <div>
                      <p className="tl-w">{title}</p>
                      <p className="tl-s">{sub}</p>
                    </div>
                  </li>
                )
              })}
            </ol>
          </section>

          <button className="btn btn-quiet btn-block" type="button">
            Report a problem with this request
          </button>
        </div>
      </main>
      <ResidentTabbar active="home" onChange={onNavigate} />
    </>
  )
}

function SuggestionCard({ csrf }: { csrf: string }) {
  const queryClient = useQueryClient()
  const suggestionsQuery = useQuery({ queryKey: ["suggestions"], queryFn: api.getSuggestions })
  const carsQuery = useQuery({ queryKey: ["cars"], queryFn: api.listCars })
  const [dismissed, setDismissed] = useState<Set<number>>(new Set())

  const createSchedule = useMutation({
    mutationFn: async ({ index }: { index: number }) => {
      const suggestion = suggestionsQuery.data![index]
      const car = carsQuery.data?.[0]
      if (!car) throw new Error("no car on file")
      return api.createSchedule(csrf, {
        car_id: car.id,
        weekdays: suggestion.weekdays,
        ready_by_local_time: suggestion.ready_by_local_time,
        active_from: new Date().toISOString().slice(0, 10),
      })
    },
    onSuccess: (_result, { index }) => {
      queryClient.invalidateQueries({ queryKey: ["schedules"] })
      setDismissed((current) => new Set(current).add(index))
    },
  })

  const suggestions = (suggestionsQuery.data ?? []).filter((_, i) => !dismissed.has(i))
  if (suggestions.length === 0) return null
  const suggestion = suggestions[0]
  const index = (suggestionsQuery.data ?? []).indexOf(suggestion)

  return (
    <div className="card-tint col g3" data-testid="suggestion-card">
      <p className="t16">
        You usually call your car around {formatLocalTimeString(suggestion.ready_by_local_time)}{" "}
        on {describeWeekdays(suggestion.weekdays)}. Schedule it?
      </p>
      <div className="row g2">
        <button
          type="button"
          data-testid="accept-suggestion"
          className="btn btn-secondary grow"
          disabled={createSchedule.isPending}
          onClick={() => createSchedule.mutate({ index })}
        >
          Schedule it
        </button>
        <button
          type="button"
          data-testid="dismiss-suggestion"
          className="btn btn-quiet grow"
          onClick={() => setDismissed((current) => new Set(current).add(index))}
        >
          Not now
        </button>
      </div>
    </div>
  )
}

export function HomePage({
  onNavigate,
  onOpenAccount,
  onBookAhead,
}: {
  onNavigate: (tab: ResidentTab) => void
  onOpenAccount: () => void
  onBookAhead: () => void
}) {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const clock = useClock()
  const carsQuery = useQuery({ queryKey: ["cars"], queryFn: api.listCars })
  const requestsQuery = useQuery({ queryKey: ["requests"], queryFn: api.listRequests })
  const billingQuery = useQuery({ queryKey: ["billing", "summary"], queryFn: api.getBillingSummary })
  const [detailOpen, setDetailOpen] = useState(false)

  const [selectedCarId, setSelectedCarId] = useState<string>(
    () => localStorage.getItem(LAST_CAR_KEY) ?? "",
  )
  const [readyChoice, setReadyChoice] = useState<ReadyChoice>("asap")
  const [timeToday, setTimeToday] = useState("18:00")

  useEffect(() => {
    if (!carsQuery.data || carsQuery.data.length === 0) return
    const stillOwned = carsQuery.data.some((c) => c.id === selectedCarId)
    if (!stillOwned) {
      setSelectedCarId(carsQuery.data[0].id)
    }
  }, [carsQuery.data, selectedCarId])

  useEffect(() => {
    if (selectedCarId) localStorage.setItem(LAST_CAR_KEY, selectedCarId)
  }, [selectedCarId])

  useLiveRequests((updated) => {
    queryClient.setQueryData<CarRequest[]>(["requests"], (current) => {
      if (!current) return current
      const exists = current.some((r) => r.id === updated.id)
      return exists
        ? current.map((r) => (r.id === updated.id ? updated : r))
        : [updated, ...current]
    })
  }, Boolean(user))

  const bringCar = useMutation({
    mutationFn: async () => {
      if (!user) throw new Error("not logged in")
      let readyBy: string | undefined
      if (readyChoice === "in10") {
        readyBy = new Date(Date.now() + 10 * 60_000).toISOString()
      } else if (readyChoice === "attime") {
        const [hours, minutes] = timeToday.split(":").map(Number)
        const target = new Date()
        target.setHours(hours, minutes, 0, 0)
        if (target.getTime() < Date.now()) target.setDate(target.getDate() + 1)
        readyBy = target.toISOString()
      }
      return api.createRequest(user.csrf_token, { car_id: selectedCarId, ready_by: readyBy })
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["requests"] }),
  })

  const cancelRequest = useMutation({
    mutationFn: (requestId: string) => api.cancelRequest(user!.csrf_token, requestId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["requests"] }),
  })

  const activeRequest = useMemo(() => {
    const requests = requestsQuery.data ?? []
    const byNewest = (a: CarRequest, b: CarRequest) =>
      new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    const ongoing = requests.filter((r) => ONGOING_STATES.has(r.state)).sort(byNewest)[0]
    if (ongoing) return ongoing
    const delivered = requests.filter((r) => r.state === "delivered").sort(byNewest)[0]
    if (delivered && Date.now() - new Date(lastEventAt(delivered)).getTime() < DELIVERED_GRACE_MS) {
      return delivered
    }
    return undefined
  }, [requestsQuery.data])

  const activeCar = useMemo(
    () => (carsQuery.data ?? []).find((c) => c.id === activeRequest?.car_id),
    [carsQuery.data, activeRequest],
  )

  useEffect(() => {
    setDetailOpen(false)
  }, [activeRequest?.id])

  const cars = carsQuery.data ?? []
  const selectedCar = cars.find((c) => c.id === selectedCarId)

  // Payment status never blocks Bring my car: this quiet line is the only
  // thing a past due balance changes on Home (design screen R34)
  const pastDue =
    billingQuery.data &&
    billingQuery.data.amount_due_cents > 0 &&
    billingQuery.data.due_date !== null &&
    new Date(billingQuery.data.due_date) < new Date(new Date().toDateString())

  const avatar = user ? <Avatar name={user.full_name} onClick={onOpenAccount} /> : null

  if (detailOpen && activeRequest) {
    return (
      <RequestDetail
        request={activeRequest}
        car={activeCar}
        onBack={() => setDetailOpen(false)}
        onNavigate={onNavigate}
      />
    )
  }

  if (!activeRequest) {
    return (
      <>
        <TopbarHome
          right={
            <div className="row g3">
              <span className="t16 w5 c-ink2">Harbor Tower</span>
              {avatar}
            </div>
          }
        />
        <main className="pbody">
          <div className="col g4" style={{ height: "100%" }} data-testid="home-page">
            <h1 className="t28 w7">
              {greeting(new Date().getHours())}, {user?.full_name?.split(" ")[0]}
            </h1>

            {user && <SuggestionCard csrf={user.csrf_token} />}

            {cars.length > 1 && (
              <div className="col g2">
                <p className="lbl" id="cp-l">
                  Choose from your active cars
                </p>
                <div className="cp" role="group" aria-labelledby="cp-l">
                  {cars.map((car) => (
                    <button
                      key={car.id}
                      type="button"
                      data-testid="car-option"
                      className={`cp-i${car.id === selectedCarId ? " on" : ""}`}
                      aria-pressed={car.id === selectedCarId}
                      onClick={() => setSelectedCarId(car.id)}
                    >
                      <span className="cp-ic">
                        <Icon name="car" />
                      </span>
                      <span className="grow col">
                        <span className="w7">{car.nickname || `${car.color} ${car.model}`}</span>
                        <span className="t14 c-ink2">{car.license_plate}</span>
                      </span>
                      {car.id === selectedCarId && <Icon name="check" className="g cp-ck" />}
                    </button>
                  ))}
                </div>
              </div>
            )}

            <div className="col g2">
              <p className="lbl">Ready by</p>
              <div className="seg">
                <button
                  type="button"
                  className={`seg-i${readyChoice === "asap" ? " on" : ""}`}
                  aria-pressed={readyChoice === "asap"}
                  onClick={() => setReadyChoice("asap")}
                >
                  As soon as possible
                </button>
                <button
                  type="button"
                  className={`seg-i${readyChoice === "in10" ? " on" : ""}`}
                  aria-pressed={readyChoice === "in10"}
                  onClick={() => setReadyChoice("in10")}
                >
                  In 10 minutes
                </button>
                <button
                  type="button"
                  className={`seg-i${readyChoice === "attime" ? " on" : ""}`}
                  aria-pressed={readyChoice === "attime"}
                  onClick={() => setReadyChoice("attime")}
                >
                  At a time today
                </button>
              </div>
              {readyChoice === "attime" && (
                <input
                  type="time"
                  className="inp"
                  value={timeToday}
                  onChange={(e) => setTimeToday(e.target.value)}
                  data-testid="ready-time-input"
                />
              )}
            </div>

            <button
              type="button"
              className="btn btn-quiet btn-block"
              data-testid="book-ahead"
              onClick={onBookAhead}
            >
              Book ahead for later
            </button>

            <div className="col g2" style={{ marginTop: "auto" }}>
              <button
                type="button"
                className="btn btn-primary btn-xl"
                data-testid="bring-my-car"
                disabled={!selectedCarId || bringCar.isPending}
                onClick={() => bringCar.mutate()}
              >
                Bring my car
              </button>
              {cars.length === 1 && selectedCar ? (
                <>
                  <p className="t16 c-ink2 tc">
                    {selectedCar.nickname || `${selectedCar.color} ${selectedCar.model}`},{" "}
                    {selectedCar.license_plate}
                  </p>
                  <p className="hint tc">It will be at the lobby shortly after you ask.</p>
                </>
              ) : (
                <p className="hint tc">
                  {selectedCar
                    ? `Your ${selectedCar.nickname || `${selectedCar.color} ${selectedCar.make}`} will be at the lobby shortly after you ask.`
                    : "Your car will be at the lobby shortly after you ask."}
                </p>
              )}
              {pastDue && billingQuery.data?.due_date && (
                <button
                  type="button"
                  className="t16 c-ink2 tc"
                  data-testid="past-due-banner"
                  style={{
                    minHeight: 48,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    textWrap: "balance",
                    textDecoration: "underline",
                    textUnderlineOffset: 4,
                    background: "transparent",
                    border: 0,
                    width: "100%",
                  }}
                  onClick={() => onNavigate("billing")}
                >
                  {formatMonthYear(billingQuery.data.due_date)} payment needs attention. Go to Billing.
                </button>
              )}
            </div>
          </div>
        </main>
        <ResidentTabbar active="home" onChange={onNavigate} />
      </>
    )
  }

  const state = activeRequest.state
  const stopIndex = stopIndexFor(state)

  return (
    <>
      <TopbarHome
        right={
          <div className="row g3">
            <span className="t14 c-ink2">{clock}</span>
            {avatar}
          </div>
        }
      />
      <main className="pbody">
        <div className="col g4" style={{ height: "100%" }} data-testid="home-page">
          {state !== "delivered" && <Scene />}

          <button
            type="button"
            className="card col g1"
            style={{ textAlign: "left", cursor: "pointer" }}
            data-testid="status-card"
            onClick={() => setDetailOpen(true)}
          >
            <p className={`stx t28 w7 ${statusColorClass(state)}`} data-testid="status-label">
              {state === "en_route"
                ? `On the way, arriving by ${formatTime(activeRequest.ready_by)}`
                : state === "delivered"
                  ? `Delivered ${formatTime(lastEventAt(activeRequest))}`
                  : `Ready by ${formatTime(activeRequest.ready_by)}`}
            </p>
            <p className="t16 c-ink2">
              {state === "delivered"
                ? `${activeCar ? `${activeCar.nickname || activeCar.make} left ` : "Left "}at the lobby.`
                : `${activeRequest.eta_latest ? `Latest ${formatTime(activeRequest.eta_latest)} - ` : ""}Called at ${formatTime(activeRequest.created_at)}`}
            </p>
            <ol className="pl" style={{ marginTop: "var(--sp-4)" }}>
              {STOPS.map((s, i) => (
                <li key={s.key} className={i < stopIndex ? "done" : i === stopIndex ? "cur" : ""}>
                  {s.label}
                </li>
              ))}
            </ol>
          </button>

          {(state === "scheduled" || state === "queued" || state === "assigned") && activeCar && (
            <div className="card-hi col g1">
              <div className="row between">
                <p className="t20 w7">
                  {activeCar.color} {activeCar.make}
                </p>
                <p className="t16 w7">{activeCar.license_plate}</p>
              </div>
              <p className="t16 sub">Waiting for a valet to start</p>
              <p className="t16" style={{ marginTop: "var(--sp-2)" }}>
                We will have your car ready for the time you chose.
              </p>
            </div>
          )}

          {state === "retrieving" && activeCar && (
            <div className="card-hi col g1">
              <div className="row between">
                <p className="t20 w7">
                  {activeCar.color} {activeCar.make}
                </p>
                <p className="t16 w7">{activeCar.license_plate}</p>
              </div>
              <p className="t16" style={{ marginTop: "var(--sp-2)" }}>
                Your valet is retrieving your car now.
              </p>
            </div>
          )}

          {state === "en_route" && activeCar && (
            <div className="card-hi col g1">
              <div className="row between">
                <p className="t20 w7">
                  {activeCar.color} {activeCar.make}
                </p>
                <p className="t16 w7">{activeCar.license_plate}</p>
              </div>
              <p className="t16" style={{ marginTop: "var(--sp-2)" }}>
                Your car is on the way to the lobby.
              </p>
            </div>
          )}

          {state === "delivered" && (
            <section className="card col g1" aria-label="Where the car is">
              <div className="kv">
                <span className="k">Where</span>
                <span className="v">Harbor Tower lobby</span>
              </div>
              <div className="kv">
                <span className="k">Time</span>
                <span className="v">{formatTime(lastEventAt(activeRequest))}</span>
              </div>
            </section>
          )}

          {(state === "scheduled" || state === "queued" || state === "assigned" || state === "retrieving") && (
            <div className="col g2" style={{ marginTop: "auto" }}>
              <button className="btn btn-secondary btn-block" type="button" disabled>
                Change ready-by time
              </button>
              <button
                className="btn btn-quiet btn-block"
                type="button"
                data-testid="cancel-request"
                disabled={cancelRequest.isPending}
                onClick={() => cancelRequest.mutate(activeRequest.id)}
              >
                Cancel request
              </button>
            </div>
          )}

          {state === "en_route" && (
            <div className="col g2" style={{ marginTop: "auto" }}>
              <button className="btn btn-secondary btn-block" type="button">
                <Icon name="chat" />
                Message the valet desk
              </button>
            </div>
          )}

          {state === "delivered" && (
            <p className="t16 c-ink2" style={{ marginTop: "auto" }}>
              Nothing to confirm. Home goes back to Bring my car on its own.
            </p>
          )}
        </div>
      </main>
      <ResidentTabbar active="home" onChange={onNavigate} />
    </>
  )
}
