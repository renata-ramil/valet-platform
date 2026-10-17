import { useCallback, useEffect, useState } from "react"

export type ThemeName = "th-l" | "th-d"

const STORAGE_PREFIX = "valet.theme."

// One stored preference per surface (resident, valet, manager), since the
// design ships dark mode as a first-class, user-chosen toggle rather than a
// single global switch. The valet app still defaults to dark.
export function useTheme(surface: "resident" | "valet" | "manager", initial: ThemeName): [ThemeName, () => void] {
  const key = STORAGE_PREFIX + surface
  const [theme, setTheme] = useState<ThemeName>(() => {
    try {
      const stored = localStorage.getItem(key)
      if (stored === "th-l" || stored === "th-d") return stored
    } catch {
      // ignoring unavailable storage, falling back to the surface default
    }
    return initial
  })

  useEffect(() => {
    try {
      localStorage.setItem(key, theme)
    } catch {
      // per-viewer convenience only, fine to drop if storage is unavailable
    }
  }, [key, theme])

  const toggle = useCallback(() => {
    setTheme((t) => (t === "th-l" ? "th-d" : "th-l"))
  }, [])

  return [theme, toggle]
}
