import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import * as api from "../../lib/apiClient"
import { useAuth } from "../../context/AuthContext"
import { formatDate } from "../../lib/format"
import { AddCarWizard } from "./AddCarWizard"
import { EndCarSheet } from "./EndCarSheet"

function initials(fullName: string): string {
  const parts = fullName.trim().split(/\s+/)
  return parts
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? "")
    .join("")
}

// Matching M10: one resident's cars and info. The invoices, balance, credits
// and notes panels in the mock need billing data this screen's endpoint
// (managerResidentDetail) does not return, so those panels are left out
// rather than filled with invented numbers; see the report for the gap.
export function ResidentDetailPage({
  residentId,
  onBack,
}: {
  residentId: string
  onBack: () => void
}) {
  const { user } = useAuth()
  const canEdit = user?.role === "manager"
  const [addingCar, setAddingCar] = useState(false)
  const [endingCarId, setEndingCarId] = useState<string | null>(null)

  const detailQuery = useQuery({
    queryKey: ["manager-resident-detail", residentId],
    queryFn: () => api.managerResidentDetail(residentId),
  })
  const resident = detailQuery.data

  if (detailQuery.isLoading || !resident) {
    return (
      <header className="row between">
        <button className="btn btn-quiet" type="button" onClick={onBack}>
          Back to residents
        </button>
      </header>
    )
  }

  const endingCar = resident.cars.find((c) => c.id === endingCarId)
  if (endingCar) {
    return (
      <EndCarSheet
        car={endingCar}
        residentName={resident.full_name}
        residentUnit={resident.unit}
        onBack={() => setEndingCarId(null)}
        onEnded={() => setEndingCarId(null)}
      />
    )
  }

  const activeCars = resident.cars.filter((c) => c.status !== "ended")
  const endedCars = resident.cars.filter((c) => c.status === "ended")

  return (
    <>
      <header className="row between astart">
        <div className="row g4">
          <span className="avatar" style={{ width: 64, height: 64 }} aria-hidden="true">
            {initials(resident.full_name)}
          </span>
          <div>
            <h1 className="t28 w7">{resident.full_name}</h1>
            <div className="t14 c-ink2">
              {resident.unit ? `Unit ${resident.unit}` : "No unit on file"}, {resident.email}
            </div>
          </div>
        </div>
        <div className="row g2">
          <button className="btn btn-quiet" type="button" onClick={onBack}>
            Back to residents
          </button>
          <button
            className="btn btn-primary"
            type="button"
            disabled={!canEdit}
            onClick={() => setAddingCar(true)}
          >
            Add car
          </button>
        </div>
      </header>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(0, 1fr) 400px",
          gap: "var(--sp-4)",
          alignItems: "start",
        }}
      >
        <div className="col g4">
          <section className="tile col g2" aria-label="Cars">
            <div className="row between">
              <h2 className="t20 w7">Cars</h2>
              <div className="t14 c-ink2">
                {activeCars.length} active car{activeCars.length === 1 ? "" : "s"}
              </div>
            </div>
            <div>
              {resident.cars.map((car) => (
                <div className="car-row" key={car.id}>
                  <div className="m">
                    <span className="t16 w7">
                      {car.color} {car.model} {car.license_plate}
                    </span>
                    <span className="t14 c-ink2">
                      {car.size_class ?? "No size class"}, started {formatDate(car.started_on)}
                      {car.nickname ? `, nickname ${car.nickname}` : ""}
                      {car.ended_on ? `, ended ${formatDate(car.ended_on)}` : ""}
                    </span>
                  </div>
                  <div className="a">
                    <span
                      className={`sw ${car.status === "ended" ? "sw-void" : car.status === "pending" ? "sw-due" : "sw-paid"}`}
                    >
                      {car.status === "ended" ? "Ended" : car.status === "pending" ? "Pending" : "Active"}
                    </span>
                  </div>
                  {car.status !== "ended" && (
                    <button
                      className="btn btn-quiet"
                      type="button"
                      disabled={!canEdit}
                      onClick={() => setEndingCarId(car.id)}
                    >
                      End car
                    </button>
                  )}
                </div>
              ))}
              {resident.cars.length === 0 && (
                <p className="t14 c-ink2 py2">No cars on this account yet.</p>
              )}
            </div>
          </section>
          <div className="t14 c-ink2">
            Invoices, balance, credits and notes are not shown here yet: this build has no endpoint
            that returns a resident's billing detail alongside their fleet. See docs/KNOWN-ISSUES.md.
          </div>
        </div>

        <div className="col g4">
          <section className="tile col g2" aria-label="Contact">
            <h2 className="t16 w7">Contact</h2>
            <div className="kv">
              <span className="k">Email</span>
              <span className="v">{resident.email}</span>
            </div>
            <div className="kv">
              <span className="k">Unit</span>
              <span className="v">{resident.unit ?? "Not set"}</span>
            </div>
            <div className="kv">
              <span className="k">Cars on file</span>
              <span className="v">{resident.cars.length}</span>
            </div>
            {endedCars.length > 0 && (
              <div className="kv">
                <span className="k">Ended cars</span>
                <span className="v">{endedCars.length}</span>
              </div>
            )}
          </section>
        </div>
      </div>

      {addingCar && (
        <AddCarWizard
          initial={{ residentId: resident.id }}
          onClose={() => setAddingCar(false)}
        />
      )}
    </>
  )
}
