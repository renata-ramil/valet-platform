// A decorative, deterministic QR-like pattern matching the design's
// own placeholder (R20-TwoFactor design screen). Not a real scannable QR code;
// the authenticator key is shown as real, enterable text alongside it.
export function FakeQr() {
  const cells: boolean[] = []
  let s = 17
  for (let r = 0; r < 21; r++) {
    for (let c = 0; c < 21; c++) {
      s = (s * 75 + 74) % 65537
      const finder = (r < 8 && c < 8) || (r < 8 && c > 12) || (r > 12 && c < 8)
      let on = false
      if (!finder) {
        if (r === 6 || c === 6) on = (r + c) % 2 === 0
        else on = s % 5 < 2
      }
      cells.push(on)
    }
  }
  return (
    <div className="qr" role="img" aria-label="QR code for your authenticator app">
      <div className="qg">
        {cells.map((on, i) => (
          <div className={on ? "qc on" : "qc"} key={i} />
        ))}
        <div className="fd" style={{ top: 0, left: 0 }}>
          <div className="fm">
            <div className="fc" />
          </div>
        </div>
        <div className="fd" style={{ top: 0, right: 0 }}>
          <div className="fm">
            <div className="fc" />
          </div>
        </div>
        <div className="fd" style={{ bottom: 0, left: 0 }}>
          <div className="fm">
            <div className="fc" />
          </div>
        </div>
      </div>
    </div>
  )
}
