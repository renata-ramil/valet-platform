import { useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import * as api from "../../lib/apiClient"
import { useAuth } from "../../context/AuthContext"

// The real columns fleet_service.import_cars_csv reads, in order. Design
// screen M15 shows a free column mapping step, but this build's import
// endpoint takes raw csv_text with no mapping, so the manager pastes a file
// that already uses these headers.
const CSV_HEADERS = [
  "email",
  "full_name",
  "unit",
  "plate",
  "make",
  "model",
  "color",
  "plan_name",
  "started_on",
]
const SAMPLE_CSV = `${CSV_HEADERS.join(",")}\nmaya@example.com,Maya Chen,1204,8KTR214,Honda,Civic,Silver,Standard,2026-11-19\n`

type Phase = "paste" | "dryrun" | "failed" | "done"

// Matching M15 (paste the file, step 1 of 2), M16 (dry run results) and
// M28 (import failed). There is no file-upload endpoint in this build, only
// POST /manager/cars/import with {csv_text, dry_run}, so step 1 is a paste
// box instead of M15's drag-and-drop, and there is no column mapping table
// since the backend expects these exact headers.
export function BulkImportPage({ onBack }: { onBack: () => void }) {
  const { user } = useAuth()
  const canEdit = user?.role === "manager"
  const queryClient = useQueryClient()

  const [csvText, setCsvText] = useState("")
  const [phase, setPhase] = useState<Phase>("paste")
  const [dryRun, setDryRun] = useState<api.ImportResult | null>(null)
  const [finalResult, setFinalResult] = useState<api.ImportResult | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const checkMutation = useMutation({
    mutationFn: () => api.managerImportCars(user!.csrf_token, csvText, true),
    onSuccess: (result) => {
      setDryRun(result)
      if (result.rows.length > 0 && result.ok_count === 0) {
        setErrorMessage("Every row in this file has an error. Fix them and check the file again.")
        setPhase("failed")
      } else {
        setErrorMessage(null)
        setPhase("dryrun")
      }
    },
    onError: (err: unknown) => {
      setErrorMessage(err instanceof Error ? err.message : "The file could not be read")
      setPhase("failed")
    },
  })

  const importMutation = useMutation({
    mutationFn: () => api.managerImportCars(user!.csrf_token, csvText, false),
    onSuccess: (result) => {
      setFinalResult(result)
      queryClient.invalidateQueries({ queryKey: ["manager-residents"] })
      if (result.ok_count === 0) {
        setErrorMessage("Nothing was imported from this file.")
        setPhase("failed")
      } else {
        setPhase("done")
      }
    },
    onError: (err: unknown) => {
      setErrorMessage(err instanceof Error ? err.message : "The import failed")
      setPhase("failed")
    },
  })

  const reset = () => {
    setPhase("paste")
    setDryRun(null)
    setFinalResult(null)
    setErrorMessage(null)
  }

  if (phase === "failed") {
    return (
      <>
        <header className="row between">
          <div>
            <h1 className="t28 w7">Residents and cars</h1>
            <div className="t14 c-ink2">Bulk import</div>
          </div>
          <div className="row g3">
            <button className="btn btn-secondary" type="button" onClick={reset}>
              Import cars
            </button>
            <button className="btn btn-quiet" type="button" onClick={onBack}>
              Back to residents
            </button>
          </div>
        </header>
        <section className="tile col g4" aria-label="Bulk import">
          <div>
            <h2 className="t20 w7">Import cars from a file</h2>
            <div className="t14 c-ink2">Nothing was imported from this file.</div>
          </div>
          <div className="t16 w7 c-late">{errorMessage}</div>
          <div className="row g3">
            <button className="btn btn-primary" type="button" onClick={reset}>
              Choose another file
            </button>
          </div>
          <div className="t14 c-ink2" style={{ maxWidth: 640 }}>
            The template has these headers in order, one row per car: {CSV_HEADERS.join(", ")}.
          </div>
          <pre className="tile-flat t14" style={{ padding: "var(--sp-4)", whiteSpace: "pre-wrap" }}>
            {SAMPLE_CSV}
          </pre>
        </section>
      </>
    )
  }

  if (phase === "done" && finalResult) {
    return (
      <>
        <header className="row between">
          <div>
            <h1 className="t28 w7">Residents and cars</h1>
            <div className="t14 c-ink2">Bulk import complete</div>
          </div>
          <button className="btn btn-primary" type="button" onClick={onBack}>
            Back to residents
          </button>
        </header>
        <section className="tile col g4" aria-label="Import complete">
          <div className="row g8">
            <div className="mfig">
              <span className="l">Imported</span>
              <span className="n">{finalResult.ok_count}</span>
              <span className="c c-done">cars added</span>
            </div>
            <div className="mfig">
              <span className="l">Skipped</span>
              <span className="n">{finalResult.error_count}</span>
              <span className="c c-late">rows with errors</span>
            </div>
          </div>
          <div className="t14 c-ink2">
            Fix the skipped rows in the file and import it again to add them.
          </div>
        </section>
      </>
    )
  }

  if (phase === "dryrun" && dryRun) {
    return (
      <div className="m16 col g4">
        <header className="row between">
          <div>
            <h1 className="t28 w7">Bulk import</h1>
            <div className="t14 c-ink2">Step 2 of 2, dry run. Nothing is saved yet.</div>
          </div>
          <div className="row g3">
            <button className="btn btn-secondary" type="button" onClick={() => setPhase("paste")}>
              Back to paste
            </button>
            <button
              className="btn btn-primary"
              type="button"
              disabled={!canEdit || dryRun.ok_count === 0 || importMutation.isPending}
              onClick={() => importMutation.mutate()}
            >
              Import valid rows
            </button>
          </div>
        </header>
        <div className="row g8">
          <div className="mfig">
            <span className="l">Rows checked</span>
            <span className="n">{dryRun.rows.length}</span>
            <span className="c c-ink2">In the file</span>
          </div>
          <div className="mfig">
            <span className="l">Ready to import</span>
            <span className="n">{dryRun.ok_count}</span>
            <span className="c c-done">{dryRun.ok_count} OK</span>
          </div>
          <div className="mfig">
            <span className="l">Need a fix</span>
            <span className="n">{dryRun.error_count}</span>
            <span className="c c-late">{dryRun.error_count} with errors</span>
          </div>
          <div className="grow" />
          <div className="t14 c-ink2" style={{ maxWidth: 360 }}>
            Import valid rows adds the {dryRun.ok_count} OK cars and skips the other{" "}
            {dryRun.error_count}. Fix those in the file and import it again.
          </div>
        </div>
        <section className="tile" style={{ padding: "var(--sp-2)" }} aria-label="Dry run results">
          <div>
            <div
              className="imp-row th"
              style={{ gridTemplateColumns: "56px minmax(0, 1fr) 104px minmax(0, 1fr) 176px" }}
            >
              <div>Row</div>
              <div>Email</div>
              <div>Plate</div>
              <div>Vehicle</div>
              <div>Result</div>
            </div>
            {dryRun.rows.map((r) => (
              <div
                className="imp-row"
                key={r.row_number}
                style={{ gridTemplateColumns: "56px minmax(0, 1fr) 104px minmax(0, 1fr) 176px" }}
              >
                <div className="c-ink2">{r.row_number}</div>
                <div className="w7 ellip">{r.email ?? "Unknown"}</div>
                <div>{r.license_plate ?? "-"}</div>
                <div className="ellip">{r.status === "ok" ? "Created" : r.detail}</div>
                <div className={r.status === "ok" ? "ok" : "er"}>
                  {r.status === "ok" ? "OK" : r.detail}
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>
    )
  }

  return (
    <>
      <header className="row between">
        <div>
          <h1 className="t28 w7">Bulk import</h1>
          <div className="t14 c-ink2">Step 1 of 2, paste the file and check it</div>
        </div>
        <div className="row g3">
          <button className="btn btn-secondary" type="button" onClick={onBack}>
            Cancel
          </button>
          <button
            className="btn btn-primary"
            type="button"
            disabled={!canEdit || !csvText.trim() || checkMutation.isPending}
            onClick={() => checkMutation.mutate()}
          >
            Check file
          </button>
        </div>
      </header>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "360px minmax(0, 1fr)",
          gap: "var(--sp-4)",
          alignItems: "stretch",
        }}
      >
        <section className="m15-drop" aria-label="CSV text">
          <div className="t20 w7">Paste CSV text</div>
          <div className="t14 c-ink2">
            Each row adds one car to a resident and unit that already exist in this building.
          </div>
          <button className="btn btn-secondary" type="button" onClick={() => setCsvText(SAMPLE_CSV)}>
            Load a sample row
          </button>
        </section>
        <section className="tile col g3" style={{ padding: "var(--sp-4)" }} aria-label="CSV input">
          <div className="field">
            <label className="lbl" htmlFor="bi-csv">
              CSV text, headers {CSV_HEADERS.join(", ")}
            </label>
            <textarea
              id="bi-csv"
              className="inp"
              style={{ minHeight: 320, fontFamily: "monospace", resize: "vertical" }}
              value={csvText}
              onChange={(e) => setCsvText(e.target.value)}
              placeholder={SAMPLE_CSV}
            />
          </div>
        </section>
      </div>
    </>
  )
}
