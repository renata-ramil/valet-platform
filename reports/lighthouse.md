# Accessibility and performance pass

Run with Lighthouse 13.5.0 (headless Chrome) against the production build
(`npm run build`) of the resident app's login screen, served statically and
pointed at a locally running backend seeded with `scripts/seed_demo.py`.
Full HTML report: `reports/lighthouse-resident-login.html`. Raw numbers,
not hand-typed.

| Category | Score |
|---|---|
| Performance | 99 |
| Accessibility | 100 |
| Best practices | 96 |
| SEO | 63 |

Core Web Vitals on this page: first contentful paint 1.4s, largest
contentful paint 2.0s, total blocking time 0ms, cumulative layout shift 0.

## What changed during this pass

The first run scored accessibility 96 and SEO 82, with two real,
fixable findings:

- **`landmark-one-main`**: no page had a `<main>` landmark. Fixed by
  wrapping each app's page content (resident, valet, manager, support,
  and both the login and MFA-code screens) in a `<main>` element in
  `frontend/src/App.tsx` and `frontend/src/pages/AuthPage.tsx`.
- **`meta-description`**: the page had no meta description. Fixed in
  `frontend/index.html`.

Also added while in there, not flagged by Lighthouse but worth doing:

- A visible `:focus-visible` ring on every interactive element
  (`frontend/src/index.css`), since Tailwind's reset removes the browser
  default and the app had no replacement, meaning keyboard users had no
  way to see where focus was.
- A `prefers-reduced-motion` media query that collapses animation and
  transition durations to near-zero for anyone who has that OS setting on.

After the fix, accessibility reached 100. SEO dropped from 82 to 63
after adding `frontend/public/robots.txt` with `Disallow: /`: Lighthouse's
`is-crawlable` audit penalizes blocking search engines, but this app sits
entirely behind a login and should not be indexed, so that score is low
on purpose and is not being further "fixed."

## Known, accepted finding

`errors-in-console` (best practices) flags one console entry: a 401 from
`GET /auth/me` on page load. This is the app's own auth-check correctly
reporting "not logged in yet" before the login form renders; it is
expected behavior on every fresh page load, not a bug, and is not
something to suppress.

## Not covered by this pass

This Lighthouse run covers the login screen only (the one page reachable
without a seeded session in a scripted run). The resident home screen,
schedule page, valet queue, and manager board were checked manually in
the browser during feature verification throughout this project (keyboard
tab order, color contrast against Tailwind's slate palette, and the
`prefers-reduced-motion` behavior), but do not have their own saved
Lighthouse reports in this pass; a follow-up could script a login and run
Lighthouse against each authenticated route.
