import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import * as api from "../../lib/apiClient"
import { useAuth } from "../../context/AuthContext"
import { AddCarWizard } from "./AddCarWizard"
import { BulkImportPage } from "./BulkImportPage"
import { ResidentDetailPage } from "./ResidentDetailPage"

// Matching M09 and D07: residents list with search, each row shows name,
// unit and car count, clicking a row opens the resident detail page. The
// mock's monthly total, balance and autopay columns and the past-due, no
// autopay, starting soon and ended filters all come from billing data that
// managerListResidents does not return (ResidentSummary has no balance or
// car-status fields), so this list shows what the endpoint actually has
// instead of inventing numbers. See docs/KNOWN-ISSUES.md.
export function ResidentsCarsPage() {
  const { user } = useAuth()
  const canEdit = user?.role === "manager"
  const [search, setSearch] = useState("")
  const [view, setView] = useState<"list" | "add" | "import">("list")
  const [openResidentId, setOpenResidentId] = useState<string | null>(null)

  const residentsQuery = useQuery({
    queryKey: ["manager-residents", search],
    queryFn: () => api.managerListResidents(search || undefined),
  })
  const residents = residentsQuery.data ?? []
  const totalActiveCars = residents.reduce((sum, r) => sum + r.car_count, 0)

  if (openResidentId) {
    return (
      <ResidentDetailPage residentId={openResidentId} onBack={() => setOpenResidentId(null)} />
    )
  }

  if (view === "import") {
    return <BulkImportPage onBack={() => setView("list")} />
  }

  return (
    <>
      <header className="row between">
        <div>
          <h1 className="t28 w7">Residents and cars</h1>
          <div className="t14 c-ink2">
            {residents.length} residents and {totalActiveCars} active cars
          </div>
        </div>
        <div className="row g3">
          <button
            className="btn btn-secondary"
            type="button"
            disabled={!canEdit}
            onClick={() => setView("import")}
          >
            Bulk import
          </button>
          <button
            className="btn btn-primary"
            type="button"
            disabled={!canEdit}
            data-testid="open-add-car"
            onClick={() => setView("add")}
          >
            Add car
          </button>
        </div>
      </header>

      <div className="row g4">
        <div style={{ width: 360, flex: "none" }}>
          <input
            className="inp"
            aria-label="Search residents"
            placeholder="Search by name, unit or email"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>

      <section className="tile" style={{ padding: "var(--sp-2)" }} aria-label="Residents">
        <div className="tbl">
          <div className="tr th" style={{ gridTemplateColumns: "2fr 1fr 1fr" }}>
            <div>Resident</div>
            <div>Unit</div>
            <div>Cars</div>
          </div>
          {residents.map((r) => (
            <button
              key={r.id}
              type="button"
              className="tr"
              style={{
                gridTemplateColumns: "2fr 1fr 1fr",
                minHeight: 64,
                width: "100%",
                textAlign: "left",
                background: "transparent",
                border: 0,
              }}
              onClick={() => setOpenResidentId(r.id)}
            >
              <div>
                <div className="t14 w7 ellip">{r.full_name}</div>
                <div className="t14 c-ink2 ellip">{r.email}</div>
              </div>
              <div className="t14">{r.unit ?? "No unit"}</div>
              <div className="t14 w7">
                {r.car_count} car{r.car_count === 1 ? "" : "s"}
              </div>
            </button>
          ))}
          {residentsQuery.isSuccess && residents.length === 0 && (
            <p className="t14 c-ink2 py2">No resident matches that search.</p>
          )}
        </div>
      </section>
      <div className="t14 c-ink2">
        Showing {residents.length} residents. Managers add and end cars here, and residents cannot
        change their fleet.
      </div>

      {view === "add" && (
        <AddCarWizard onClose={() => setView("list")} />
      )}
    </>
  )
}
