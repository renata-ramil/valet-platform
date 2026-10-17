import { Tabbar } from "./PhoneFrame"

export type ResidentTab = "home" | "schedule" | "billing" | "help"

const TABS: { key: ResidentTab; label: string }[] = [
  { key: "home", label: "Home" },
  { key: "schedule", label: "Schedule" },
  { key: "billing", label: "Billing" },
  { key: "help", label: "Help" },
]

export function ResidentTabbar({
  active,
  onChange,
}: {
  active: ResidentTab
  onChange: (tab: ResidentTab) => void
}) {
  return <Tabbar tabs={TABS} active={active} onChange={(k) => onChange(k as ResidentTab)} label="Main" />
}
