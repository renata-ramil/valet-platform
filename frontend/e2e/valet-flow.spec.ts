import { test, expect } from "@playwright/test"
import path from "node:path"
import { uniqueEmail, registerAndLogin, managerCreateCarForResident } from "./helpers"

const SCREENS_DIR = path.resolve(import.meta.dirname, "../../reports/screens")

test.describe("valet and manager flow", () => {
  test("resident requests, valet advances on a second context, resident sees updates, valet reports Car arrived", async ({
    browser,
    request,
  }) => {
    const residentContext = await browser.newContext({ viewport: { width: 390, height: 844 } })
    const valetContext = await browser.newContext({ viewport: { width: 390, height: 844 } })
    const residentPage = await residentContext.newPage()
    const valetPage = await valetContext.newPage()

    const residentEmail = uniqueEmail("resident")
    const valetEmail = uniqueEmail("valet")
    const password = "testpass123"
    const plate = "VF001"

    // Resident registers; a manager adds their car (fleet ownership belongs
    // to managers, residents can no longer add their own)
    await residentPage.goto("/")
    await residentPage.getByTestId("auth-mode-register").click()
    await residentPage.getByTestId("invite-code-input").fill("E2E-RESIDENT")
    await residentPage.getByTestId("full-name-input").fill("Valet Flow Resident")
    await residentPage.getByTestId("email-input").fill(residentEmail)
    await residentPage.getByTestId("password-input").fill(password)
    await residentPage.getByTestId("auth-submit").click()
    await expect(residentPage.getByTestId("home-page")).toBeVisible()

    const residentCookies = await residentPage.context().cookies()
    const residentSessionCookie = residentCookies.find((c) => c.name === "session_id")?.value
    const meResponse = await request.get("http://localhost:8001/auth/me", {
      headers: { Cookie: `session_id=${residentSessionCookie}` },
    })
    const me = await meResponse.json()

    const managerAuth = await registerAndLogin(request, "E2E-MANAGER", "E2E Manager")
    await managerCreateCarForResident(request, managerAuth, me.id, {
      make: "Tesla",
      model: "Model 3",
      color: "white",
      license_plate: plate,
    })

    await residentPage.reload()
    await expect(residentPage.getByTestId("home-page")).toBeVisible()
    await expect(residentPage.getByTestId("bring-my-car")).toBeEnabled({ timeout: 10_000 })
    await residentPage.getByTestId("bring-my-car").click()
    await expect(residentPage.getByTestId("status-label")).toContainText("Ready by", {
      timeout: 10_000,
    })
    await expect(residentPage.locator(".pl li.cur")).toHaveText("Called")

    // Valet registers and sees the request in their queue
    await valetPage.goto("/")
    await valetPage.getByTestId("auth-mode-register").click()
    await valetPage.getByTestId("invite-code-input").fill("E2E-VALET")
    await valetPage.getByTestId("full-name-input").fill("Valet Flow Valet")
    await valetPage.getByTestId("email-input").fill(valetEmail)
    await valetPage.getByTestId("password-input").fill(password)
    await valetPage.getByTestId("auth-submit").click()
    await expect(valetPage.getByTestId("valet-page")).toBeVisible()

    await expect(valetPage.getByTestId("queue-card").first()).toBeVisible({ timeout: 10_000 })
    await valetPage.screenshot({ path: path.join(SCREENS_DIR, "valet-queue.png") })

    // Advance queued -> assigned -> retrieving -> en_route -> delivered, one
    // tap at a time, each waiting for the queue to refetch before the next
    for (let i = 0; i < 3; i++) {
      await valetPage.getByTestId("advance-button").first().click()
      await valetPage.waitForResponse((r) => r.url().includes("/transition"))
      await valetPage.waitForResponse((r) => r.url().includes("/valet/queue"))
    }

    // Resident sees "On the way" live, without reloading
    await expect(residentPage.getByTestId("status-label")).toContainText("On the way", {
      timeout: 10_000,
    })

    await valetPage.getByTestId("advance-button").first().click()

    // Delivered is the final state now: no handoff code, no "I'm home"
    await expect(residentPage.getByTestId("status-label")).toContainText("Delivered", {
      timeout: 10_000,
    })
    await expect(residentPage.getByTestId("im-home")).toHaveCount(0)
    await residentPage.screenshot({ path: path.join(SCREENS_DIR, "home-delivered.png") })

    // Car arrived: the resident is back, the valet searches the plate,
    // matches it, and creates the park task, no handoff code involved
    await valetPage.getByTestId("car-arrived-button").click()
    await valetPage.getByTestId("car-arrived-search").fill(plate)
    await expect(valetPage.getByTestId("car-arrived-result")).toBeVisible({ timeout: 10_000 })
    await valetPage.getByTestId("car-arrived-result").click()
    await valetPage.getByTestId("create-park-task").click()

    await expect(valetPage.getByTestId("queue-card").first()).toBeVisible({ timeout: 10_000 })
    await valetPage.screenshot({ path: path.join(SCREENS_DIR, "valet-car-arrived.png") })

    // Complete the park task
    await valetPage.getByTestId("advance-button").first().click()
    await valetPage.waitForResponse((r) => r.url().includes("/complete-park"))

    await residentContext.close()
    await valetContext.close()
  })

  test("manager sees the board and adds a car through the Add car wizard", async ({ browser, request }) => {
    const residentEmail = uniqueEmail("manager-flow-resident")
    const managerEmail = uniqueEmail("manager")
    const password = "testpass123"

    const residentAuth = await registerAndLogin(request, "E2E-RESIDENT", "Manager Flow Resident")
    await request.post("http://localhost:8001/auth/register", {
      data: {
        invite_code: "E2E-MANAGER",
        email: managerEmail,
        password,
        full_name: "E2E Manager",
      },
    })

    const managerContext = await browser.newContext({ viewport: { width: 1280, height: 900 } })
    const managerPage = await managerContext.newPage()
    await managerPage.goto("/")
    await managerPage.getByTestId("email-input").fill(managerEmail)
    await managerPage.getByTestId("password-input").fill(password)
    await managerPage.getByTestId("auth-submit").click()
    await expect(managerPage.getByTestId("manager-page")).toBeVisible()
    await managerPage.screenshot({ path: path.join(SCREENS_DIR, "manager-board.png") })

    await managerPage.getByTestId("nav-residents").click()
    await managerPage.getByTestId("open-add-car").click()

    await managerPage.getByTestId("ac-resident-search").fill("Manager Flow Resident")
    await expect(managerPage.getByTestId("ac-resident-option").first()).toBeVisible({
      timeout: 10_000,
    })
    await managerPage.getByTestId("ac-resident-option").first().click()
    await managerPage.getByTestId("ac-step1-continue").click()

    await managerPage.getByTestId("ac-plate-input").fill("MGR001")
    await managerPage.getByTestId("ac-make-input").fill("Ford")
    await managerPage.getByTestId("ac-model-input").fill("Focus")
    await managerPage.getByTestId("ac-color-input").fill("blue")
    await managerPage.getByTestId("ac-step2-continue").click()

    await managerPage.getByTestId("ac-submit").click()
    await expect(managerPage.getByTestId("ac-done")).toBeVisible({ timeout: 10_000 })
    await managerPage.screenshot({ path: path.join(SCREENS_DIR, "manager-add-car-success.png") })
    await managerPage.getByTestId("ac-done").click()

    const carsResponse = await request.get("http://localhost:8001/cars", {
      headers: { Cookie: `session_id=${residentAuth.sessionCookie}` },
    })
    const cars = await carsResponse.json()
    expect(cars.some((c: { license_plate: string }) => c.license_plate === "MGR001")).toBe(true)

    await managerContext.close()
  })
})
