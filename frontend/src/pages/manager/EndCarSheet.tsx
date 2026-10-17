import { useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import * as api from "../../lib/apiClient"
import { useAuth } from "../../context/AuthContext"
import { formatDate } from "../../lib/format"

function toLocalIsoDate(date: Date): string {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, "0")
  const day = String(date.getDate()).padStart(2, "0")
  return `${year}-${month}-${day}`
}

// Matching M17: a full page, not a sheet, reached from a car row in the
// resident detail page. There is no preview endpoint for the proration
// credit, so this states the policy in words instead of showing a computed
// dollar amount: the server computes the real credit when the end call lands.
export function EndCarSheet({
  car,
  residentName,
  residentUnit,
  onBack,
  onEnded,
}: {
  car: api.Car
  residentName: string
  residentUnit: string | null
  onBack: () => void
  onEnded: () => void
}) {
  const { user } = useAuth()
  const canEdit = user?.role === "manager"
  const queryClient = useQueryClient()
  const [endedOn, setEndedOn] = useState(toLocalIsoDate(new Date()))

  const endCar = useMutation({
    mutationFn: () => api.managerEndCar(user!.csrf_token, car.id, endedOn),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["manager-resident-detail"] })
      queryClient.invalidateQueries({ queryKey: ["manager-residents"] })
      onEnded()
    },
  })

  const carLabel = `${car.color} ${car.model} ${car.license_plate}`

  return (
    <>
      <header className="row between">
        <div>
          <h1 className="t28 w7">End a car</h1>
          <div className="t14 c-ink2">
            {residentName}
            {residentUnit ? `, unit ${residentUnit}` : ""}
          </div>
        </div>
        <div className="row g3">
          <button className="btn btn-quiet" type="button" onClick={onBack}>
            Back to {residentName}
          </button>
        </div>
      </header>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(0, 1fr) 440px",
          gap: "var(--sp-4)",
          alignItems: "start",
        }}
      >
        <section className="tile col g4" aria-label="End date">
          <div className="car-row" style={{ boxShadow: "none", padding: 0 }}>
            <div className="m">
              <span className="t16 w7">{carLabel}</span>
              <span className="t14 c-ink2">
                {car.size_class ?? "No size class"}, started {formatDate(car.started_on)}
              </span>
            </div>
            <div className="a">
              <span className="sw sw-paid">
                {car.status === "pending" ? "Pending" : car.status === "ended" ? "Ended" : "Active"}
              </span>
            </div>
          </div>
          <div className="field">
            <label className="lbl" htmlFor="ec-ed">
              Last day of service
            </label>
            <input
              type="date"
              className="inp"
              id="ec-ed"
              value={endedOn}
              onChange={(e) => setEndedOn(e.target.value)}
              disabled={!canEdit}
            />
          </div>
          <div className="tile-flat t14" style={{ padding: "var(--sp-4)" }}>
            Ending this car stops every repeating schedule for {car.license_plate} on {formatDate(endedOn)}, and
            requests for this car can no longer be made after that date. The unused days left on its
            current plan become a credit on the resident's next invoice. The server calculates the
            exact credit when you confirm.
          </div>
          {endCar.isError && (
            <div className="hint err" role="alert">
              {endCar.error instanceof Error ? endCar.error.message : "Could not end this car"}
            </div>
          )}
        </section>
        <section className="confirm" aria-label="Confirm ending the car">
          <h2 className="t20 w7">
            End the {car.color} {car.model} on {formatDate(endedOn)}?
          </h2>
          <div className="t14 c-ink2">
            The resident is told by push message and email. This cannot be undone.
          </div>
          <button
            className="btn btn-primary btn-block"
            type="button"
            disabled={!canEdit || endCar.isPending || car.status === "ended"}
            onClick={() => endCar.mutate()}
          >
            {car.status === "ended" ? "Already ended" : "End car"}
          </button>
          <button className="btn btn-quiet btn-block" type="button" onClick={onBack}>
            Keep the car
          </button>
        </section>
      </div>
    </>
  )
}
