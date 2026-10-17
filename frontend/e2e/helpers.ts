import type { APIRequestContext } from "@playwright/test"

const API_BASE = "http://localhost:8001"

export function uniqueEmail(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 10000)}@harbortower.example.com`
}

export async function registerAndLoginValet(
  request: APIRequestContext,
): Promise<{ sessionCookie: string; csrf: string }> {
  const email = uniqueEmail("valet")
  const password = "valetpass123"
  await request.post(`${API_BASE}/auth/register`, {
    data: {
      invite_code: "E2E-VALET",
      email,
      password,
      full_name: "E2E Valet",
    },
  })
  const loginResponse = await request.post(`${API_BASE}/auth/login`, {
    data: { email, password },
  })
  const body = await loginResponse.json()
  const cookies = loginResponse.headers()["set-cookie"] ?? ""
  const match = /session_id=([^;]+)/.exec(cookies)
  const sessionCookie = match ? match[1] : ""
  return { sessionCookie, csrf: body.csrf_token }
}

export async function advanceRequestAsValet(
  request: APIRequestContext,
  valetAuth: { sessionCookie: string; csrf: string },
  requestId: string,
  targetState: string,
) {
  return request.post(`${API_BASE}/requests/${requestId}/transition`, {
    headers: {
      Cookie: `session_id=${valetAuth.sessionCookie}`,
      "X-CSRF-Token": valetAuth.csrf,
    },
    data: { target_state: targetState },
  })
}

export interface Auth {
  sessionCookie: string
  csrf: string
  userId: string
}

export async function registerAndLogin(
  request: APIRequestContext,
  inviteCode: string,
  fullName: string,
): Promise<Auth> {
  const email = uniqueEmail(inviteCode.toLowerCase())
  const password = "testpass123"
  const registerResponse = await request.post(`${API_BASE}/auth/register`, {
    data: { invite_code: inviteCode, email, password, full_name: fullName },
  })
  const registered = await registerResponse.json()
  const loginResponse = await request.post(`${API_BASE}/auth/login`, {
    data: { email, password },
  })
  const body = await loginResponse.json()
  const cookies = loginResponse.headers()["set-cookie"] ?? ""
  const match = /session_id=([^;]+)/.exec(cookies)
  const sessionCookie = match ? match[1] : ""
  return { sessionCookie, csrf: body.csrf_token, userId: registered.id }
}

export function authHeaders(auth: Auth): Record<string, string> {
  return { Cookie: `session_id=${auth.sessionCookie}`, "X-CSRF-Token": auth.csrf }
}

// Residents can no longer add their own car (fleet ownership belongs
// to managers): an e2e resident needs a manager to create one
// before "Bring my car" has anything to call
export async function managerCreateCarForResident(
  request: APIRequestContext,
  managerAuth: Auth,
  residentId: string,
  payload: { make: string; model: string; color: string; license_plate: string },
): Promise<{ id: string; license_plate: string }> {
  const response = await request.post(`${API_BASE}/manager/cars`, {
    headers: authHeaders(managerAuth),
    data: { resident_id: residentId, ...payload },
  })
  return response.json()
}
