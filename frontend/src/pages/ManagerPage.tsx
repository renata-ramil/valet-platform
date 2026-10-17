import { useMemo, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import * as api from "../lib/apiClient"
import { useAuth } from "../context/AuthContext"
import { useLiveBuildingEvents } from "../lib/useLiveRequests"
import { ManagerFrame } from "../components/ManagerFrame"
import { useClock } from "../lib/useClock"
import { useTheme } from "../lib/useTheme"
import { ResidentsCarsPage } from "./manager/ResidentsCarsPage"
import { BillingSection } from "./manager/BillingSection"
import { PlansPage } from "./manager/PlansPage"
import { AddCarWizard } from "./manager/AddCarWizard"

const STATE_COLUMNS: { key: string; label: string; cls: string }[] = [
  { key: "scheduled", label: "Scheduled", cls: "c-sched" },
  { key: "queued", label: "Called", cls: "c-called" },
  { key: "en_route", label: "On the way", cls: "c-way" },
  { key: "delivered", label: "Delivered", cls: "c-done" },
]

function LiveBoard() {
  const dashboardQuery = useQuery({ queryKey: ["manager-dashboard"], queryFn: api.getManagerDashboard })
  const queryClient = useQueryClient()
  const { user } = useAuth()
  const clock = useClock()
  useLiveBuildingEvents(() => {
    queryClient.invalidateQueries({ queryKey: ["manager-dashboard"] })
  }, Boolean(user))

  const d = dashboardQuery.data
  const onShift = d?.valet_roster ?? []
  const busy = onShift.filter((v) => v.current_task_id)
  const idle = onShift.filter((v) => !v.current_task_id)

  return (
    <>
      <header className="row between">
        <div>
          <h1 className="t28 w7">Live board</h1>
          <div className="t14 c-ink2">{clock}</div>
        </div>
        <div className="row g3">
          <button className="btn btn-secondary" type="button">
            Print shift report
          </button>
          <button className="btn btn-primary" type="button">
            Add request
          </button>
        </div>
      </header>

      <div className="kpis">
        <div className="tile" style={{ padding: "var(--sp-4) var(--sp-6)" }}>
          <div className="t16 w5 c-ink2">On time today</div>
          <div className="t64 w7">
            {d?.on_time_rate_today !== null && d?.on_time_rate_today !== undefined
              ? `${Math.round(d.on_time_rate_today * 100)}%`
              : "-"}
          </div>
          <div className="t14 c-ink2">Live from today's deliveries</div>
        </div>
        <div className="tile" style={{ padding: "var(--sp-4) var(--sp-6)" }}>
          <div className="t16 w5 c-ink2">Requests today</div>
          <div className="t64 w7">
            {Object.values(d?.counts_by_state ?? {}).reduce((a, b) => a + b, 0)}
          </div>
          <div className="t14 c-ink2">Counted through {clock.split(", ")[1]}</div>
        </div>
        <div className="tile" style={{ padding: "var(--sp-4) var(--sp-6)" }}>
          <div className="t16 w5 c-ink2">Valets on shift</div>
          <div className="t64 w7">{onShift.length}</div>
          <div className="t14 c-ink2">
            {busy.length} with a task below, {idle.length} more
          </div>
        </div>
      </div>

      <section aria-label="Requests by state" className="col g3">
        <h2 className="t20 w7">Requests by state</h2>
        <div className="cols">
          {STATE_COLUMNS.map((col) => (
            <div className="tile col g2" style={{ padding: "var(--sp-3)" }} key={col.key}>
              <div className="row between">
                <div className={`t16 w7 ${col.cls}`}>{col.label}</div>
                <div className="t16 w7">{d?.counts_by_state[col.key] ?? 0}</div>
              </div>
              <hr className="rule" />
              {!d?.counts_by_state[col.key] && <p className="t14 c-ink2 py2">None right now</p>}
            </div>
          ))}
        </div>
      </section>

      <section className="tile" aria-label="Valets" style={{ padding: "var(--sp-4) var(--sp-6)" }}>
        <div className="row between" style={{ marginBottom: "var(--sp-3)" }}>
          <h2 className="t20 w7">Valets</h2>
          <div className="t14 c-ink2">{onShift.length} on shift</div>
        </div>
        <div className="vrow">
          {onShift.slice(0, 4).map((v) => (
            <div key={v.valet_id}>
              <div className="row between">
                <div className="t16 w7">{v.full_name}</div>
                <div className="t14 w7">{v.current_task_type ?? "Idle"}</div>
              </div>
              <div className="t14 c-ink2">
                {v.current_task_type ? `Working a ${v.current_task_type} task` : "No task assigned"}
              </div>
            </div>
          ))}
          {onShift.length > 4 && (
            <div>
              <div className="t16 w7">{onShift.length - 4} more on shift</div>
              <div className="t14 c-ink2">{onShift.slice(4).map((v) => v.full_name).join(", ")}</div>
            </div>
          )}
        </div>
      </section>
    </>
  )
}

// Garage map: representative layout matching the design's own sample data,
// since there is no live per-spot occupancy endpoint in this build.
function garageCells() {
  const counts = [5, 7, 6, 8, 3, 5, 2, 4, 6, 7, 3, 5, 6, 4]
  const soon: Record<string, string> = {
    "12-2": "7:38", "6-3": "7:52", "9-2": "8:00", "3-1": "8:10", "13-1": "8:20", "2-1": "8:35",
  }
  const blockers: Record<string, string> = { "6-1": "10:15", "6-2": "11:30", "9-1": "11:30", "12-1": "9:20" }
  const spots: Record<string, boolean> = { "7-3": true, "5-4": true }
  const cells: { cls: string; label: string }[] = []
  for (let d = 8; d >= 1; d--) {
    cells.push({ cls: "gm-dl", label: String(d) })
    for (let l = 1; l <= 14; l++) {
      const k = `${l}-${d}`
      let cls = "gm-c"
      let label = ""
      if (spots[k]) { cls = "gm-c spot"; label = "Spot" }
      else if (k === "6-3") { cls = "gm-c tgt"; label = soon[k] }
      else if (k === "12-2") { cls = "gm-c late"; label = soon[k] }
      else if (soon[k]) { cls = "gm-c soon"; label = soon[k] }
      else if (blockers[k]) { cls = "gm-c blk"; label = blockers[k] }
      else if (d <= counts[l - 1]) { cls = "gm-c car" }
      cells.push({ cls, label })
    }
  }
  return cells
}

function GarageMap() {
  const clock = useClock()
  const cells = useMemo(garageCells, [])
  return (
    <>
      <div className="row between">
        <div className="col g1">
          <h1 className="t28 w7">Garage map</h1>
          <p className="t14 c-ink2">{clock}, 71 of 112 spots in use</p>
        </div>
        <div className="seg" style={{ width: 280 }}>
          <button className="seg-i on" type="button">Next hour</button>
          <button className="seg-i" type="button">All cars</button>
        </div>
      </div>
      <div className="row g6 astretch grow">
        <section className="tile grow col g4" aria-label="Garage map">
          <div className="gm">
            <div className="gm-hd-sp" />
            {Array.from({ length: 14 }, (_, i) => (
              <div className="gm-hd" key={i}>L{i + 1}</div>
            ))}
            {cells.map((c, i) => (
              <div className={c.cls} key={i}>{c.label}</div>
            ))}
            <div className="gm-aisle">Aisle to the lobby and ramp</div>
          </div>
          <div className="row wrap g4">
            <div className="row g2"><div className="gm-c soon sw" /><span className="t14">Needed in the next hour</span></div>
            <div className="row g2"><div className="gm-c late sw" /><span className="t14">Late</span></div>
            <div className="row g2"><div className="gm-c blk sw" /><span className="t14">Sits in front of a car needed sooner</span></div>
            <div className="row g2"><div className="gm-c tgt sw" /><span className="t14">Selected car</span></div>
            <div className="row g2"><div className="gm-c spot sw" /><span className="t14">Planned spot</span></div>
            <div className="row g2"><div className="gm-c car sw" /><span className="t14">Parked, not needed soon</span></div>
          </div>
          <hr className="rule" />
          <div className="row g6 astart">
            <div className="kv grow" style={{ flexDirection: "column", alignItems: "flex-start", gap: 4 }}>
              <span className="k">Needed in the next hour</span><span className="v">6 cars</span>
            </div>
            <div className="kv grow" style={{ flexDirection: "column", alignItems: "flex-start", gap: 4 }}>
              <span className="k">Relocations those retrievals need</span><span className="v">4</span>
            </div>
            <div className="kv grow" style={{ flexDirection: "column", alignItems: "flex-start", gap: 4 }}>
              <span className="k">Cars in front of a sooner car</span><span className="v">4</span>
            </div>
          </div>
        </section>
        <aside className="tile none col g3" style={{ width: 336 }} aria-label="Selected car">
          <div className="col g1">
            <span className="t14 c-ink2 w5">Selected car</span>
            <span className="t20 w7">Silver Civic 8KTR214</span>
          </div>
          <hr className="rule" />
          <div className="col g1">
            <span className="t28 w7 c-called">Ready by 7:52</span>
            <span className="t14 c-ink2">Called 7:40 PM, latest 7:56</span>
            <span className="t16 w5">Lane 6, depth 3</span>
          </div>
          <hr className="rule" />
          <div className="col g2">
            <span className="t14 c-ink2 w5">Retrieval cost</span>
            <span className="t40 w7">2 relocations</span>
            <p className="t14">Two cars sit between this car and the aisle. Both must move first.</p>
          </div>
          <div className="grow" />
          <hr className="rule" />
          <div className="col g2">
            <button className="btn btn-secondary btn-block" type="button">Open request</button>
            <button className="btn btn-quiet btn-block" type="button">Assign a valet to help</button>
          </div>
        </aside>
      </div>
    </>
  )
}

// Demand chart: same deterministic forecast shape as the design,
// since there is no per-15-minute live forecast endpoint in this build.
function demandData() {
  const fc = [1,1,2,2,3,3,4,5, 6,8,9,10,12,13,14,17,21,14,11,9,8,7,6,5, 5,4,4,5,5,6,6,7,8,9,9,8,7,6,5,5, 6,7,8,10,11,12,13,12]
  const staffed = (i: number) => (i < 8 ? 2 : i < 24 ? 5 : i < 40 ? 4 : 6)
  const U = 10
  const S = 8
  const cols = fc.map((v, i) => {
    const lo = Math.floor(v * 0.8)
    const hi = Math.ceil(v * 1.2)
    const cap = staffed(i) * 3
    const cls = i % 4 === 0 ? "pc hr" : "pc"
    const short = i === 15 || i === 16
    return {
      cls,
      band: { left: 2, right: 2, bottom: lo * U, height: (hi - lo) * U },
      bar: { left: 5, right: 5, bottom: 0, height: v * U },
      cap: { left: 0, right: 0, bottom: cap * U - 1 },
      lbl: short ? String(v) : "",
      lblStyle: { left: 0, right: 0, bottom: v * U + 4 },
    }
  })
  const sCols = fc.map((_, i) => ({ height: staffed(i) * S }))
  const xLabels = ["4 AM", "5 AM", "6 AM", "7 AM", "8 AM", "9 AM", "10 AM", "11 AM", "12 PM", "1 PM", "2 PM", "3 PM"]
  return { cols, sCols, xLabels }
}

function DemandStaffing() {
  const { cols, sCols, xLabels } = useMemo(demandData, [])
  return (
    <>
      <header className="row between">
        <div>
          <h1 className="t28 w7">Tomorrow, Friday</h1>
          <div className="t14 c-ink2">Forecast for 4:00 AM to 4:00 PM</div>
        </div>
        <button className="btn btn-secondary" type="button">Download forecast</button>
      </header>

      <section className="tile" aria-label="Forecast and staffing by 15 minutes">
        <div className="row between" style={{ marginBottom: "var(--sp-4)" }}>
          <div className="t16 w7">Requests per 15 minutes</div>
          <div className="row g6 t14 c-ink2">
            <div className="row g2"><div className="sw bar" /><div>Forecast</div></div>
            <div className="row g2"><div className="sw band" /><div>Likely range</div></div>
            <div className="row g2"><div className="sw capl" /><div>Capacity, 3 per valet</div></div>
            <div className="row g2"><div className="sw sv" /><div>Staffed valets</div></div>
          </div>
        </div>
        <div className="row astart g2">
          <div className="yc" style={{ height: 300 }}>
            {[30, 20, 10, 0].map((t) => (
              <div className="yl t12 c-ink2" style={{ bottom: t * 10 - 8 }} key={t}>{t}</div>
            ))}
          </div>
          <div className="plot plot-d">
            {[10, 20, 30].map((t) => (
              <div className="gl" style={{ bottom: t * 10 }} key={t} />
            ))}
            {cols.map((c, i) => (
              <div className={c.cls} key={i}>
                <div className="a band" style={c.band} />
                <div className="a bar" style={c.bar} />
                <div className="a capl" style={c.cap} />
                <div className="a t12 w7 tc" style={c.lblStyle}>{c.lbl}</div>
              </div>
            ))}
            <div className="frame" style={{ left: "31.25%", width: "4.1667%", top: 0, bottom: 0 }} />
            <div className="card-late a" style={{ left: "36.5%", top: 8, width: 360, padding: "var(--sp-3)" }}>
              <div className="t14 w7 c-late">Short by up to 2 valets, 7:45 to 8:15 AM</div>
              <div className="t14">17 requests in the 7:45 bin and 21 in the 8:00 bin, 38 in all.</div>
            </div>
          </div>
        </div>

        <div className="t14 c-ink2" style={{ marginTop: "var(--sp-4)", marginBottom: "var(--sp-1)" }}>
          Staffed valets per 15 minutes
        </div>
        <div className="row astart g2">
          <div className="yc" style={{ height: 72 }}>
            {[8, 4, 0].map((t) => (
              <div className="yl t12 c-ink2" style={{ bottom: t * 8 - 8 }} key={t}>{t}</div>
            ))}
          </div>
          <div className="plot plot-s">
            {sCols.map((c, i) => (
              <div className={i % 4 === 0 ? "pc hr" : "pc"} key={i}>
                <div className="a sv" style={{ left: 0, right: 0, bottom: 0, height: c.height }} />
              </div>
            ))}
            <div className="frame" style={{ left: "31.25%", width: "4.1667%", top: 0, bottom: 0 }} />
          </div>
        </div>

        <div className="row g2" style={{ marginTop: "var(--sp-1)" }}>
          <div style={{ width: 40, flex: "none" }} />
          <div className="row grow">
            {xLabels.map((x) => (
              <div className="grow t12 c-ink2" key={x}>{x}</div>
            ))}
          </div>
        </div>
      </section>

      <section className="tile" aria-label="Where to add people">
        <h2 className="t20 w7" style={{ marginBottom: "var(--sp-3)" }}>Where to add people</h2>
        <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 3fr) minmax(0, 2fr)", gap: "var(--sp-6)", alignItems: "start" }}>
          <div className="tbl">
            <div className="tr th" style={{ gridTemplateColumns: "1fr 1.4fr 1fr 1fr 1fr", padding: "0 var(--sp-2)" }}>
              <div>15 minute bin</div><div>Forecast</div><div>Needed</div><div>Staffed</div><div>Gap</div>
            </div>
            <div className="tr" style={{ gridTemplateColumns: "1fr 1.4fr 1fr 1fr 1fr", padding: "0 var(--sp-2)" }}>
              <div className="w7">7:45 AM</div><div>17 requests</div><div>6 valets</div><div>5 valets</div><div className="w7 c-late">Short by 1</div>
            </div>
            <div className="tr" style={{ gridTemplateColumns: "1fr 1.4fr 1fr 1fr 1fr", padding: "0 var(--sp-2)" }}>
              <div className="w7">8:00 AM</div><div>21 requests</div><div>7 valets</div><div>5 valets</div><div className="w7 c-late">Short by 2</div>
            </div>
          </div>
          <div className="card-tint row g4">
            <div className="grow">
              <div className="t20 w7">Add 2 valets from 7:30 to 8:30 AM</div>
              <div className="t14 c-ink2">Seven valets cover the peak of the 8:00 bin.</div>
            </div>
            <button className="btn btn-primary none" type="button">Open roster</button>
          </div>
        </div>
      </section>
    </>
  )
}

function bar(domain: [number, number], range: [number, number]) {
  const pos = (x: number) => ((x - domain[0]) / (domain[1] - domain[0])) * 100
  return { left: `${pos(range[0]).toFixed(2)}%`, width: `${(pos(range[1]) - pos(range[0])).toFixed(2)}%` }
}
function dotPos(domain: [number, number], x: number) {
  const pos = ((x - domain[0]) / (domain[1] - domain[0])) * 100
  return { left: `calc(${pos.toFixed(2)}% - 10px)` }
}

function WhatIf() {
  const [valetCount, setValetCount] = useState(7)
  const [multiplier, setMultiplier] = useState(1.1)
  const currentQuery = useQuery({ queryKey: ["what-if-current"], queryFn: () => api.getWhatIf(5, 1.0) })
  const scenarioQuery = useQuery({
    queryKey: ["what-if-scenario", valetCount, multiplier],
    queryFn: () => api.getWhatIf(valetCount, multiplier),
  })

  const metrics = [
    {
      name: "p95 wait", unit: "Minutes", domain: [0, 10] as [number, number], ticks: [0, 2, 4, 6, 8, 10],
      cur: currentQuery.data?.wait_p95_seconds, curCi: currentQuery.data?.wait_p95_seconds_ci,
      sc: scenarioQuery.data?.wait_p95_seconds, scCi: scenarioQuery.data?.wait_p95_seconds_ci,
      fmt: (s: number) => `${(s / 60).toFixed(1)} min`, toUnit: (s: number) => s / 60,
    },
    {
      name: "On-time rate", unit: "Percent of requests on time", domain: [80, 100] as [number, number], ticks: [80, 85, 90, 95, 100],
      cur: currentQuery.data?.on_time_rate, curCi: currentQuery.data?.on_time_rate_ci,
      sc: scenarioQuery.data?.on_time_rate, scCi: scenarioQuery.data?.on_time_rate_ci,
      fmt: (r: number) => `${Math.round(r * 100)}%`, toUnit: (r: number) => r * 100,
    },
    {
      name: "Relocations per retrieval", unit: "Relocations per retrieval", domain: [0, 1.5] as [number, number], ticks: [0, 0.5, 1, 1.5],
      cur: currentQuery.data?.relocations_per_retrieval, curCi: currentQuery.data?.relocations_per_retrieval_ci,
      sc: scenarioQuery.data?.relocations_per_retrieval, scCi: scenarioQuery.data?.relocations_per_retrieval_ci,
      fmt: (v: number) => v.toFixed(2), toUnit: (v: number) => v,
    },
  ]

  return (
    <>
      <header className="row between">
        <div>
          <h1 className="t28 w7">What-if</h1>
          <div className="t14 c-ink2">A real simulation, run on demand</div>
        </div>
        <button className="btn btn-secondary" type="button">Open roster</button>
      </header>

      <div style={{ display: "grid", gridTemplateColumns: "420px minmax(0, 1fr)", gap: "var(--sp-6)", alignItems: "start" }}>
        <section className="tile col g6" aria-label="Try a different day">
          <h2 className="t20 w7">Try a different setup</h2>

          <div className="field">
            <div className="row between">
              <label className="lbl" htmlFor="valets">Valets on shift</label>
              <div className="t20 w7">{valetCount} valets</div>
            </div>
            <input
              id="valets"
              type="range"
              min={3}
              max={12}
              step={1}
              value={valetCount}
              onChange={(e) => setValetCount(Number(e.target.value))}
              style={{ accentColor: "var(--accent)", minHeight: 48, width: "100%" }}
            />
            <div className="row between t14 c-ink2"><span>3</span><span>Current setup: 5</span><span>12</span></div>
          </div>

          <div className="field">
            <div className="row between">
              <label className="lbl" htmlFor="mult">Demand multiplier</label>
              <div className="t20 w7">Times {multiplier.toFixed(1)}</div>
            </div>
            <input
              id="mult"
              type="range"
              min={0.5}
              max={1.5}
              step={0.1}
              value={multiplier}
              onChange={(e) => setMultiplier(Number(e.target.value))}
              style={{ accentColor: "var(--accent)", minHeight: 48, width: "100%" }}
            />
            <div className="row between t14 c-ink2"><span>0.5</span><span>Current setup: 1.0</span><span>1.5</span></div>
          </div>

          <div className="card-flat">
            <div className="t14 w7">Scenario to simulate</div>
            <div className="t14 c-ink2">
              {valetCount} valets and demand times {multiplier.toFixed(1)}, weekday_peak scenario, 10 seeds.
            </div>
          </div>

          <div className="col g2">
            <button className="btn btn-primary btn-block" type="button" onClick={() => scenarioQuery.refetch()}>
              Run simulation
            </button>
            <button
              className="btn btn-quiet btn-block"
              type="button"
              onClick={() => { setValetCount(5); setMultiplier(1.0) }}
            >
              Reset to current setup
            </button>
          </div>
        </section>

        <section className="tile" aria-label="Simulation results">
          <div className="row between" style={{ marginBottom: "var(--sp-2)" }}>
            <h2 className="t20 w7">Results for this setup</h2>
            <div className="t14 c-ink2">Each bar shows the likely range, the dot shows the best estimate</div>
          </div>
          {metrics.map((m) => (
            <div
              key={m.name}
              style={{ display: "grid", gridTemplateColumns: "200px minmax(0, 1fr)", columnGap: "var(--sp-6)", padding: "var(--sp-4) 0", borderTop: "1px solid var(--line)" }}
            >
              <div>
                <div className="t16 w7">{m.name}</div>
                <div className="t28 w7">{m.sc !== undefined ? m.fmt(m.sc) : "..."}</div>
                <div className="t14 c-ink2">
                  {m.scCi ? `range ${m.fmt(m.scCi[0])} to ${m.fmt(m.scCi[1])}` : ""}
                </div>
              </div>
              <div>
                <div className="t14"><span className="w7">Current, 5 valets</span>
                  <span className="c-ink2">, {m.cur !== undefined ? m.fmt(m.cur) : "..."}</span>
                </div>
                <div className="trk">
                  {m.curCi && (
                    <div className="ivl ivl-cur" style={bar(m.domain, [m.toUnit(m.curCi[0]), m.toUnit(m.curCi[1])])} />
                  )}
                  {m.cur !== undefined && <div className="dot" style={dotPos(m.domain, m.toUnit(m.cur))} />}
                </div>
                <div className="t14" style={{ marginTop: "var(--sp-2)" }}>
                  <span className="w7">Scenario, {valetCount} valets, demand times {multiplier.toFixed(1)}</span>
                  <span className="c-ink2">, {m.sc !== undefined ? m.fmt(m.sc) : "..."}</span>
                </div>
                <div className="trk">
                  {m.scCi && (
                    <div className="ivl ivl-sc" style={bar(m.domain, [m.toUnit(m.scCi[0]), m.toUnit(m.scCi[1])])} />
                  )}
                  {m.sc !== undefined && <div className="dot" style={dotPos(m.domain, m.toUnit(m.sc))} />}
                </div>
                <div className="axis">
                  {m.ticks.map((t) => (
                    <div className="axl t12 c-ink2" style={dotPos(m.domain, t)} key={t}>{t}</div>
                  ))}
                </div>
                <div className="t12 c-ink2 tc" style={{ marginTop: "var(--sp-1)" }}>{m.unit}</div>
              </div>
            </div>
          ))}
          <div className="card-tint">
            <div className="t16 w7">
              {currentQuery.data && scenarioQuery.data
                ? `At ${valetCount} valets and demand times ${multiplier.toFixed(1)}, p95 wait moves from ${(currentQuery.data.wait_p95_seconds / 60).toFixed(1)} to ${(scenarioQuery.data.wait_p95_seconds / 60).toFixed(1)} minutes and on-time moves from ${Math.round(currentQuery.data.on_time_rate * 100)} to ${Math.round(scenarioQuery.data.on_time_rate * 100)} percent.`
                : "Running the simulation..."}
            </div>
          </div>
        </section>
      </div>
    </>
  )
}

// Roster grid: representative week, since there is no multi-valet shift
// listing endpoint in this build (only the signed-in valet's own shifts).
function rosterData() {
  const dayDefs = [["Fri", "Oct 9"], ["Sat", "Oct 10"], ["Sun", "Oct 11"], ["Mon", "Oct 12"], ["Tue", "Oct 13"], ["Wed", "Oct 14"], ["Thu", "Oct 15"]]
  const M = "6a to 2p", E = "4a to 10a", A = "2p to 10p", D = "4a to 2p", X = "Off"
  const sched: [string, string[]][] = [
    ["Priya", [D, X, X, D, D, D, A]],
    ["Tomas", [E, M, X, E, E, X, E]],
    ["Marco", [M, M, X, M, M, M, X]],
    ["Joy", [M, X, M, M, M, X, M]],
    ["Sam", [M, A, X, M, X, M, M]],
    ["Lena", [X, M, M, X, M, M, M]],
  ]
  return { dayDefs, sched }
}

function Roster() {
  const { dayDefs, sched } = useMemo(rosterData, [])
  return (
    <>
      <header className="row between">
        <div>
          <h1 className="t28 w7">Roster and shifts</h1>
          <div className="t14 c-ink2">Friday October 9 to Thursday October 15</div>
        </div>
        <div className="row g3">
          <button className="btn btn-secondary" type="button">Copy last week</button>
          <button className="btn btn-primary" type="button">Add shift</button>
        </div>
      </header>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 340px", gap: "var(--sp-6)", alignItems: "start" }}>
        <section className="tile" style={{ padding: "var(--sp-4)" }} aria-label="Week shift grid">
          <div className="tbl">
            <div className="tr th" style={{ gridTemplateColumns: "88px repeat(7, minmax(0, 1fr))", columnGap: 0, padding: "0 var(--sp-2)", minHeight: 96 }}>
              <div className="hd t14 w7">Valet</div>
              {dayDefs.map(([day, date], i) => (
                <div className={i === 0 ? "hd fri" : "hd"} key={day}>
                  <div className="t14 w7 c-ink">{day}</div>
                  <div className="t14 w4 c-ink2">{date}</div>
                </div>
              ))}
            </div>
            {sched.map(([name, cells]) => (
              <div className="tr" style={{ gridTemplateColumns: "88px repeat(7, minmax(0, 1fr))", columnGap: 0, padding: "0 var(--sp-2)", minHeight: 44 }} key={name}>
                <div className="cl t14 w7">{name}</div>
                {cells.map((c, i) => (
                  <div className={`cl t14${i === 0 ? " fri" : ""}${c === "Off" ? " off" : ""}`} key={i}>
                    {c}
                  </div>
                ))}
              </div>
            ))}
          </div>
        </section>

        <section className="tile col g3" aria-label="Edit shift">
          <div>
            <h2 className="t20 w7">Edit shift</h2>
            <div className="t14 c-ink2">Priya, Friday October 9</div>
          </div>
          <div className="field">
            <div className="lbl">Start</div>
            <div className="row g2">
              <button className="btn btn-secondary" style={{ padding: "0 var(--sp-3)" }} type="button">Earlier</button>
              <div className="grow tc t16 w7">4:00 AM</div>
              <button className="btn btn-secondary" style={{ padding: "0 var(--sp-3)" }} type="button">Later</button>
            </div>
          </div>
          <div className="field">
            <div className="lbl">End</div>
            <div className="row g2">
              <button className="btn btn-secondary" style={{ padding: "0 var(--sp-3)" }} type="button">Earlier</button>
              <div className="grow tc t16 w7">2:00 PM</div>
              <button className="btn btn-secondary" style={{ padding: "0 var(--sp-3)" }} type="button">Later</button>
            </div>
          </div>
          <div className="row g2">
            <button className="btn btn-primary grow" style={{ padding: "0 var(--sp-3)" }} type="button">Save shift</button>
            <button className="btn btn-secondary grow" style={{ padding: "0 var(--sp-3)" }} type="button">Remove shift</button>
          </div>
        </section>
      </div>
    </>
  )
}

function Audit() {
  const [broken, setBroken] = useState(false)
  const clock = useClock()
  return (
    <>
      <header className="row between">
        <div>
          <h1 className="t28 w7">Audit and security</h1>
          <div className="t14 c-ink2">{clock}</div>
        </div>
        <div className="row g3">
          <button className="btn btn-quiet" type="button" onClick={() => setBroken((b) => !b)}>
            Demo: toggle result
          </button>
          <button className="btn btn-secondary" type="button">Export chain</button>
        </div>
      </header>

      {!broken ? (
        <section className="tile row between g6" aria-label="Chain check result">
          <div>
            <div className="t40 w7 c-done">Verified</div>
            <div className="t16">Checked {clock.split(", ")[1]}. Every event's hash matches the one before it.</div>
          </div>
          <button className="btn btn-secondary none" type="button">Run check again</button>
        </section>
      ) : (
        <section className="card-late row between astart g6" style={{ padding: "var(--sp-6)" }} aria-label="Chain check result">
          <div style={{ maxWidth: 720 }}>
            <div className="t40 w7 c-late">Chain broken at event 18,431</div>
            <div className="t16" style={{ marginTop: "var(--sp-2)" }}>
              Event 18,431 stores previous hash 3be1d07a. The chain expects d52b1c83. Events from
              18,431 on cannot be trusted until reviewed.
            </div>
          </div>
          <div className="col g2 none">
            <button className="btn btn-primary" type="button">Export evidence</button>
            <button className="btn btn-secondary" type="button">Alert the security lead</button>
          </div>
        </section>
      )}

      <section className="tile" aria-label="Key custody">
        <h2 className="t20 w7">Key custody</h2>
        <div className="t14 c-ink2" style={{ marginBottom: "var(--sp-3)" }}>4 keys out right now</div>
        <div className="col g3">
          <div>
            <div className="t16 w7">Green Outback 9MNB551</div>
            <div className="t14 c-ink2">Andre, slot 12-2</div>
          </div>
          <hr className="rule" />
          <div>
            <div className="t16 w7">White Kia Soul 1KDR552</div>
            <div className="t14 c-ink2">Priya, slot S-1</div>
          </div>
        </div>
      </section>
    </>
  )
}

function TicketsPanel() {
  const { user } = useAuth()
  const ticketsQuery = useQuery({ queryKey: ["tickets"], queryFn: api.listTickets })
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [reply, setReply] = useState("")
  const queryClient = useQueryClient()
  const ticketQuery = useQuery({
    queryKey: ["ticket", selectedId],
    queryFn: () => api.getTicket(selectedId!),
    enabled: Boolean(selectedId),
  })
  const tickets = ticketsQuery.data ?? []
  const ticket = ticketQuery.data ?? tickets.find((t) => t.id === selectedId)

  // M18 Car requests: a new tab/filter inside this same Tickets screen, next
  // to the existing ticket inbox above. A resident's car request has no
  // resident name or unit of its own (CarRequestOut only carries ticket_id),
  // so the resident list is fetched once and joined in by resident_id from
  // the request's own ticket.
  const [ticketTab, setTicketTab] = useState<"all" | "car-requests">("all")
  const [selectedCarRequestId, setSelectedCarRequestId] = useState<string | null>(null)
  const [carRequestAddInitial, setCarRequestAddInitial] = useState<{
    residentId?: string | null
    make?: string | null
    model?: string | null
    color?: string | null
    licensePlate?: string | null
    ticketId?: string
  } | null>(null)
  const canConvert = user?.role === "manager"

  const carRequestsQuery = useQuery({
    queryKey: ["manager-car-requests"],
    queryFn: api.managerListCarRequests,
    enabled: ticketTab === "car-requests",
  })
  const carRequests = carRequestsQuery.data ?? []
  const selectedCarRequest = carRequests.find((r) => r.id === selectedCarRequestId)
  const residentsQuery = useQuery({
    queryKey: ["manager-residents"],
    queryFn: () => api.managerListResidents(),
    enabled: ticketTab === "car-requests",
  })
  const residents = residentsQuery.data ?? []
  const carRequestTicketQuery = useQuery({
    queryKey: ["ticket", selectedCarRequest?.ticket_id],
    queryFn: () => api.getTicket(selectedCarRequest!.ticket_id),
    enabled: Boolean(selectedCarRequest),
  })
  const carRequestTicket = carRequestTicketQuery.data
  const carRequestResident = residents.find((r) => r.id === carRequestTicket?.resident_id)

  const prefillMutation = useMutation({
    mutationFn: (carRequestId: string) => api.managerPrefillCarRequest(carRequestId),
    onSuccess: (data, carRequestId) => {
      const req = carRequests.find((r) => r.id === carRequestId)
      setCarRequestAddInitial({
        residentId: (data.resident_id as string) ?? null,
        make: (data.make as string) ?? null,
        model: (data.model as string) ?? null,
        color: (data.color as string) ?? null,
        licensePlate: (data.license_plate as string) ?? null,
        ticketId: req?.ticket_id,
      })
    },
  })

  const sendReply = async () => {
    if (!user || !selectedId || !reply) return
    await api.addTicketMessage(user.csrf_token, selectedId, reply)
    setReply("")
    queryClient.invalidateQueries({ queryKey: ["ticket", selectedId] })
  }
  const resolve = async () => {
    if (!user || !selectedId) return
    await api.updateTicketStatus(user.csrf_token, selectedId, "resolved")
    queryClient.invalidateQueries({ queryKey: ["ticket", selectedId] })
    queryClient.invalidateQueries({ queryKey: ["tickets"] })
  }

  const closeCarRequestWizard = () => setCarRequestAddInitial(null)
  const onCarCreatedFromRequest = async () => {
    // Leaving the wizard open on its own success step here: it has a real
    // Done button already wired to onClose, so closing it a second time,
    // right when the car is created, would skip past that screen before
    // the manager ever saw it
    const ticketId = carRequestAddInitial?.ticketId
    if (user && ticketId) {
      await api.updateTicketStatus(user.csrf_token, ticketId, "resolved")
      queryClient.invalidateQueries({ queryKey: ["tickets"] })
      queryClient.invalidateQueries({ queryKey: ["ticket", ticketId] })
    }
    queryClient.invalidateQueries({ queryKey: ["manager-car-requests"] })
    setSelectedCarRequestId(null)
  }

  return (
    <>
      <header className="row between">
        <div>
          <h1 className="t28 w7">Tickets</h1>
          <div className="t14 c-ink2">{tickets.length} tickets</div>
        </div>
      </header>
      <div className="fbar" aria-label="Ticket filters">
        <button
          type="button"
          className={`fl${ticketTab === "all" ? " on" : ""}`}
          aria-pressed={ticketTab === "all"}
          onClick={() => setTicketTab("all")}
        >
          All
        </button>
        <button
          type="button"
          className={`fl${ticketTab === "car-requests" ? " on" : ""}`}
          aria-pressed={ticketTab === "car-requests"}
          onClick={() => setTicketTab("car-requests")}
        >
          Car requests
        </button>
      </div>
      {ticketTab === "all" && (
        <div style={{ display: "grid", gridTemplateColumns: "400px minmax(0, 1fr)", gap: "var(--sp-6)", alignItems: "start" }}>
          <section className="tile" style={{ padding: "var(--sp-2)" }} aria-label="Ticket list">
            <div className="px4 py3">
              <h2 className="t20 w7">Inbox</h2>
              <div className="t14 c-ink2">
                {tickets.length} tickets, {tickets.filter((t) => t.status !== "resolved").length} open
              </div>
            </div>
            <div className="tbl">
              {tickets.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  className={`tr${t.id === selectedId ? " sel" : ""}`}
                  style={{ gridTemplateColumns: "minmax(0, 1fr)", minHeight: 64, padding: "0 var(--sp-4)", width: "100%", textAlign: "left", background: "transparent", border: 0 }}
                  onClick={() => setSelectedId(t.id)}
                >
                  <div>
                    <div className="t14 w7 ellip">{t.subject}</div>
                    <div className="row between g2 t14">
                      <span className="c-ink2 ellip">Ticket {t.id.slice(0, 8)}</span>
                      <span className={`w7 none${t.status === "resolved" ? " c-done" : t.status === "waiting" ? " c-called" : ""}`}>
                        {t.status === "resolved" ? "Closed" : t.status === "waiting" ? "Waiting" : "Open"}
                      </span>
                    </div>
                  </div>
                </button>
              ))}
            </div>
          </section>

          {ticket ? (
            <section className="tile col g4" aria-label={`Ticket ${ticket.subject}`}>
              <div className="row between astart g4">
                <div>
                  <h2 className="t20 w7">{ticket.subject}</h2>
                  <div className="t14 c-ink2">Opened {new Date(ticket.created_at).toLocaleString()}</div>
                </div>
                <div className="t16 w7 c-called none">{ticket.status}</div>
              </div>
              <hr className="rule" />
              <div className="msgs">
                {ticket.messages.map((m) => (
                  <div className="bub bub-staff" style={{ maxWidth: 480 }} key={m.id}>
                    <div className="bub-who">{new Date(m.created_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</div>
                    {m.body}
                  </div>
                ))}
              </div>
              <div className="field">
                <label className="lbl" htmlFor="reply">Reply</label>
                <input className="inp" id="reply" value={reply} onChange={(e) => setReply(e.target.value)} />
              </div>
              <div className="row between">
                <div className="row g3">
                  <button className="btn btn-primary" type="button" onClick={sendReply}>Send reply</button>
                  <button className="btn btn-secondary" type="button" onClick={resolve}>Mark resolved</button>
                </div>
              </div>
            </section>
          ) : (
            <section className="tile" aria-label="No ticket selected">
              <p className="t16 c-ink2">Select a ticket to see the thread.</p>
            </section>
          )}
        </div>
      )}
      {ticketTab === "car-requests" && (
        <div style={{ display: "grid", gridTemplateColumns: "400px minmax(0, 1fr)", gap: "var(--sp-6)", alignItems: "start" }}>
          <section className="tile" aria-label="Car requests">
            <div className="px4 py3">
              <h2 className="t20 w7">Car requests</h2>
              <div className="t14 c-ink2">
                {carRequests.length} requests, {carRequests.filter((r) => r.status === "pending").length} open
              </div>
            </div>
            <div className="tbl">
              {carRequests.map((r) => (
                <button
                  key={r.id}
                  type="button"
                  className={`tr${r.id === selectedCarRequestId ? " sel" : ""}`}
                  style={{ gridTemplateColumns: "minmax(0, 1fr)", minHeight: 64, padding: "0 var(--sp-4)", width: "100%", textAlign: "left", background: "transparent", border: 0 }}
                  onClick={() => setSelectedCarRequestId(r.id)}
                >
                  <div>
                    <div className="t14 w7 ellip">
                      {r.action === "add" ? "Add" : r.action === "remove" ? "Remove" : "Change"}
                      {r.make || r.model ? ` ${[r.make, r.model].filter(Boolean).join(" ")}` : ""}
                      {r.plate ? ` ${r.plate}` : ""}
                    </div>
                    <div className="row between g2 t14">
                      <span className="c-ink2 ellip">{new Date(r.created_at).toLocaleDateString()}</span>
                      <span className={`w7 none${r.status !== "pending" ? " c-done" : ""}`}>
                        {r.status === "pending" ? "Open" : r.status === "applied" ? "Added" : "Dismissed"}
                      </span>
                    </div>
                  </div>
                </button>
              ))}
              {carRequestsQuery.isSuccess && carRequests.length === 0 && (
                <p className="t14 c-ink2 py2 px4">No car requests yet.</p>
              )}
            </div>
          </section>

          {selectedCarRequest ? (
            <section className="tile col g4" aria-label="Car request thread">
              <div className="row between astart g4">
                <div>
                  <h2 className="t20 w7">
                    {selectedCarRequest.action === "add" ? "Add" : selectedCarRequest.action === "remove" ? "Remove" : "Change"}
                    {" "}
                    {[selectedCarRequest.make, selectedCarRequest.model].filter(Boolean).join(" ") || "a car"}
                  </h2>
                  <div className="t14 c-ink2">
                    {carRequestResident
                      ? `${carRequestResident.full_name}${carRequestResident.unit ? `, Unit ${carRequestResident.unit}` : ""}`
                      : "Loading resident..."}
                    , opened {new Date(selectedCarRequest.created_at).toLocaleString()}
                  </div>
                </div>
                <div className="t16 w7 none">
                  {selectedCarRequest.status === "pending" ? "Open" : selectedCarRequest.status === "applied" ? "Added" : "Dismissed"}
                </div>
              </div>
              <hr className="rule" />
              {carRequestTicket && (
                <div className="msgs">
                  {carRequestTicket.messages.map((m) => (
                    <div className="bub bub-staff" style={{ maxWidth: 520 }} key={m.id}>
                      <div className="bub-who">{new Date(m.created_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</div>
                      {m.body}
                    </div>
                  ))}
                </div>
              )}
              <div className="row g8 astart">
                <div className="col g2 grow">
                  <div className="row g4">
                    <div className="t14 c-ink2" style={{ width: 96 }}>Resident</div>
                    <div className="t14 w7">
                      {carRequestResident
                        ? `${carRequestResident.full_name}${carRequestResident.unit ? `, Unit ${carRequestResident.unit}` : ""}`
                        : "Loading..."}
                    </div>
                  </div>
                  {(selectedCarRequest.make || selectedCarRequest.model) && (
                    <div className="row g4">
                      <div className="t14 c-ink2" style={{ width: 96 }}>Car</div>
                      <div className="t14 w7">{[selectedCarRequest.color, selectedCarRequest.make, selectedCarRequest.model].filter(Boolean).join(" ")}</div>
                    </div>
                  )}
                  {selectedCarRequest.plate && (
                    <div className="row g4">
                      <div className="t14 c-ink2" style={{ width: 96 }}>Plate</div>
                      <div className="t14 w7">{selectedCarRequest.plate}</div>
                    </div>
                  )}
                  {selectedCarRequest.note && (
                    <div className="row g4">
                      <div className="t14 c-ink2" style={{ width: 96 }}>Note</div>
                      <div className="t14 w7">{selectedCarRequest.note}</div>
                    </div>
                  )}
                </div>
                {selectedCarRequest.action === "add" && selectedCarRequest.status === "pending" && (
                  <div className="col g2" style={{ width: 320 }}>
                    <button
                      className="btn btn-primary btn-block"
                      type="button"
                      disabled={!canConvert || prefillMutation.isPending}
                      onClick={() => prefillMutation.mutate(selectedCarRequest.id)}
                    >
                      Add this car
                    </button>
                    <div className="hint">
                      Add this car opens the add-car sheet with the resident and vehicle already
                      filled in from this request.
                    </div>
                  </div>
                )}
              </div>
            </section>
          ) : (
            <section className="tile" aria-label="No car request selected">
              <p className="t16 c-ink2">Select a car request to see the thread.</p>
            </section>
          )}
        </div>
      )}
      {carRequestAddInitial && (
        <AddCarWizard
          initial={carRequestAddInitial}
          onClose={closeCarRequestWizard}
          onCreated={onCarCreatedFromRequest}
        />
      )}
    </>
  )
}

export function ManagerPage() {
  const { user } = useAuth()
  const [active, setActive] = useState("live")
  const [theme, toggleTheme] = useTheme("manager", "th-l")

  return (
    <ManagerFrame
      active={active}
      onChange={setActive}
      buildingName="Harbor Tower"
      managerName={user?.full_name ?? ""}
      managerRole={user?.role === "support" ? "Support, read only" : "Operations manager"}
      theme={theme}
      onToggleTheme={toggleTheme}
    >
      {active === "live" && <LiveBoard />}
      {active === "garage" && <GarageMap />}
      {active === "demand" && <DemandStaffing />}
      {active === "whatif" && <WhatIf />}
      {active === "roster" && <Roster />}
      {active === "residents" && <ResidentsCarsPage />}
      {active === "billing" && <BillingSection />}
      {active === "plans" && <PlansPage />}
      {active === "audit" && <Audit />}
      {active === "tickets" && <TicketsPanel />}
    </ManagerFrame>
  )
}
