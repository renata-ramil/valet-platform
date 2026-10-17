import type { ReactNode } from "react"

export interface NavItem {
  key: string
  label: string
}

const NAV_ITEMS: NavItem[] = [
  { key: "live", label: "Live board" },
  { key: "garage", label: "Garage map" },
  { key: "demand", label: "Demand and staffing" },
  { key: "whatif", label: "What-if" },
  { key: "roster", label: "Roster and shifts" },
  { key: "residents", label: "Residents and cars" },
  { key: "billing", label: "Billing" },
  { key: "plans", label: "Plans" },
  { key: "audit", label: "Audit and security" },
  { key: "tickets", label: "Tickets" },
]

export function ManagerFrame({
  active,
  onChange,
  buildingName,
  managerName,
  managerRole,
  theme = "th-l",
  onToggleTheme,
  children,
}: {
  active: string
  onChange: (key: string) => void
  buildingName: string
  managerName: string
  managerRole: string
  theme?: "th-l" | "th-d"
  onToggleTheme?: () => void
  children: ReactNode
}) {
  return (
    <div className={`vk mgr ${theme}`} data-testid="manager-page">
      <nav className="side" aria-label="Main">
        <div className="px4 py2">
          <span className="wm" />
        </div>
        <div className="t14 c-ink2 px4">{buildingName}</div>
        {NAV_ITEMS.map((item) => (
          <button
            key={item.key}
            type="button"
            className={`nav-i${item.key === active ? " on" : ""}`}
            data-testid={`nav-${item.key}`}
            onClick={() => onChange(item.key)}
          >
            {item.label}
          </button>
        ))}
        <div className="grow" />
        {onToggleTheme && (
          <button
            type="button"
            className="opt"
            data-testid="manager-dark-mode-toggle"
            onClick={onToggleTheme}
          >
            <span>Dark mode</span>
            <span className={`tgl${theme === "th-d" ? " on" : ""}`} role="switch" aria-checked={theme === "th-d"} />
          </button>
        )}
        <div className="px4 py2">
          <div className="t16 w7">{managerName}</div>
          <div className="t14 c-ink2">{managerRole}</div>
        </div>
      </nav>
      <main className="main">{children}</main>
    </div>
  )
}
