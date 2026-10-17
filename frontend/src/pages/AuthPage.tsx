import { useEffect, useRef, useState } from "react"
import { useAuth } from "../context/AuthContext"
import { ApiError } from "../lib/apiClient"
import { Scene } from "../components/Scene"
import { Icon } from "../components/Icon"
import { formatTime } from "../lib/format"

// Matching backend/app/security.py's LOGIN_FAILURE_WINDOW (15 minutes) and
// ACCOUNT_LOCKOUT_THRESHOLD (5 attempts). The 429 response carries no
// retry-after value, so this starts the countdown from the moment the
// lockout response arrives, a client side approximation of the real window.
const LOCKOUT_MINUTES = 15

function Lockout({ lockoutUntil, onExpire, onBack }: { lockoutUntil: number; onExpire: () => void; onBack: () => void }) {
  const [now, setNow] = useState(() => Date.now())
  const expiredRef = useRef(false)

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [])

  const remainingMs = Math.max(0, lockoutUntil - now)
  const minutes = Math.floor(remainingMs / 60000)
  const seconds = Math.floor((remainingMs % 60000) / 1000)
  const clock = `${minutes}:${String(seconds).padStart(2, "0")}`

  useEffect(() => {
    if (remainingMs === 0 && !expiredRef.current) {
      expiredRef.current = true
      onExpire()
    }
  }, [remainingMs, onExpire])

  return (
    <div className="vk phone th-l">
      <div className="topbar">
        <span className="wm" />
      </div>
      <div className="pbody-full">
        <div className="col" style={{ height: "100%", paddingBottom: "var(--sp-6)" }}>
          <div className="col g2">
            <h1 className="t28 w7">Sign-in is paused for a few minutes</h1>
            <p className="t16 c-ink2">
              After 5 wrong passwords we pause sign-in to keep your account safe. It happens to
              everyone, and nothing is wrong with your account.
            </p>
          </div>

          <div className="card-flat col g2" style={{ marginTop: "var(--sp-6)" }}>
            <p className="t20 w7">Try again at {formatTime(new Date(lockoutUntil).toISOString())}</p>
            <p className="t64 w7" aria-label={`${minutes} minutes ${seconds} seconds left`}>
              {clock}
            </p>
            <p className="t14 c-ink2">minutes and seconds until you can try again</p>
          </div>

          <p className="t16 c-ink2" style={{ marginTop: "var(--sp-6)" }}>
            Not sure of the password? You can reset it by email right now, or ask the front desk to
            help.
          </p>

          <div className="col g3" style={{ marginTop: "auto" }}>
            <button className="btn btn-primary btn-xl is-disabled" type="button" disabled>
              Sign in
            </button>
            <button className="btn btn-secondary btn-block" type="button" onClick={onBack}>
              Reset password by email
            </button>
            <button className="btn btn-quiet btn-block" type="button" onClick={onBack}>
              <Icon name="chat" />
              Message the front desk
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

export function AuthPage() {
  const { login, verifyTotp, register } = useAuth()
  const [mode, setMode] = useState<"login" | "register">("login")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [fullName, setFullName] = useState("")
  const [inviteCode, setInviteCode] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const [mfaChallengeId, setMfaChallengeId] = useState<string | null>(null)
  const [mfaCode, setMfaCode] = useState("")
  const [lockoutUntil, setLockoutUntil] = useState<number | null>(null)

  const submit = async () => {
    setError(null)
    setSubmitting(true)
    try {
      if (mode === "login") {
        const { mfaChallengeId: challengeId } = await login(email, password)
        if (challengeId) setMfaChallengeId(challengeId)
      } else {
        await register({ invite_code: inviteCode, email, password, full_name: fullName })
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) {
        setLockoutUntil(Date.now() + LOCKOUT_MINUTES * 60_000)
      } else {
        setError(err instanceof ApiError ? err.message : "Something went wrong")
      }
    } finally {
      setSubmitting(false)
    }
  }

  const submitMfaCode = async () => {
    if (!mfaChallengeId) return
    setError(null)
    setSubmitting(true)
    try {
      await verifyTotp(mfaChallengeId, mfaCode)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong")
    } finally {
      setSubmitting(false)
    }
  }

  if (lockoutUntil !== null) {
    return (
      <Lockout
        lockoutUntil={lockoutUntil}
        onExpire={() => setLockoutUntil(null)}
        onBack={() => setLockoutUntil(null)}
      />
    )
  }

  if (mfaChallengeId) {
    const digits = mfaCode.padEnd(6, " ").split("")
    return (
      <div className="vk phone th-l" data-testid="mfa-page">
        <header className="topbar">
          <div className="ttl">Enter your code</div>
        </header>
        <main className="pbody-full col g4" style={{ paddingTop: "var(--sp-6)" }}>
          <p className="t16 c-ink2">Open your authenticator app for a 6 digit code</p>
          <input
            data-testid="mfa-code-input"
            value={mfaCode}
            onChange={(e) => setMfaCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
            style={{ position: "absolute", opacity: 0, pointerEvents: "none" }}
            autoFocus
          />
          <div className="code jcenter row" aria-hidden="true">
            {digits.map((d, i) => (
              <div key={i} className={`cb${i === mfaCode.length ? " is-focus" : ""}`}>
                {d.trim()}
              </div>
            ))}
          </div>
          {error && (
            <p className="hint err tc" data-testid="auth-error">
              {error}
            </p>
          )}
          <button
            type="button"
            data-testid="mfa-submit"
            className="btn btn-primary btn-xl"
            disabled={submitting || mfaCode.length < 6}
            onClick={submitMfaCode}
          >
            Verify
          </button>
        </main>
      </div>
    )
  }

  if (mode === "register") {
    return (
      <div className="vk phone th-l">
        <div className="topbar">
          <button className="btn btn-quiet ibtn" type="button" aria-label="Back" onClick={() => setMode("login")}>
            <Icon name="arrow" rotate={180} />
          </button>
          <span className="wm" />
          <span className="none" style={{ width: 48 }} />
        </div>
        <div className="pbody-full">
          <div className="col" style={{ height: "100%", paddingBottom: "var(--sp-6)" }}>
            <div className="col g2">
              <p className="t14 w5 c-ink2">Step 1 of 2</p>
              <div className="row g2" aria-hidden="true">
                <div className="seg2 on" />
                <div className="seg2" />
              </div>
            </div>

            <div className="col g2" style={{ marginTop: "var(--sp-6)" }}>
              <h1 className="t28 w7">Create your account</h1>
              <p className="t16 c-ink2">Your building gives you an invite code. Your manager adds your car next.</p>
            </div>

            <div className="field" style={{ marginTop: "var(--sp-6)" }}>
              <label className="lbl" htmlFor="full-name">Full name</label>
              <input
                className="inp"
                id="full-name"
                data-testid="full-name-input"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
              />
            </div>
            <div className="field" style={{ marginTop: "var(--sp-4)" }}>
              <label className="lbl" htmlFor="email">Email</label>
              <input
                className="inp"
                id="email"
                type="email"
                data-testid="email-input"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            <div className="field" style={{ marginTop: "var(--sp-4)" }}>
              <label className="lbl" htmlFor="pw">Password</label>
              <div className="pw-wrap">
                <input
                  className="inp"
                  id="pw"
                  type={showPassword ? "text" : "password"}
                  data-testid="password-input"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  aria-describedby="pw-hint"
                />
                <button
                  type="button"
                  className="pw-toggle"
                  onClick={() => setShowPassword((v) => !v)}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                >
                  <Icon name={showPassword ? "eye-off" : "eye"} />
                </button>
              </div>
              <p className="hint" id="pw-hint">At least 8 characters</p>
            </div>
            <div className="field" style={{ marginTop: "var(--sp-4)" }}>
              <label className="lbl" htmlFor="code">Building invite code</label>
              <input
                className={`inp${error ? " is-error" : ""}`}
                id="code"
                data-testid="invite-code-input"
                value={inviteCode}
                onChange={(e) => setInviteCode(e.target.value)}
                aria-describedby="code-hint"
              />
              {error && (
                <p className="hint err" id="code-hint" data-testid="auth-error">
                  {error}
                </p>
              )}
            </div>

            <div className="col g3" style={{ marginTop: "auto" }}>
              <button
                type="button"
                className="btn btn-primary btn-xl"
                data-testid="auth-submit"
                disabled={submitting}
                onClick={submit}
              >
                Create account
              </button>
              <button type="button" className="btn btn-quiet btn-block" onClick={() => setMode("login")}>
                I already have an account
              </button>
            </div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="vk phone th-l" data-testid="auth-page">
      <div className="topbar">
        <span className="wm" />
      </div>
      <div className="pbody-full">
        <div className="col" style={{ height: "100%", paddingBottom: "var(--sp-6)" }}>
          <Scene height={120} />

          <div className="col g2" style={{ marginTop: "var(--sp-6)" }}>
            <h1 className="t28 w7">Welcome back to Harbor Tower</h1>
            <p className="t16 c-ink2">Sign in to call your car to the lobby.</p>
          </div>

          <div className="field" style={{ marginTop: "var(--sp-6)" }}>
            <label className="lbl" htmlFor="email">Email</label>
            <input
              className="inp"
              id="email"
              type="email"
              data-testid="email-input"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>

          <div className="field" style={{ marginTop: "var(--sp-4)" }}>
            <label className="lbl" htmlFor="pw">Password</label>
            <div className="pw-wrap">
              <input
                className={`inp${error ? " is-error" : ""}`}
                id="pw"
                type={showPassword ? "text" : "password"}
                data-testid="password-input"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                aria-invalid={Boolean(error)}
                aria-describedby="pw-hint"
              />
              <button
                type="button"
                className="pw-toggle"
                onClick={() => setShowPassword((v) => !v)}
                aria-label={showPassword ? "Hide password" : "Show password"}
              >
                <Icon name={showPassword ? "eye-off" : "eye"} />
              </button>
            </div>
            {error && (
              <p className="hint err" id="pw-hint" data-testid="auth-error">
                {error}
              </p>
            )}
          </div>

          <button className="btn btn-quiet" type="button" style={{ marginTop: "var(--sp-2)", alignSelf: "flex-start" }}>
            Forgot password
          </button>

          <div className="col g3" style={{ marginTop: "auto" }}>
            <button
              type="button"
              className="btn btn-primary btn-xl"
              data-testid="auth-submit"
              disabled={submitting}
              onClick={submit}
            >
              Sign in
            </button>
            <button type="button" className="btn btn-secondary btn-block" data-testid="auth-mode-register" onClick={() => setMode("register")}>
              Create an account
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
