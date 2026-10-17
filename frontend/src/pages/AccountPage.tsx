import { useEffect, useState } from "react"
import { useMutation } from "@tanstack/react-query"
import * as api from "../lib/apiClient"
import { useAuth } from "../context/AuthContext"
import { Icon } from "../components/Icon"
import { TopbarBack } from "../components/PhoneFrame"
import { FakeQr } from "../components/FakeQr"
import { ApiError } from "../lib/apiClient"
import type { ThemeName } from "../lib/useTheme"

const NOTIFICATION_ROWS = ["Car called", "On the way", "Delivered", "Schedule reminders the evening before"]

function TwoFactorSetup({ onBack }: { onBack: () => void }) {
  const { user } = useAuth()
  const [enrollment, setEnrollment] = useState<api.TotpEnrollment | null>(null)
  const [code, setCode] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  const enroll = useMutation({
    mutationFn: () => api.enrollTotp(user!.csrf_token),
    onSuccess: setEnrollment,
    onError: (err: unknown) =>
      setError(
        err instanceof ApiError
          ? err.message
          : "Could not start setup",
      ),
  })

  const confirm = useMutation({
    mutationFn: () => api.confirmTotp(code, user!.csrf_token),
    onSuccess: () => setDone(true),
    onError: (err: unknown) =>
      setError(err instanceof ApiError ? err.message : "That code did not match"),
  })

  useEffect(() => {
    enroll.mutate()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <>
      <TopbarBack title="Two-factor setup" onBack={onBack} />
      <main className="pbody-full col g3" style={{ paddingBottom: "var(--sp-16)" }}>
        {done ? (
          <p className="t16 w7">Two-factor sign-in is on for your account.</p>
        ) : error && !enrollment ? (
          <p className="t16 c-ink2">{error}</p>
        ) : enrollment ? (
          <>
            <p className="t16 w7">Scan this code with your authenticator app</p>
            <div className="row g4 astart">
              <FakeQr />
              <p className="t16 grow">
                Cannot scan? Enter the key <span className="w7">{enrollment.secret}</span>
              </p>
            </div>
            <div className="field">
              <label className="lbl" id="codelbl">Enter the 6-digit code</label>
              <div className="code" role="group" aria-labelledby="codelbl">
                {Array.from({ length: 6 }).map((_, i) => (
                  <div key={i} className={`cb${error ? " is-error" : i === code.length ? " is-focus" : ""}`}>
                    {code[i] ?? ""}
                  </div>
                ))}
              </div>
              <input
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                style={{ position: "absolute", opacity: 0, pointerEvents: "none" }}
                autoFocus
              />
              {error && <p className="hint err">{error}</p>}
            </div>

            <section className="card-flat col g3" aria-label="Recovery codes">
              <h2 className="t16 w7">Recovery codes, save these now</h2>
              <div className="rc t16 w5">
                {enrollment.recovery_codes.map((rc) => (
                  <span key={rc}>{rc}</span>
                ))}
              </div>
              <button
                className="btn btn-secondary btn-block"
                type="button"
                onClick={() => navigator.clipboard?.writeText(enrollment.recovery_codes.join("\n"))}
              >
                Copy codes
              </button>
            </section>

            <button
              className={`btn btn-primary btn-xl${code.length < 6 ? " is-disabled" : ""}`}
              type="button"
              disabled={code.length < 6 || confirm.isPending}
              onClick={() => confirm.mutate()}
            >
              Turn on two-factor
            </button>
          </>
        ) : (
          <p className="t16 c-ink2">Starting setup...</p>
        )}
      </main>
    </>
  )
}

function initials(name: string): string {
  return name
    .split(" ")
    .map((p) => p[0])
    .join("")
    .slice(0, 2)
    .toUpperCase()
}

export function AccountPage({
  onBack,
  theme,
  onToggleTheme,
}: {
  onBack: () => void
  theme: ThemeName
  onToggleTheme: () => void
}) {
  const { user, logout } = useAuth()
  const [channel, setChannel] = useState<"push" | "text" | "email">("push")
  const [toggles, setToggles] = useState<Record<string, boolean>>({
    "Car called": true,
    "On the way": true,
    Delivered: true,
    "Schedule reminders the evening before": false,
  })
  const [showTwoFactor, setShowTwoFactor] = useState(false)
  const isStaff = user?.role === "valet" || user?.role === "manager" || user?.role === "support"

  if (showTwoFactor) {
    return <TwoFactorSetup onBack={() => setShowTwoFactor(false)} />
  }

  return (
    <>
      <TopbarBack title="Account" onBack={onBack} />
      <main className="pbody col g4" data-testid="account-page">
        <section className="card row g4">
          <div className="orb row jcenter t16 w7 c-ink" aria-hidden="true">
            {user ? initials(user.full_name) : ""}
          </div>
          <div className="col grow">
            <h1 className="t20 w7">{user?.full_name}</h1>
            <p className="t16">Harbor Tower</p>
            <p className="t16 c-ink2 ellip">{user?.email}</p>
          </div>
        </section>

        <section className="col g2" aria-label="Notifications">
          <h2 className="t14 w7 c-ink2">Notifications</h2>
          <div className="seg" role="tablist" aria-label="Channel">
            {(["push", "text", "email"] as const).map((c) => (
              <button
                key={c}
                type="button"
                className={`seg-i${channel === c ? " on" : ""}`}
                role="tab"
                aria-selected={channel === c}
                onClick={() => setChannel(c)}
              >
                {c === "push" ? "Push" : c === "text" ? "Text" : "Email"}
              </button>
            ))}
          </div>
          <div className="col g2">
            {NOTIFICATION_ROWS.map((label) => (
              <div className="row between g3" style={{ minHeight: 48 }} key={label}>
                <span className="t16 grow">{label}</span>
                <button
                  type="button"
                  className={`tgl${toggles[label] ? " on" : ""}`}
                  role="switch"
                  aria-checked={toggles[label]}
                  aria-label={label}
                  onClick={() => setToggles((t) => ({ ...t, [label]: !t[label] }))}
                />
              </div>
            ))}
          </div>
        </section>

        {isStaff && (
          <section className="col g2" aria-label="Staff sign-in">
            <h2 className="t14 w7 c-ink2">Staff sign-in</h2>
            <button className="opt" type="button" onClick={() => setShowTwoFactor(true)}>
              <span className="col">
                <span className="t16 w7">Two-factor sign-in</span>
                <span className="t14 c-ink2">Not set up</span>
              </span>
              <Icon name="arrow" />
            </button>
          </section>
        )}

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

        <button className="btn btn-quiet btn-block" type="button" onClick={() => void logout()}>
          Sign out
        </button>
      </main>
    </>
  )
}
