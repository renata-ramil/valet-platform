import { useState } from "react"
import { useAuth } from "./context/AuthContext"
import { AuthPage } from "./pages/AuthPage"
import { HomePage } from "./pages/HomePage"
import { SchedulePage } from "./pages/SchedulePage"
import { BillingPage } from "./pages/BillingPage"
import { SupportPage } from "./pages/SupportPage"
import { AccountPage } from "./pages/AccountPage"
import { BookAheadPage } from "./pages/BookAheadPage"
import { ValetPage } from "./pages/ValetPage"
import { ManagerPage } from "./pages/ManagerPage"
import type { ResidentTab } from "./components/ResidentTabbar"
import { useTheme } from "./lib/useTheme"

function ResidentApp() {
  const [tab, setTab] = useState<ResidentTab>("home")
  const [accountOpen, setAccountOpen] = useState(false)
  const [bookAheadOpen, setBookAheadOpen] = useState(false)
  const [theme, toggleTheme] = useTheme("resident", "th-l")
  const openAccount = () => setAccountOpen(true)

  if (accountOpen) {
    return (
      <div className={`vk phone ${theme}`}>
        <AccountPage onBack={() => setAccountOpen(false)} theme={theme} onToggleTheme={toggleTheme} />
      </div>
    )
  }

  if (bookAheadOpen) {
    return (
      <div className={`vk phone ${theme}`}>
        <BookAheadPage onBack={() => setBookAheadOpen(false)} />
      </div>
    )
  }

  return (
    <div className={`vk phone ${theme}`}>
      {tab === "home" && (
        <HomePage
          onNavigate={setTab}
          onOpenAccount={openAccount}
          onBookAhead={() => setBookAheadOpen(true)}
        />
      )}
      {tab === "schedule" && <SchedulePage onNavigate={setTab} />}
      {tab === "billing" && <BillingPage onNavigate={setTab} onOpenAccount={openAccount} />}
      {tab === "help" && <SupportPage onNavigate={setTab} />}
    </div>
  )
}

function ValetApp() {
  const [theme, toggleTheme] = useTheme("valet", "th-d")
  return (
    <div className={`vk phone ${theme}`}>
      <ValetPage theme={theme} onToggleTheme={toggleTheme} />
    </div>
  )
}

function App() {
  const { user, loading } = useAuth()

  if (loading) {
    return (
      <div className="vk phone th-l" style={{ alignItems: "center", justifyContent: "center", display: "flex" }}>
        <p className="t16 c-ink2">Loading</p>
      </div>
    )
  }

  if (!user) {
    return <AuthPage />
  }

  if (user.role === "valet") {
    return <ValetApp />
  }
  if (user.role === "manager") {
    return <ManagerPage />
  }
  if (user.role === "support") {
    return (
      <div className="vk phone th-l">
        <SupportPage />
      </div>
    )
  }
  return <ResidentApp />
}

export default App
