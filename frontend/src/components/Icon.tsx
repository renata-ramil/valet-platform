const PATHS: Record<string, string> = {
  car: "M3 17v-5l2.5-5h13L21 12v5M3 12h18",
  clock: "M12 7v5l3 2",
  repeat: "M4 11V9a3 3 0 0 1 3-3h11M15 3l3 3-3 3M20 13v2a3 3 0 0 1-3 3H6M9 21l-3-3 3-3",
  key: "M12 12h9M18 12v3M15 12v2",
  chat: "M4 5h16v11H10l-5 4v-4H4z",
  check: "M5 12.5l4.5 4.5L19 7.5",
  arrow: "M5 12h14M13 6l6 6-6 6",
  plus: "M12 5v14M5 12h14",
  minus: "M5 12h14",
  "eye-off": "M3 3l18 18M10.6 10.6a3 3 0 0 0 4.24 4.24M6.6 6.7C4.1 8.3 2 12 2 12s4 7 10 7c1.8 0 3.4-.5 4.8-1.3M9.9 5.2A10 10 0 0 1 12 5c6 0 10 7 10 7s-.8 1.6-2.3 3.2",
}

export function Icon({
  name,
  className = "g",
  rotate,
}: {
  name: keyof typeof PATHS | "car" | "clock" | "eye"
  className?: string
  rotate?: 45 | 180
}) {
  const cls = rotate ? `${className} rot${rotate}` : className
  if (name === "eye") {
    return (
      <svg className={cls} viewBox="0 0 24 24" aria-hidden="true">
        <path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7z" />
        <circle cx="12" cy="12" r="3" />
      </svg>
    )
  }
  if (name === "car") {
    return (
      <svg className={cls} viewBox="0 0 24 24" aria-hidden="true">
        <path d="M3 17v-5l2.5-5h13L21 12v5" />
        <path d="M3 12h18" />
        <circle cx="7.5" cy="17" r="1.5" />
        <circle cx="16.5" cy="17" r="1.5" />
      </svg>
    )
  }
  if (name === "clock") {
    return (
      <svg className={cls} viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5l3 2" />
      </svg>
    )
  }
  if (name === "key") {
    return (
      <svg className={cls} viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="8" cy="12" r="4" />
        <path d="M12 12h9" />
        <path d="M18 12v3" />
        <path d="M15 12v2" />
      </svg>
    )
  }
  return (
    <svg className={cls} viewBox="0 0 24 24" aria-hidden="true">
      <path d={PATHS[name]} />
    </svg>
  )
}
