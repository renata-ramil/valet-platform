import { useEffect, useState } from "react"
import { formatClock } from "./format"

export function useClock(): string {
  const [label, setLabel] = useState(() => formatClock(new Date()))
  useEffect(() => {
    const id = setInterval(() => setLabel(formatClock(new Date())), 30_000)
    return () => clearInterval(id)
  }, [])
  return label
}
