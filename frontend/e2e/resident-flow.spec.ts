import { test, expect } from "@playwright/test"
import path from "node:path"
import { uniqueEmail, registerAndLogin, authHeaders, managerCreateCarForResident } from "./helpers"

const SCREENS_DIR = path.resolve(import.meta.dirname, "../../reports/screens")

test.describe("resident flow", () => {
  test("register, a manager adds the car, bring my car, watch status move to delivered", async ({
    page,
    request,
  }) => {
    const email = uniqueEmail("resident")
    const password = "residentpass123"

    await page.goto("/")
    await page.getByTestId("auth-mode-register").click()
    await page.getByTestId("invite-code-input").fill("E2E-RESIDENT")
    await page.getByTestId("full-name-input").fill("E2E Resident")
    await page.getByTestId("email-input").fill(email)
    await page.getByTestId("password-input").fill(password)
    await page.getByTestId("auth-submit").click()

    await expect(page.getByTestId("home-page")).toBeVisible()

    // Residents can no longer add their own car (fleet ownership belongs
    // to managers): a manager creates it through the real API
    const cookies = await page.context().cookies()
    const sessionCookie = cookies.find((c) => c.name === "session_id")?.value
    const meResponse = await request.get("http://localhost:8001/auth/me", {
      headers: { Cookie: `session_id=${sessionCookie}` },
    })
    const me = await meResponse.json()

    const managerAuth = await registerAndLogin(request, "E2E-MANAGER", "E2E Manager")
    await managerCreateCarForResident(request, managerAuth, me.id, {
      make: "Honda",
      model: "Civic",
      color: "silver",
      license_plate: "E2E001",
    })

    // Home refetches cars on reload and auto-selects the resident's only car
    await page.reload()
    await expect(page.getByTestId("home-page")).toBeVisible()
    await expect(page.getByTestId("bring-my-car")).toBeEnabled({ timeout: 10_000 })
    await page.getByTestId("bring-my-car").click()

    await expect(page.getByTestId("status-label")).toContainText("Ready by", { timeout: 10_000 })
    await expect(page.locator(".pl li.cur")).toHaveText("Called")
    await page.screenshot({ path: path.join(SCREENS_DIR, "home-called.png") })

    // Find the request id through the API using the resident's own session cookie
    const residentRequestsResponse = await request.get("http://localhost:8001/requests", {
      headers: { Cookie: `session_id=${sessionCookie}` },
    })
    const residentRequests = await residentRequestsResponse.json()
    const ourRequest = residentRequests.find((r: { owner_id: string }) => r.owner_id === me.id)
    expect(ourRequest).toBeTruthy()

    // Drive the transitions directly through the API, as a valet would, and
    // measure the real SSE latency from state change to UI update
    const valetAuth = await registerAndLogin(request, "E2E-VALET", "E2E Valet")
    for (const target of ["assigned", "retrieving"]) {
      await request.post(`http://localhost:8001/requests/${ourRequest.id}/transition`, {
        headers: authHeaders(valetAuth),
        data: { target_state: target },
      })
    }

    const latencyStart = Date.now()
    await request.post(`http://localhost:8001/requests/${ourRequest.id}/transition`, {
      headers: authHeaders(valetAuth),
      data: { target_state: "en_route" },
    })
    await expect(page.getByTestId("status-label")).toContainText("On the way", { timeout: 10_000 })
    const latencyMs = Date.now() - latencyStart
    console.log(`SSE latency from state change to UI update: ${latencyMs}ms`)
    await page.screenshot({ path: path.join(SCREENS_DIR, "home-on-the-way.png") })

    await request.post(`http://localhost:8001/requests/${ourRequest.id}/transition`, {
      headers: authHeaders(valetAuth),
      data: { target_state: "delivered" },
    })

    // Delivered is now the final state: no handoff code, no "I'm home"
    // action, nothing left for the resident to do
    await expect(page.getByTestId("status-label")).toContainText("Delivered", { timeout: 10_000 })
    await expect(page.getByTestId("im-home")).toHaveCount(0)
    await expect(page.getByText(/handoff/i)).toHaveCount(0)
    await page.screenshot({ path: path.join(SCREENS_DIR, "home-delivered.png") })
  })
})
