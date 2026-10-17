import type { ReactNode } from "react"
import { Icon } from "./Icon"

export function TopbarHome({ right }: { right: ReactNode }) {
  return (
    <header className="topbar">
      <span className="wm" />
      {right}
    </header>
  )
}

export function Avatar({ name, onClick }: { name: string; onClick: () => void }) {
  const initials = name
    .split(" ")
    .map((p) => p[0])
    .join("")
    .slice(0, 2)
    .toUpperCase()
  return (
    <button className="avatar" type="button" aria-label={`Account, ${name}`} onClick={onClick}>
      {initials}
    </button>
  )
}

export function TopbarBack({
  title,
  onBack,
  right,
}: {
  title: string
  onBack: () => void
  right?: ReactNode
}) {
  return (
    <header className="topbar">
      <button className="btn btn-quiet ibtn" type="button" aria-label="Back" onClick={onBack}>
        <Icon name="arrow" rotate={180} />
      </button>
      <h1 className="ttl">{title}</h1>
      {right ? right : <div className="ibtn" aria-hidden="true" />}
    </header>
  )
}

export interface TabDef {
  key: string
  label: string
}

export function Tabbar({
  tabs,
  active,
  onChange,
  label,
}: {
  tabs: TabDef[]
  active: string
  onChange: (key: string) => void
  label: string
}) {
  return (
    <nav className="tabbar" aria-label={label}>
      {tabs.map((t) => (
        <button
          key={t.key}
          type="button"
          className={`tab${t.key === active ? " on" : ""}`}
          aria-current={t.key === active ? "page" : undefined}
          data-testid={`tab-${t.key}`}
          onClick={() => onChange(t.key)}
        >
          {t.label}
        </button>
      ))}
    </nav>
  )
}

export function PhoneFrame({
  theme = "th-l",
  topbar,
  tabbar,
  full = false,
  children,
}: {
  theme?: "th-l" | "th-d"
  topbar: ReactNode
  tabbar?: ReactNode
  full?: boolean
  children: ReactNode
}) {
  return (
    <div className={`vk phone ${theme}`}>
      {topbar}
      <main className={full ? "pbody-full" : "pbody"}>
        <div style={{ overflowY: "auto", height: "100%" }}>{children}</div>
      </main>
      {tabbar}
    </div>
  )
}
