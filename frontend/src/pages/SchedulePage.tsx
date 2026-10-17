import { useRef, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import * as api from "../lib/apiClient"
import { useAuth } from "../context/AuthContext"
import { Icon } from "../components/Icon"
import { ResidentTabbar } from "../components/ResidentTabbar"
import type { ResidentTab } from "../components/ResidentTabbar"
import { describeWeekdays, formatLocalTimeString, weekdayLetter } from "../lib/format"

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1)
}

function toLocalIsoDate(date: Date): string {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, "0")
  const day = String(date.getDate()).padStart(2, "0")
  return `${year}-${month}-${day}`
}

function nextOccurrences(weekdays: number[], count: number): Date[] {
  const results: Date[] = []
  const cursor = new Date()
  cursor.setHours(0, 0, 0, 0)
  while (results.length < count) {
    const jsWeekday = cursor.getDay()
    const modelWeekday = (jsWeekday + 6) % 7
    if (weekdays.includes(modelWeekday)) results.push(new Date(cursor))
    cursor.setDate(cursor.getDate() + 1)
  }
  return results
}

function weekDates(offsetWeeks: number): Date[] {
  const today = new Date()
  const jsWeekday = today.getDay()
  const modelWeekday = (jsWeekday + 6) % 7
  const monday = new Date(today)
  monday.setDate(today.getDate() - modelWeekday + offsetWeeks * 7)
  monday.setHours(0, 0, 0, 0)
  return Array.from({ length: 7 }, (_, i) => {
    const d = new Date(monday)
    d.setDate(monday.getDate() + i)
    return d
  })
}

const WEEKDAY_FULL = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

const HOURS = Array.from({ length: 12 }, (_, i) => i + 1)
const MINUTES = Array.from({ length: 60 }, (_, i) => String(i).padStart(2, "0"))
const MERIDIEMS = ["AM", "PM"] as const

export function WheelColumn<T extends string | number>({
  options,
  value,
  onChange,
  label,
}: {
  options: readonly T[]
  value: T
  onChange: (v: T) => void
  label: string
}) {
  const colRef = useRef<HTMLDivElement>(null)
  const scrollTimeout = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  const onScroll = () => {
    if (scrollTimeout.current) clearTimeout(scrollTimeout.current)
    scrollTimeout.current = setTimeout(() => {
      const col = colRef.current
      if (!col) return
      const rect = col.getBoundingClientRect()
      const centered = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2)
      const text = centered?.closest(".tp-i")?.textContent
      const match = options.find((o) => String(o) === text)
      if (match !== undefined && match !== value) onChange(match)
    }, 120)
  }

  return (
    <div className="tp-col" role="listbox" aria-label={label} ref={colRef} onScroll={onScroll}>
      {options.map((opt) => (
        <button
          key={opt}
          type="button"
          role="option"
          aria-selected={value === opt}
          className={`tp-i${value === opt ? " sel" : ""}`}
          onClick={(e) => {
            onChange(opt)
            e.currentTarget.scrollIntoView({ block: "center", behavior: "smooth" })
          }}
        >
          {opt}
        </button>
      ))}
    </div>
  )
}

function AddScheduleSheet({
  cars,
  onClose,
  onSaved,
}: {
  cars: api.Car[]
  onClose: () => void
  onSaved: () => void
}) {
  const { user } = useAuth()
  const [weekdays, setWeekdays] = useState<number[]>([0, 1, 2, 3, 4])
  const [hour, setHour] = useState(8)
  const [minute, setMinute] = useState("00")
  const [meridiem, setMeridiem] = useState<(typeof MERIDIEMS)[number]>("AM")
  const [carId, setCarId] = useState(cars[0]?.id ?? "")

  const hour24 = meridiem === "AM" ? (hour === 12 ? 0 : hour) : hour === 12 ? 12 : hour + 12

  const createSchedule = useMutation({
    mutationFn: () =>
      api.createSchedule(user!.csrf_token, {
        car_id: carId,
        weekdays,
        ready_by_local_time: `${String(hour24).padStart(2, "0")}:${minute}:00`,
        active_from: toLocalIsoDate(new Date()),
      }),
    onSuccess: onSaved,
  })

  const car = cars.find((c) => c.id === carId)
  const summary = car
    ? `${describeWeekdays(weekdays)} at ${hour}:${minute} ${meridiem}, ${car.color} ${car.model}`
    : "Pick a car"

  return (
    <>
      <header className="topbar" aria-hidden="true">
        <div className="ibtn" />
        <h1 className="ttl">Schedule</h1>
        <div className="ibtn" />
      </header>
      <div className="scrim" />
      <section className="sheet" role="dialog" aria-label="New schedule">
        <div className="grab" />
        <div className="row between">
          <h2 className="t20 w7">New schedule</h2>
          <button className="btn btn-quiet ibtn" type="button" aria-label="Close" onClick={onClose}>
            <Icon name="plus" rotate={45} />
          </button>
        </div>

        <div className="col g2">
          <span className="lbl" id="l-days">Days</span>
          <div className="wd-row" role="group" aria-labelledby="l-days">
            {[0, 1, 2, 3, 4, 5, 6].map((d) => (
              <button
                key={d}
                type="button"
                className={`wd${weekdays.includes(d) ? " on" : ""}`}
                aria-label={WEEKDAY_FULL[d]}
                aria-pressed={weekdays.includes(d)}
                onClick={() =>
                  setWeekdays((cur) => (cur.includes(d) ? cur.filter((x) => x !== d) : [...cur, d]))
                }
              >
                {weekdayLetter(d)}
              </button>
            ))}
          </div>
        </div>

        <div className="col g2">
          <span className="lbl" id="l-time">Time</span>
          <div className="tp" role="group" aria-labelledby="l-time">
            <WheelColumn options={HOURS} value={hour} onChange={setHour} label="Hour" />
            <WheelColumn options={MINUTES} value={minute} onChange={setMinute} label="Minute" />
            <WheelColumn options={MERIDIEMS} value={meridiem} onChange={setMeridiem} label="AM or PM" />
          </div>
        </div>

        <div className="col g2">
          <span className="lbl" id="l-car">Car</span>
          <div className="cp" role="group" aria-labelledby="l-car">
            {cars.map((c) => (
              <button
                key={c.id}
                type="button"
                className={`cp-i${carId === c.id ? " on" : ""}`}
                aria-pressed={carId === c.id}
                data-testid="schedule-car-option"
                onClick={() => setCarId(c.id)}
              >
                <span className="cp-ic"><Icon name="car" /></span>
                <span className="grow col">
                  <span className="w7">{c.color} {c.model}</span>
                  <span className="t14 c-ink2">{c.license_plate}</span>
                </span>
                {carId === c.id && <Icon name="check" className="g cp-ck" />}
              </button>
            ))}
          </div>
        </div>

        <div className="row g2" aria-live="polite">
          <Icon name="repeat" />
          <p className="t16 w7">{summary}</p>
        </div>

        <button
          className="btn btn-primary btn-xl"
          type="button"
          disabled={!carId || weekdays.length === 0 || createSchedule.isPending}
          data-testid="save-schedule-button"
          onClick={() => createSchedule.mutate()}
        >
          Save schedule
        </button>
      </section>
    </>
  )
}

function WeekView({
  onBack,
  onNavigate,
}: {
  onBack: () => void
  onNavigate: (tab: ResidentTab) => void
}) {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const schedulesQuery = useQuery({ queryKey: ["schedules"], queryFn: api.listSchedules })
  const [week, setWeek] = useState<0 | 1>(0)
  const [toast, setToast] = useState<string | null>(null)
  // Tracking skipped dates for this session only: the Schedule the API
  // returns carries no exception list, so a reload forgets this until the
  // backend grows an endpoint for it (see docs/KNOWN-ISSUES.md)
  const [skippedDates, setSkippedDates] = useState<Set<string>>(new Set())
  const schedule = schedulesQuery.data?.[0]

  const skip = useMutation({
    mutationFn: (date: string) =>
      api.addScheduleException(user!.csrf_token, schedule!.id, { local_date: date, kind: "skip" }),
    onSuccess: (_r, date) => {
      setToast(`Skipped ${new Date(date).toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" })}`)
      setSkippedDates((cur) => new Set(cur).add(date))
      queryClient.invalidateQueries({ queryKey: ["schedules"] })
    },
  })

  const days = weekDates(week)

  return (
    <>
      <header className="topbar">
        <div className="ibtn" aria-hidden="true" />
        <h1 className="ttl">Schedule</h1>
        <div className="ibtn" aria-hidden="true" />
      </header>
      <main className="pw">
        <div className="in">
          <div className="seg" role="group" aria-label="Week">
            <button className={`seg-i${week === 0 ? " on" : ""}`} type="button" onClick={() => setWeek(0)}>
              This week
            </button>
            <button className={`seg-i${week === 1 ? " on" : ""}`} type="button" onClick={() => setWeek(1)}>
              Next week
            </button>
          </div>
        </div>

        <h2 className="in t20 w7">
          {days[0].toLocaleDateString([], { month: "short", day: "numeric" })} to{" "}
          {days[6].toLocaleDateString([], { month: "short", day: "numeric" })}
        </h2>

        <div className="col g1">
          <div className="wk">
            {days.map((d) => {
              const dateKey = toLocalIsoDate(d)
              const skipped = skippedDates.has(dateKey)
              const modelWeekday = (d.getDay() + 6) % 7
              const on = schedule?.weekdays.includes(modelWeekday) && !schedule.paused_until && !skipped
              return (
                <button
                  key={d.toISOString()}
                  type="button"
                  className={`wk-d${skipped ? " skip" : on ? " on" : ""}`}
                  disabled={!on || skip.isPending}
                  onClick={() => on && skip.mutate(dateKey)}
                  aria-label={`${d.toDateString()}${skipped ? ", skipped" : ""}`}
                >
                  <span>{d.toLocaleDateString([], { weekday: "short" })}</span>
                  <b>{d.getDate()}</b>
                </button>
              )
            })}
          </div>
          <div className="wk" aria-hidden="true">
            {days.map((d) => {
              const dateKey = toLocalIsoDate(d)
              const skipped = skippedDates.has(dateKey)
              const modelWeekday = (d.getDay() + 6) % 7
              const on = schedule?.weekdays.includes(modelWeekday)
              return (
                <span className="wk-t tc t14 c-ink2" key={d.toISOString()}>
                  {skipped ? "Skipped" : on && schedule ? schedule.ready_by_local_time.slice(0, 5) : ""}
                </span>
              )
            })}
          </div>
        </div>

        <p className="in t14 c-ink2">Tap a scheduled day to skip that one date. A skipped day shows its date struck through.</p>

        {toast && (
          <div className="in last">
            <div className="toast tq" role="status">
              <span className="grow">{toast}</span>
              <button className="btn btn-quiet sm" type="button" onClick={() => setToast(null)}>
                Dismiss
              </button>
            </div>
          </div>
        )}
      </main>
      <ResidentTabbar
        active="schedule"
        onChange={(tab) => (tab === "schedule" ? onBack() : onNavigate(tab))}
      />
    </>
  )
}

export function SchedulePage({ onNavigate }: { onNavigate: (tab: ResidentTab) => void }) {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const carsQuery = useQuery({ queryKey: ["cars"], queryFn: api.listCars })
  const schedulesQuery = useQuery({ queryKey: ["schedules"], queryFn: api.listSchedules })
  const [sheetOpen, setSheetOpen] = useState(false)
  const [weekViewOpen, setWeekViewOpen] = useState(false)
  const [pauseOpen, setPauseOpen] = useState(false)
  const [pauseDate, setPauseDate] = useState("")

  const skipTomorrow = useMutation({
    mutationFn: (scheduleId: string) => api.skipTomorrow(user!.csrf_token, scheduleId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["schedules"] }),
  })

  const pauseUntilMutation = useMutation({
    mutationFn: ({ scheduleId, date }: { scheduleId: string; date: string }) =>
      api.pauseUntil(user!.csrf_token, scheduleId, date),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["schedules"] })
      setPauseOpen(false)
    },
  })

  const carsById = Object.fromEntries((carsQuery.data ?? []).map((car) => [car.id, car]))
  const schedule = schedulesQuery.data?.[0]
  const car = schedule ? carsById[schedule.car_id] : undefined

  if (weekViewOpen) {
    return <WeekView onBack={() => setWeekViewOpen(false)} onNavigate={onNavigate} />
  }

  return (
    <>
      <header className="topbar">
        <div className="ibtn" aria-hidden="true" />
        <h1 className="ttl">Schedule</h1>
        <button className="btn btn-quiet ibtn" type="button" aria-label="Add schedule" data-testid="add-schedule-button" onClick={() => setSheetOpen(true)}>
          <Icon name="plus" />
        </button>
      </header>
      <main className="pbody" data-testid="schedule-page">
        <div className="col g6 py2">
          {schedule ? (
            <>
              <section className="card row g3" aria-label="Current schedule" data-testid="schedule-row">
                <div className="grow col g1">
                  <p className="t20 w7">
                    {capitalize(describeWeekdays(schedule.weekdays))} at {formatLocalTimeString(schedule.ready_by_local_time.slice(0, 5))}
                    {car ? `, ${car.color} ${car.model}` : ""}
                  </p>
                  <p className="t14 c-ink2">
                    {schedule.paused_until ? `Paused until ${schedule.paused_until}` : "Repeats every scheduled day"}
                  </p>
                </div>
                <button type="button" className="tgl on" role="switch" aria-checked="true" aria-label="Schedule on" />
              </section>

              <section className="col g2" aria-label="Next three dates">
                <h2 className="t16 w7">Next three dates</h2>
                <ul>
                  {nextOccurrences(schedule.weekdays, 3).map((d) => (
                    <li className="dr row g3" key={d.toISOString()}>
                      <Icon name="clock" className="g c-ink2" />
                      <span className="grow t16 w5">{d.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" })}</span>
                      <span className="t16 w7" data-testid={`next-date-${toLocalIsoDate(d)}`}>
                        {formatLocalTimeString(schedule.ready_by_local_time.slice(0, 5))}
                      </span>
                    </li>
                  ))}
                </ul>
              </section>

              <section className="col g2" aria-label="Change a date">
                <button className="opt" type="button" data-testid="skip-tomorrow-button" onClick={() => skipTomorrow.mutate(schedule.id)}>
                  <span className="col">
                    <span className="w7">Skip tomorrow</span>
                    <span className="t14 c-ink2 w4">
                      {new Date(Date.now() + 86400000).toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" })}
                    </span>
                  </span>
                  <Icon name="arrow" />
                </button>
                <button className="opt" type="button" onClick={() => setWeekViewOpen(true)}>
                  <span className="w7">Skip a date</span>
                  <Icon name="arrow" />
                </button>
                <button className="opt" type="button" onClick={() => setPauseOpen((v) => !v)}>
                  <span className="w7">Pause until</span>
                  <Icon name="arrow" />
                </button>
                {pauseOpen && (
                  <div className="row g2">
                    <input
                      type="date"
                      className="inp grow"
                      data-testid="pause-date-input"
                      value={pauseDate}
                      onChange={(e) => setPauseDate(e.target.value)}
                    />
                    <button
                      className="btn btn-primary"
                      type="button"
                      data-testid="pause-until-button"
                      disabled={!pauseDate || pauseUntilMutation.isPending}
                      onClick={() => pauseUntilMutation.mutate({ scheduleId: schedule.id, date: pauseDate })}
                    >
                      Confirm
                    </button>
                  </div>
                )}
              </section>
            </>
          ) : (
            <div className="empty" aria-label="No schedule yet">
              <div className="orb" aria-hidden="true" />
              <p className="t16 w7">No recurring schedule yet</p>
              <p className="t14 c-ink2">Add one so your car is ready at the same time every day.</p>
              <button className="btn btn-secondary" type="button" onClick={() => setSheetOpen(true)}>
                Add schedule
              </button>
            </div>
          )}
        </div>
      </main>
      {sheetOpen && (
        <AddScheduleSheet
          cars={carsQuery.data ?? []}
          onClose={() => setSheetOpen(false)}
          onSaved={() => {
            queryClient.invalidateQueries({ queryKey: ["schedules"] })
            setSheetOpen(false)
          }}
        />
      )}
      {!sheetOpen && <ResidentTabbar active="schedule" onChange={onNavigate} />}
    </>
  )
}
