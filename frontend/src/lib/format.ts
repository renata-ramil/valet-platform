export function formatClock(date: Date): string {
  const day = date.toLocaleDateString([], { weekday: "long" })
  const time = date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
  return `${day}, ${time}`
}

export function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
}

export function formatTimeNoLeadingZero(iso: string): string {
  return formatTime(iso).replace(/^0/, "")
}

const WEEKDAY_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
const WEEKDAY_LETTER = ["M", "T", "W", "T", "F", "S", "S"]

export function weekdayShort(index: number): string {
  return WEEKDAY_SHORT[index]
}

export function weekdayLetter(index: number): string {
  return WEEKDAY_LETTER[index]
}

export function describeWeekdays(weekdays: number[]): string {
  const sorted = [...weekdays].sort((a, b) => a - b)
  if (sorted.length === 5 && sorted.every((d, i) => d === i)) return "weekdays"
  if (sorted.length === 7) return "every day"
  if (sorted.length === 2 && sorted[0] === 5 && sorted[1] === 6) return "weekends"
  return sorted.map((d) => WEEKDAY_SHORT[d]).join(", ")
}

export function formatLocalTimeString(hhmm: string): string {
  const [hours, minutes] = hhmm.split(":").map(Number)
  const date = new Date()
  date.setHours(hours, minutes, 0, 0)
  return formatTime(date.toISOString())
}

// Money always comes from the server in integer cents; this only formats
// for display, it never computes an amount
export function formatCents(cents: number): string {
  const sign = cents < 0 ? "-" : ""
  const abs = Math.abs(cents)
  const dollars = Math.floor(abs / 100)
  const remainder = String(abs % 100).padStart(2, "0")
  return `${sign}$${dollars.toLocaleString("en-US")}.${remainder}`
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString([], { month: "short", day: "numeric" })
}

export function formatMonthYear(iso: string): string {
  return new Date(iso).toLocaleDateString([], { month: "long", year: "numeric" })
}
