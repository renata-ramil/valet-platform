// M29 payment provider outage: shown instead of a blank screen whenever a
// billing query fails with a 5xx or a network error. Cars and requests are
// never affected, so the copy says so plainly.
export function OutageBanner() {
  return (
    <div className="banner" role="alert">
      <span>
        <span className="t">Our payment provider is having trouble.</span> Card payments may be
        delayed. Cars and requests are not affected.
      </span>
    </div>
  )
}

// M30 read-only support role: every money-moving control stays visible and
// disabled rather than hidden, with this line explaining why
export function ReadOnlyNotice() {
  return (
    <div className="t16 w7">Your role can view billing and cannot change it. Ask an operations manager.</div>
  )
}
