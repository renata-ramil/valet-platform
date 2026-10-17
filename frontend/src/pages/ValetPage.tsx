import { Fragment, useEffect, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import * as api from "../lib/apiClient"
import type { ValetQueueItem, CarSearchResult } from "../lib/apiClient"
import { useAuth } from "../context/AuthContext"
import { useLiveBuildingEvents } from "../lib/useLiveRequests"
import { TopbarBack } from "../components/PhoneFrame"
import { Icon } from "../components/Icon"
import type { ThemeName } from "../lib/useTheme"

// Retrieve and deliver tasks ride on the request's own state machine; a park
// task (from Car arrived) has no request-state counterpart and is completed
// directly through POST /valet/tasks/{id}/complete-park instead
const NEXT_TRANSITION: Record<string, string> = {
  queued: "assigned",
  assigned: "retrieving",
  retrieving: "en_route",
  en_route: "delivered",
}

const START_LABEL: Record<string, string> = {
  retrieve: "Start retrieving",
  deliver: "Start delivery",
  restage: "Start restage",
  park: "Start parking",
}

const TYPE_LABEL: Record<string, string> = {
  retrieve: "Retrieve",
  deliver: "Deliver",
  restage: "Restage",
  park: "Park",
}

function laneLabel(item: ValetQueueItem): string {
  if (item.lane === null) return "Staging bay"
  return `Lane ${item.lane}, depth ${item.depth}`
}

function deadlineLabel(minutes: number): string {
  const rounded = Math.round(minutes)
  return rounded < 0 ? `Late by ${Math.abs(rounded)} min` : `${rounded} min`
}

// Formatting every clock time the same way (due times, the new-tag stamp,
// the lane map target cell and the live "now" subtitle) so they read as
// tabular, matching hour:minute figures throughout the queue
function formatClock(iso: string | Date): string {
  const date = typeof iso === "string" ? new Date(iso) : iso
  return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
}

// Labeling the queue card's action button by what pressing it actually does
// next, not just the task's original type: a "deliver" task's button reads
// "Mark delivered" once the car is en route, matching the custody chain's
// real steps (key taken, car retrieved, delivered at the lobby)
function actionLabel(item: ValetQueueItem): string {
  if (item.task.type === "park") return "Start parking"
  const state = item.request.state
  if (state === "retrieving") return "Mark picked up"
  if (state === "en_route") return "Mark delivered"
  return START_LABEL[item.task.type] ?? "Start"
}

function isRecentlyAdded(item: ValetQueueItem): boolean {
  if (item.task.type !== "park") return false
  const addedAt = new Date(item.task.planned_start_at).getTime()
  return Date.now() - addedAt < 10 * 60 * 1000
}

function TaskDetail({
  item,
  onBack,
  onStart,
  pending,
}: {
  item: ValetQueueItem
  onBack: () => void
  onStart: () => void
  pending: boolean
}) {
  const lane = item.lane ?? 0
  const depth = item.depth ?? 0
  const lanes = [lane - 2, lane - 1, lane, lane + 1, lane + 2].filter((l) => l >= 1)
  // Showing the full stack down to the aisle, like the design's D1 to D4
  // example, capped at 4 rows so a deep lane still fits a readable grid
  const depths: number[] = []
  for (let d = depth + 1; d >= Math.max(depth - 2, 1); d--) depths.push(d)
  if (depths.length === 0) depths.push(1)
  const dueAt = formatClock(item.task.planned_start_at)

  return (
    <>
      <TopbarBack title={TYPE_LABEL[item.task.type] ?? "Task"} onBack={onBack} />
      <main className="pbody col g4">
        <div className="col g1">
          <h1 className="t28 w7">
            {item.car.color} {item.car.make}
          </h1>
          <p className="t20 w7">{item.car.license_plate}</p>
          <p className="t20 w7">
            Due {dueAt}, {deadlineLabel(item.minutes_to_deadline)} left
          </p>
          <p className="t20 w7">{laneLabel(item)}</p>
        </div>

        {item.lane !== null && (
          <div className="col g2">
            <div
              className="mp"
              role="img"
              aria-label={`Lane map near lane ${item.lane}, depths 1 to ${depths[0]}. Target ${item.car.color} ${item.car.make} in lane ${item.lane} depth ${depth}, due ${dueAt}.`}
            >
              <div className="mh" />
              {lanes.map((l) => (
                <div className="mh" key={l}>
                  L{l}
                </div>
              ))}
              {depths.map((d) => (
                <Fragment key={d}>
                  <div className="ml">D{d}</div>
                  {lanes.map((l) => (
                    <div
                      key={`${l}-${d}`}
                      className={`gm-c${l === lane && d === depth ? " tgt" : " car"}`}
                    >
                      {l === lane && d === depth ? dueAt : ""}
                    </div>
                  ))}
                </Fragment>
              ))}
            </div>
            <p className="t14 c-ink2">L is lane, D is depth. D1 is nearest the aisle.</p>
          </div>
        )}

        <div className="col g2" style={{ marginTop: "auto" }}>
          <button
            type="button"
            className="btn btn-primary btn-xl"
            disabled={pending}
            onClick={onStart}
          >
            {actionLabel(item)}
          </button>
          <button type="button" className="btn btn-quiet btn-block">
            Report a problem
          </button>
        </div>
      </main>
    </>
  )
}

function CarArrivedFlow({
  onBack,
  onParkTaskCreated,
}: {
  onBack: () => void
  onParkTaskCreated: () => void
}) {
  const { user } = useAuth()
  const [plate, setPlate] = useState("")
  const [selected, setSelected] = useState<CarSearchResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  const searchQuery = useQuery({
    queryKey: ["valet-car-search", plate],
    queryFn: () => api.searchValetCars(plate),
    enabled: plate.length > 0,
  })

  const createPark = useMutation({
    mutationFn: (carId: string) => api.carArrived(user!.csrf_token, carId),
    onSuccess: () => onParkTaskCreated(),
    onError: (err: unknown) =>
      setError(err instanceof api.ApiError ? err.message : "Could not create the park task"),
  })

  const results = searchQuery.data ?? []

  if (selected) {
    return (
      <>
        <header className="topbar">
          <button
            className="btn btn-quiet ibtn"
            type="button"
            aria-label="Back"
            onClick={() => setSelected(null)}
          >
            <Icon name="arrow" rotate={180} />
          </button>
          <div className="ttl">Car arrived</div>
          <div className="none" style={{ width: 48 }} />
        </header>
        <main className="pbody col g4">
          <div className="col g1">
            <h1 className="t28 w7">Which car arrived?</h1>
            <p className="t14 c-ink2">Active cars at Harbor Tower. Ended cars do not appear.</p>
          </div>
          <div className="field srch">
            <label className="lbl" htmlFor="plate-match">
              Plate, name or unit
            </label>
            <input className="inp is-focus" id="plate-match" value={plate} readOnly />
          </div>
          <div className="col g2">
            <p className="hint">1 active car matches {plate}</p>
            <button className="plt-row on" type="button" aria-pressed="true">
              <span className="m">
                <span className="t20 w7">{selected.license_plate}</span>
                <span className="pl-s">
                  {selected.color} {selected.make} {selected.model}, {selected.owner_name}
                </span>
              </span>
            </button>
          </div>
          {error && <p className="hint err">{error}</p>}
          <div className="col g2" style={{ marginTop: "auto" }}>
            <button
              className="btn btn-primary btn-xl"
              type="button"
              disabled={createPark.isPending}
              data-testid="create-park-task"
              onClick={() => createPark.mutate(selected.id)}
            >
              Create Park task
            </button>
            <button className="btn btn-quiet btn-block" type="button" onClick={() => setSelected(null)}>
              Pick a different car
            </button>
          </div>
        </main>
      </>
    )
  }

  return (
    <>
      <header className="topbar">
        <button className="btn btn-quiet ibtn" type="button" aria-label="Back" onClick={onBack}>
          <Icon name="arrow" rotate={180} />
        </button>
        <div className="ttl">Car arrived</div>
        <div className="none" style={{ width: 48 }} />
      </header>
      <main className="pbody col g4">
        <div className="col g1">
          <h1 className="t28 w7">Which car arrived?</h1>
          <p className="t14 c-ink2">Active cars at Harbor Tower. Ended cars do not appear.</p>
        </div>
        <div className="field srch">
          <label className="lbl" htmlFor="plate">
            Plate, name or unit
          </label>
          <input
            className="inp is-focus"
            id="plate"
            data-testid="car-arrived-search"
            value={plate}
            autoFocus
            autoComplete="off"
            autoCapitalize="characters"
            onChange={(e) => setPlate(e.target.value.toUpperCase())}
          />
        </div>

        {plate.length === 0 ? null : results.length > 0 ? (
          <div className="col g2">
            <p className="hint">
              {results.length} active car{results.length === 1 ? "" : "s"} match {plate}
            </p>
            {results.map((car) => (
              <button
                key={car.id}
                className="plt-row"
                type="button"
                data-testid="car-arrived-result"
                onClick={() => setSelected(car)}
              >
                <span className="m">
                  <span className="t20 w7">{car.license_plate}</span>
                  <span className="pl-s">
                    {car.color} {car.make} {car.model}, {car.owner_name}
                  </span>
                </span>
              </button>
            ))}
          </div>
        ) : (
          <>
            <p className="hint err">0 active cars match {plate}</p>
            <div className="empty" data-testid="car-arrived-no-match">
              <p className="t20 w7">No active car matches {plate}</p>
              <p className="t16 c-ink2">
                Check the plate on the car. Visitor cars and cars whose plan has ended are not in this
                list, so the front desk has to confirm them.
              </p>
              <button className="btn btn-secondary btn-block" type="button" onClick={() => setPlate("")}>
                Clear search
              </button>
              <button className="btn btn-quiet btn-block" type="button" onClick={onBack}>
                Ask the front desk
              </button>
            </div>
          </>
        )}
      </main>
    </>
  )
}

export function ValetPage({
  theme,
  onToggleTheme,
}: {
  theme: ThemeName
  onToggleTheme: () => void
}) {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const queueQuery = useQuery({ queryKey: ["valet-queue"], queryFn: api.getValetQueue })
  const [openTaskId, setOpenTaskId] = useState<string | null>(null)
  const [arrivedOpen, setArrivedOpen] = useState(false)
  const [tab, setTab] = useState<"queue" | "garage" | "shift">("queue")
  const [now, setNow] = useState(() => new Date())

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 30000)
    return () => clearInterval(id)
  }, [])

  useLiveBuildingEvents(() => {
    queryClient.invalidateQueries({ queryKey: ["valet-queue"] })
  }, Boolean(user))

  const transition = useMutation({
    mutationFn: ({ requestId, target }: { requestId: string; target: string }) =>
      api.transitionRequest(user!.csrf_token, requestId, target),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["valet-queue"] }),
  })

  const completePark = useMutation({
    mutationFn: (taskId: string) => api.completeParkTask(user!.csrf_token, taskId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["valet-queue"] }),
  })

  const items = queueQuery.data ?? []
  const openTask = items.find((i) => i.task.id === openTaskId)

  // Queue stays the active tab under its own drill-down screens (task
  // detail, car arrived), matching the design's tabbar staying on Queue
  // throughout V02, V06, V07, V08 and V09, the same way a native tab bar
  // keeps its tab lit while a screen is pushed on top of it
  const tabBar = (
    <nav className="tabbar" aria-label="Valet">
      <button
        type="button"
        className={`tab${tab === "queue" ? " on" : ""}`}
        aria-current={tab === "queue" ? "page" : undefined}
        data-testid="tab-queue"
        onClick={() => setTab("queue")}
      >
        Queue
      </button>
      <button
        type="button"
        className={`tab${tab === "garage" ? " on" : ""}`}
        aria-current={tab === "garage" ? "page" : undefined}
        data-testid="tab-garage"
        onClick={() => setTab("garage")}
      >
        Garage
      </button>
      <button
        type="button"
        className={`tab${tab === "shift" ? " on" : ""}`}
        aria-current={tab === "shift" ? "page" : undefined}
        data-testid="tab-shift"
        onClick={() => setTab("shift")}
      >
        Shift
      </button>
    </nav>
  )

  if (tab === "shift") {
    return (
      <>
        <header className="topbar">
          <div className="col none">
            <span className="wm" />
            <span className="t14 c-ink2">Harbor Tower</span>
          </div>
          <div className="t14 c-ink2 grow tr-r">{user?.full_name}</div>
        </header>
        <main className="pbody col g4" data-testid="shift-page">
          <div className="col g1">
            <h1 className="t28 w7">{user?.full_name}</h1>
            <p className="t14 c-ink2">Signed in at Harbor Tower</p>
          </div>
          <section className="col g2" aria-label="Appearance">
            <h2 className="t14 w7 c-ink2">Appearance</h2>
            <div className="row between g3" style={{ minHeight: 48 }}>
              <span className="t16 grow">Dark mode</span>
              <button
                type="button"
                className={`tgl${theme === "th-d" ? " on" : ""}`}
                role="switch"
                aria-checked={theme === "th-d"}
                aria-label="Dark mode"
                data-testid="dark-mode-toggle"
                onClick={onToggleTheme}
              />
            </div>
          </section>
        </main>
        {tabBar}
      </>
    )
  }

  if (tab === "garage") {
    return (
      <>
        <header className="topbar">
          <div className="col none">
            <span className="wm" />
            <span className="t14 c-ink2">Harbor Tower</span>
          </div>
        </header>
        <main className="pbody col g3" data-testid="garage-page">
          <div className="col g1">
            <h1 className="t28 w7">Garage</h1>
            <p className="t14 c-ink2">The garage map is coming soon.</p>
          </div>
        </main>
        {tabBar}
      </>
    )
  }

  if (arrivedOpen) {
    return (
      <>
        <CarArrivedFlow
          onBack={() => setArrivedOpen(false)}
          onParkTaskCreated={() => {
            queryClient.invalidateQueries({ queryKey: ["valet-queue"] })
            setArrivedOpen(false)
          }}
        />
        {tabBar}
      </>
    )
  }

  if (openTask) {
    const nextTarget = NEXT_TRANSITION[openTask.request.state]
    return (
      <>
        <TaskDetail
          item={openTask}
          onBack={() => setOpenTaskId(null)}
          pending={transition.isPending || completePark.isPending}
          onStart={() => {
            setOpenTaskId(null)
            if (openTask.task.type === "park") {
              completePark.mutate(openTask.task.id)
            } else if (nextTarget) {
              transition.mutate({ requestId: openTask.request.id, target: nextTarget })
            }
          }}
        />
        {tabBar}
      </>
    )
  }

  return (
    <>
      <header className="topbar">
        <div className="col none">
          <span className="wm" />
          <span className="t14 c-ink2">Harbor Tower</span>
        </div>
        <div className="t14 c-ink2 grow tr-r">{user?.full_name}</div>
      </header>
      <main className="pbody col g3" data-testid="valet-page">
        <div className="col g1">
          <h1 className="t28 w7">{items.length} tasks</h1>
          <p className="t14 c-ink2">Sorted by deadline, now {formatClock(now)}</p>
        </div>

        <button
          className="btn btn-secondary btn-block"
          type="button"
          style={{ minHeight: 64 }}
          data-testid="car-arrived-button"
          onClick={() => setArrivedOpen(true)}
        >
          <Icon name="plus" />
          Car arrived
        </button>

        <div className="queue">
          {items.map((item) => {
            const overdue = item.minutes_to_deadline < 0
            const nextTarget = item.task.type === "park" ? "complete" : NEXT_TRANSITION[item.request.state]
            return (
              <article className={`task${overdue ? " late" : ""}`} key={item.task.id} data-testid="queue-card">
                <button
                  type="button"
                  className="row between g3"
                  style={{ background: "transparent", border: 0, cursor: "pointer", width: "100%", textAlign: "left", padding: 0 }}
                  onClick={() => setOpenTaskId(item.task.id)}
                >
                  <span className="tk-type">{TYPE_LABEL[item.task.type] ?? item.task.type}</span>
                  {isRecentlyAdded(item) && (
                    <span className="new-tag">New, added {formatClock(item.task.planned_start_at)}</span>
                  )}
                  <span className="tk-min" data-testid="deadline-minutes">
                    {deadlineLabel(item.minutes_to_deadline)}
                  </span>
                </button>
                <div className="row between g3">
                  <span className="t16">
                    {item.car.color} {item.car.make} <span className="w7">{item.car.license_plate}</span>
                  </span>
                  <span className="t14 c-ink2">Due {formatClock(item.task.planned_start_at)}</span>
                </div>
                <div className="row between g3">
                  <span className="tk-lane grow">{laneLabel(item)}</span>
                  {nextTarget ? (
                    <button
                      type="button"
                      data-testid="advance-button"
                      className={`btn ${overdue ? "btn-primary" : "btn-secondary"} none`}
                      style={{ minHeight: 64, minWidth: 144 }}
                      disabled={transition.isPending || completePark.isPending}
                      onClick={() =>
                        item.task.type === "park"
                          ? completePark.mutate(item.task.id)
                          : transition.mutate({ requestId: item.request.id, target: nextTarget })
                      }
                    >
                      {actionLabel(item)}
                    </button>
                  ) : null}
                </div>
              </article>
            )
          })}
          {items.length === 0 && <p className="t16 c-ink2">No open tasks right now.</p>}
        </div>
      </main>
      {tabBar}
    </>
  )
}
