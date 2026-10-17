export function Scene({ height = 128 }: { height?: number }) {
  return (
    <div
      className="scene"
      style={{ height, borderRadius: "var(--r3)" }}
      aria-hidden="true"
    >
      <div className="sun" style={{ left: 232, top: 24, width: 48, height: 48 }} />
      <div className="dn d1" style={{ left: 0, bottom: 0, width: 240, height: 64 }} />
      <div className="dn d2" style={{ right: 0, bottom: 0, width: 264, height: 48 }} />
      <div className="dn d3" style={{ left: 64, bottom: 0, width: 192, height: 32 }} />
    </div>
  )
}
