import { test, expect } from "@playwright/test"
import path from "node:path"
import { uniqueEmail, registerAndLogin, managerCreateCarForResident } from "./helpers"

const SCREENS_DIR = path.resolve(import.meta.dirname, "../../reports/screens")

test.describe("schedule flow", () => {
  test("create a weekday schedule, see next three dates, skip tomorrow", async ({
    page,
    request,
  }) => {
    const email = uniqueEmail("schedule-resident")
    const password = "residentpass123"

    await page.goto("/")
    await page.getByTestId("auth-mode-register").click()
    await page.getByTestId("invite-code-input").fill("E2E-RESIDENT")
    await page.getByTestId("full-name-input").fill("Schedule Resident")
    await page.getByTestId("email-input").fill(email)
    await page.getByTestId("password-input").fill(password)
    await page.getByTestId("auth-submit").click()

    await expect(page.getByTestId("home-page")).toBeVisible()

    const cookies = await page.context().cookies()
    const sessionCookie = cookies.find((c) => c.name === "session_id")?.value
    const meResponse = await request.get("http://localhost:8001/auth/me", {
      headers: { Cookie: `session_id=${sessionCookie}` },
    })
    const me = await meResponse.json()

    const managerAuth = await registerAndLogin(request, "E2E-MANAGER", "E2E Manager")
    await managerCreateCarForResident(request, managerAuth, me.id, {
      make: "Subaru",
      model: "Outback",
      color: "green",
      license_plate: "E2E002",
    })

    await page.getByTestId("tab-schedule").click()
    await expect(page.getByTestId("schedule-page")).toBeVisible()

    await page.getByTestId("add-schedule-button").click()
    await page.getByTestId("schedule-car-option").first().click()
    await page.getByTestId("save-schedule-button").click()

    const row = page.getByTestId("schedule-row")
    await expect(row).toBeVisible()
    await expect(row).toContainText("Weekdays at 8:00 AM")
    await page.screenshot({ path: path.join(SCREENS_DIR, "schedule-created.png") })

    const nextDates = page.locator('[data-testid^="next-date-"]')
    await expect(nextDates).toHaveCount(3)

    // The backend accepts the skip-tomorrow call and records a real
    // ScheduleException; there is no endpoint yet to read exceptions back,
    // so the main screen's "next three dates" list (computed client-side
    // from the weekday pattern alone) does not reflect it, a known,
    // documented gap rather than something to assert against here
    const [skipResponse] = await Promise.all([
      page.waitForResponse((r) => r.url().includes("/skip-tomorrow")),
      page.getByTestId("skip-tomorrow-button").click(),
    ])
    expect(skipResponse.ok()).toBe(true)
    await page.screenshot({ path: path.join(SCREENS_DIR, "schedule-skip-tomorrow.png") })
  })
})
