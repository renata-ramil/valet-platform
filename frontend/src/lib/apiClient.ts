const baseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000"

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(
  path: string,
  options: {
    method?: string
    body?: unknown
    csrf?: string
    idempotencyKey?: string
  } = {},
): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" }
  if (options.csrf) {
    headers["X-CSRF-Token"] = options.csrf
  }
  if (options.idempotencyKey) {
    headers["Idempotency-Key"] = options.idempotencyKey
  }
  const response = await fetch(`${baseUrl}${path}`, {
    method: options.method ?? "GET",
    headers,
    credentials: "include",
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  })
  if (!response.ok) {
    const text = await response.text()
    throw new ApiError(response.status, extractErrorMessage(text) || response.statusText)
  }
  if (response.status === 204) {
    return null as T
  }
  return response.json() as Promise<T>
}

export function newIdempotencyKey(): string {
  return crypto.randomUUID()
}

function extractErrorMessage(text: string): string {
  if (!text) return ""
  try {
    const parsed = JSON.parse(text)
    if (typeof parsed.detail === "string") return parsed.detail
    if (Array.isArray(parsed.detail) && parsed.detail[0]?.msg) return parsed.detail[0].msg
  } catch {
    // not JSON, fall through to the raw text
  }
  return text
}

export async function getHealth(): Promise<{ status: string; env: string }> {
  return request("/health")
}

export interface AuthUser {
  id: string
  email: string
  full_name: string
  role: "resident" | "valet" | "manager" | "support"
  building_id: string
  csrf_token: string
}

export function me(): Promise<AuthUser> {
  return request("/auth/me")
}

export interface LoginResult {
  mfa_required: boolean
  challenge_id: string | null
  id: string | null
  email: string | null
  full_name: string | null
  role: AuthUser["role"] | null
  building_id: string | null
  csrf_token: string | null
}

export function login(email: string, password: string): Promise<LoginResult> {
  return request("/auth/login", { method: "POST", body: { email, password } })
}

export function verifyTotp(challengeId: string, code: string): Promise<AuthUser> {
  return request("/auth/totp/verify", {
    method: "POST",
    body: { challenge_id: challengeId, code },
  })
}

export interface TotpEnrollment {
  secret: string
  provisioning_uri: string
  recovery_codes: string[]
}

export function enrollTotp(csrf: string): Promise<TotpEnrollment> {
  return request("/auth/totp/enroll", { method: "POST", csrf })
}

export function confirmTotp(code: string, csrf: string): Promise<AuthUser> {
  return request("/auth/totp/confirm", { method: "POST", body: { code }, csrf })
}

export function disableTotp(code: string, csrf: string): Promise<{ status: string }> {
  return request("/auth/totp/disable", { method: "POST", body: { code }, csrf })
}

// Re-proves TOTP for an already logged in staff member, within the last 10
// minutes, before a manager money action (record payment, credit, refund,
// void, approve)
export function totpStepup(code: string, csrf: string): Promise<AuthUser> {
  return request("/auth/totp/stepup", { method: "POST", body: { code }, csrf })
}

export function register(payload: {
  invite_code: string
  email: string
  password: string
  full_name: string
}): Promise<AuthUser> {
  return request("/auth/register", { method: "POST", body: payload })
}

export function logout(csrf: string): Promise<{ status: string }> {
  return request("/auth/logout", { method: "POST", csrf })
}

export type CarStatus = "pending" | "active" | "ended"

export interface Car {
  id: string
  owner_id: string
  plan_id: string | null
  make: string
  model: string
  color: string
  license_plate: string
  status: CarStatus
  started_on: string
  ended_on: string | null
  size_class: string | null
  nickname: string | null
  created_at: string
}

// Residents can only read their cars and edit the nickname. Everything else
// about a car (plate, make, model, plan, ending it) is a manager action: see
// managerCreateCar, managerUpdateCar and managerEndCar below.
export function listCars(): Promise<Car[]> {
  return request("/cars")
}

export function updateCarNickname(csrf: string, carId: string, nickname: string): Promise<Car> {
  return request(`/cars/${carId}`, { method: "PATCH", body: { nickname }, csrf })
}

export type CarRequestAction = "add" | "remove" | "change"
export type CarRequestStatus = "pending" | "applied" | "dismissed"

export interface CarRequestOut {
  id: string
  ticket_id: string
  action: CarRequestAction
  status: CarRequestStatus
  car_id: string | null
  plate: string | null
  make: string | null
  model: string | null
  color: string | null
  note: string | null
  created_at: string
}

export function submitCarRequest(
  csrf: string,
  payload: {
    action: CarRequestAction
    car_id?: string | null
    plate?: string | null
    make?: string | null
    model?: string | null
    color?: string | null
    note?: string | null
  },
): Promise<CarRequestOut> {
  return request("/cars/requests", { method: "POST", body: payload, csrf })
}

export type RequestState =
  | "scheduled"
  | "queued"
  | "assigned"
  | "retrieving"
  | "en_route"
  | "delivered"
  | "cancelled"
  | "failed"

export interface RequestEventOut {
  type: string
  payload: string
  created_at: string
}

export interface CarRequest {
  id: string
  owner_id: string
  car_id: string
  source: string
  ready_by: string
  state: RequestState
  resident_label: string
  schedule_id: string | null
  created_at: string
  events: RequestEventOut[]
  eta_ready_by: string | null
  eta_latest: string | null
  eta_calibrated: boolean
}

export function listRequests(): Promise<CarRequest[]> {
  return request("/requests")
}

export function createRequest(
  csrf: string,
  payload: { car_id: string; ready_by?: string },
): Promise<CarRequest> {
  return request("/requests", { method: "POST", body: payload, csrf })
}

export function cancelRequest(csrf: string, requestId: string): Promise<CarRequest> {
  return request(`/requests/${requestId}/cancel`, { method: "POST", csrf })
}

export interface Schedule {
  id: string
  car_id: string
  owner_id: string
  weekdays: number[]
  ready_by_local_time: string
  active_from: string
  active_until: string | null
  paused_until: string | null
}

export function listSchedules(): Promise<Schedule[]> {
  return request("/schedules")
}

export function createSchedule(
  csrf: string,
  payload: {
    car_id: string
    weekdays: number[]
    ready_by_local_time: string
    active_from: string
    active_until?: string | null
  },
): Promise<Schedule> {
  return request("/schedules", { method: "POST", body: payload, csrf })
}

export function deleteSchedule(csrf: string, scheduleId: string): Promise<null> {
  return request(`/schedules/${scheduleId}`, { method: "DELETE", csrf })
}

export function skipTomorrow(
  csrf: string,
  scheduleId: string,
): Promise<{ status: string; local_date: string }> {
  return request(`/schedules/${scheduleId}/skip-tomorrow`, { method: "POST", csrf })
}

export function addScheduleException(
  csrf: string,
  scheduleId: string,
  payload: { local_date: string; kind: "skip" | "override"; override_local_time?: string },
): Promise<{ status: string; local_date: string; kind: string }> {
  return request(`/schedules/${scheduleId}/exceptions`, { method: "POST", body: payload, csrf })
}

export function pauseUntil(
  csrf: string,
  scheduleId: string,
  pausedUntil: string,
): Promise<{ status: string; paused_until: string }> {
  return request(`/schedules/${scheduleId}/pause-until`, {
    method: "POST",
    body: { paused_until: pausedUntil },
    csrf,
  })
}

export function transitionRequest(
  csrf: string,
  requestId: string,
  targetState: string,
): Promise<CarRequest> {
  return request(`/requests/${requestId}/transition`, {
    method: "POST",
    body: { target_state: targetState },
    csrf,
  })
}

export interface ValetQueueItem {
  task: {
    id: string
    request_id: string
    type: string
    assigned_valet_id: string | null
    state: string
    planned_start_at: string
    completed_at: string | null
  }
  request: CarRequest
  car: Car
  lane: number | null
  depth: number | null
  minutes_to_deadline: number
}

export function getValetQueue(): Promise<ValetQueueItem[]> {
  return request("/valet/queue")
}

export interface CarSearchResult {
  id: string
  license_plate: string
  make: string
  model: string
  color: string
  owner_name: string
}

export function searchValetCars(plate: string): Promise<CarSearchResult[]> {
  return request(`/valet/car-search?plate=${encodeURIComponent(plate)}`)
}

export interface CarArrivedResult {
  status: string
  task_id: string
  request_id: string
}

export function carArrived(csrf: string, carId: string): Promise<CarArrivedResult> {
  return request(`/valet/cars/${carId}/arrived`, { method: "POST", csrf })
}

export interface ParkTaskCompleteResult {
  status: string
  task_id: string
  lane: number | null
  depth: number | null
}

export function completeParkTask(csrf: string, taskId: string): Promise<ParkTaskCompleteResult> {
  return request(`/valet/tasks/${taskId}/complete-park`, { method: "POST", csrf })
}

export interface ManagerDashboard {
  counts_by_state: Record<string, number>
  valet_roster: {
    valet_id: string
    full_name: string
    current_task_id: string | null
    current_task_type: string | null
  }[]
  on_time_rate_today: number | null
  timeline: { bucket_start: string; count: number }[]
}

export function getManagerDashboard(): Promise<ManagerDashboard> {
  return request("/manager/dashboard")
}

export interface WhatIfResult {
  source: string
  seeds: number | null
  on_time_rate: number
  on_time_rate_ci: [number, number] | null
  wait_p95_seconds: number
  wait_p95_seconds_ci: [number, number] | null
  relocations_per_retrieval: number
  relocations_per_retrieval_ci: [number, number] | null
  note: string | null
}

export function getWhatIf(valetCount: number, demandMultiplier: number): Promise<WhatIfResult> {
  return request(
    `/manager/what-if?valet_count=${valetCount}&demand_multiplier=${demandMultiplier}`,
  )
}

export interface Ticket {
  id: string
  resident_id: string
  request_id: string | null
  subject: string
  status: "open" | "waiting" | "resolved"
  created_at: string
  messages: { id: string; author_id: string; body: string; created_at: string }[]
}

export function listTickets(): Promise<Ticket[]> {
  return request("/tickets")
}

export function getTicket(ticketId: string): Promise<Ticket> {
  return request(`/tickets/${ticketId}`)
}

export function createTicket(
  csrf: string,
  payload: { subject: string; message: string; request_id?: string },
): Promise<Ticket> {
  return request("/tickets", { method: "POST", body: payload, csrf })
}

export function addTicketMessage(
  csrf: string,
  ticketId: string,
  body: string,
): Promise<{ status: string }> {
  return request(`/tickets/${ticketId}/messages`, { method: "POST", body: { body }, csrf })
}

export function updateTicketStatus(
  csrf: string,
  ticketId: string,
  ticketStatus: string,
): Promise<Ticket> {
  return request(`/tickets/${ticketId}/status`, {
    method: "PATCH",
    body: { status: ticketStatus },
    csrf,
  })
}

export interface SupportChatDone {
  reply: string
  proposal: {
    proposal_id: string
    description: string
    confirmation_token: string
    expires_in_seconds: number
  } | null
  tool_calls: { name: string; error: string | null }[]
  used_live_model: boolean
  refused: boolean
}

export async function streamSupportChat(
  csrf: string,
  message: string,
  history: { role: string; content: string }[],
  onToken: (text: string) => void,
): Promise<SupportChatDone> {
  const response = await fetch(`${baseUrl}/support/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
    credentials: "include",
    body: JSON.stringify({ message, history }),
  })
  if (!response.ok || !response.body) {
    const text = await response.text()
    throw new ApiError(response.status, extractErrorMessage(text) || response.statusText)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  let done: SupportChatDone | null = null

  while (true) {
    const { value, done: streamDone } = await reader.read()
    if (streamDone) break
    buffer += decoder.decode(value, { stream: true })
    const events = buffer.split("\n\n")
    buffer = events.pop() ?? ""
    for (const raw of events) {
      const eventLine = raw.split("\n").find((l) => l.startsWith("event: "))
      const dataLine = raw.split("\n").find((l) => l.startsWith("data: "))
      if (!eventLine || !dataLine) continue
      const eventName = eventLine.slice("event: ".length)
      const data = JSON.parse(dataLine.slice("data: ".length))
      if (eventName === "token") {
        onToken(data.text)
      } else if (eventName === "done") {
        done = data as SupportChatDone
      }
    }
  }
  if (!done) {
    throw new Error("Support chat stream ended without a done event")
  }
  return done
}

export function confirmSupportReschedule(
  csrf: string,
  proposalId: string,
  token: string,
): Promise<{ reply: string }> {
  return request("/support/confirm", {
    method: "POST",
    body: { proposal_id: proposalId, token },
    csrf,
  })
}

export function getCalendarFeedPath(csrf: string): Promise<{ feed_path: string }> {
  return request("/calendar/token", { method: "POST", csrf })
}

export interface CalendarProposal {
  event_summary: string
  event_start: string
  event_location: string
  proposed_ready_by: string
}

export function importCalendar(
  csrf: string,
  icsUrl: string,
): Promise<{ proposals: CalendarProposal[] }> {
  return request("/calendar/import", { method: "POST", body: { ics_url: icsUrl }, csrf })
}

export interface Suggestion {
  weekdays: number[]
  ready_by_local_time: string
  recurrence_probability: number
  observations: number
}

export function getSuggestions(): Promise<Suggestion[]> {
  return request("/suggestions")
}

// Billing, resident facing

export interface CarBillingSummary {
  car_id: string
  license_plate: string
  plan_name: string | null
  monthly_cents: number | null
}

export interface BillingSummary {
  amount_due_cents: number
  due_date: string | null
  autopay_enabled: boolean
  paid_through: string | null
  cars: CarBillingSummary[]
}

export function getBillingSummary(): Promise<BillingSummary> {
  return request("/billing/summary")
}

export type InvoiceStatus = "draft" | "open" | "processing" | "paid" | "past_due" | "void"

export interface InvoiceLine {
  id: string
  car_id: string | null
  description: string
  amount_cents: number
  days_active: number | null
  days_in_month: number | null
}

export interface Invoice {
  id: string
  resident_id: string
  period_start: string
  period_end: string
  status: InvoiceStatus
  total_cents: number
  paid_cents: number
  due_at: string
  issued_at: string | null
  paid_at: string | null
  is_adjustment: boolean
  lines: InvoiceLine[]
}

export function listInvoices(): Promise<Invoice[]> {
  return request("/billing/invoices")
}

export function getInvoice(invoiceId: string): Promise<Invoice> {
  return request(`/billing/invoices/${invoiceId}`)
}

export function receiptUrl(invoiceId: string): string {
  return `${baseUrl}/billing/invoices/${invoiceId}/receipt`
}

export type PaymentMethodKind = "card" | "bank"

export interface PaymentMethod {
  id: string
  kind: PaymentMethodKind
  brand: string | null
  last4: string
  exp_month: number | null
  exp_year: number | null
  is_active: boolean
  pending: boolean
  client_secret: string | null
}

export function listPaymentMethods(): Promise<PaymentMethod[]> {
  return request("/billing/payment-methods")
}

// Card and bank details never touch our servers: fake_token stands in for
// what a real Stripe Elements/SetupIntent flow would tokenize client side
export function setupPaymentMethod(
  csrf: string,
  payload: { kind: PaymentMethodKind; fake_token?: string },
): Promise<PaymentMethod> {
  return request("/billing/payment-methods/setup", { method: "POST", body: payload, csrf })
}

export function deletePaymentMethod(csrf: string, methodId: string): Promise<null> {
  return request(`/billing/payment-methods/${methodId}`, { method: "DELETE", csrf })
}

export function updateAutopay(csrf: string, enabled: boolean): Promise<BillingSummary> {
  return request("/billing/autopay", { method: "PATCH", body: { enabled }, csrf })
}

export type PaymentStatus = "pending" | "succeeded" | "failed" | "refunded" | "requires_action"

export interface Payment {
  id: string
  invoice_id: string
  method: string
  provider: string
  amount_cents: number
  status: PaymentStatus
  is_refund: boolean
  created_at: string
}

export function payInvoice(
  csrf: string,
  idempotencyKey: string,
  invoiceId: string,
  paymentMethodId?: string,
): Promise<Payment> {
  return request(`/billing/invoices/${invoiceId}/pay`, {
    method: "POST",
    body: { payment_method_id: paymentMethodId ?? null },
    csrf,
    idempotencyKey,
  })
}

// Fleet, manager facing

export function managerCreateCar(
  csrf: string,
  payload: {
    resident_id: string
    make: string
    model: string
    color: string
    license_plate: string
    plan_id?: string | null
    started_on?: string | null
    size_class?: string | null
    nickname?: string | null
  },
): Promise<Car> {
  return request("/manager/cars", { method: "POST", body: payload, csrf })
}

export function managerUpdateCar(
  csrf: string,
  carId: string,
  payload: Partial<{
    make: string
    model: string
    color: string
    license_plate: string
    plan_id: string | null
    size_class: string | null
    nickname: string | null
  }>,
): Promise<Car> {
  return request(`/manager/cars/${carId}`, { method: "PATCH", body: payload, csrf })
}

export function managerEndCar(csrf: string, carId: string, endedOn?: string): Promise<Car> {
  return request(`/manager/cars/${carId}/end`, {
    method: "POST",
    body: { ended_on: endedOn ?? null },
    csrf,
  })
}

export interface ResidentSummary {
  id: string
  email: string
  full_name: string
  unit: string | null
  car_count: number
}

export function managerListResidents(search?: string, unit?: string): Promise<ResidentSummary[]> {
  const params = new URLSearchParams()
  if (search) params.set("search", search)
  if (unit) params.set("unit", unit)
  const qs = params.toString()
  return request(`/manager/residents${qs ? `?${qs}` : ""}`)
}

export interface ResidentDetail {
  id: string
  email: string
  full_name: string
  unit: string | null
  cars: Car[]
}

export function managerResidentDetail(residentId: string): Promise<ResidentDetail> {
  return request(`/manager/residents/${residentId}`)
}

export interface ImportRowResult {
  row_number: number
  status: string
  detail: string
  email: string | null
  license_plate: string | null
}

export interface ImportResult {
  dry_run: boolean
  ok_count: number
  error_count: number
  rows: ImportRowResult[]
}

export function managerImportCars(
  csrf: string,
  csvText: string,
  dryRun: boolean,
): Promise<ImportResult> {
  return request("/manager/cars/import", {
    method: "POST",
    body: { csv_text: csvText, dry_run: dryRun },
    csrf,
  })
}

export function managerInviteResident(
  csrf: string,
  unit: string,
  maxUses = 1,
): Promise<{ code: string; unit: string | null; max_uses: number }> {
  return request("/manager/residents/invite", {
    method: "POST",
    body: { unit, max_uses: maxUses },
    csrf,
  })
}

export function managerListCarRequests(): Promise<CarRequestOut[]> {
  return request("/manager/car-requests")
}

export function managerPrefillCarRequest(carRequestId: string): Promise<Record<string, unknown>> {
  return request(`/manager/car-requests/${carRequestId}/prefill`)
}

export interface Plan {
  id: string
  name: string
  size_class: string
  archived: boolean
  current_monthly_cents: number
  created_at: string
}

export function managerCreatePlan(
  csrf: string,
  payload: { name: string; size_class: string; monthly_cents: number },
): Promise<Plan> {
  return request("/manager/plans", { method: "POST", body: payload, csrf })
}

export function managerListPlans(): Promise<Plan[]> {
  return request("/manager/plans")
}

export function managerSchedulePriceChange(
  csrf: string,
  planId: string,
  monthlyCents: number,
  effectiveMonth: string,
): Promise<Plan> {
  return request(`/manager/plans/${planId}/price`, {
    method: "POST",
    body: { monthly_cents: monthlyCents, effective_month: effectiveMonth },
    csrf,
  })
}

export function managerPreviewPriceChange(
  csrf: string,
  planId: string,
  monthlyCents: number,
  effectiveMonth: string,
): Promise<Record<string, unknown>> {
  return request(`/manager/plans/${planId}/price-preview`, {
    method: "POST",
    body: { monthly_cents: monthlyCents, effective_month: effectiveMonth },
    csrf,
  })
}

export function managerArchivePlan(csrf: string, planId: string): Promise<Plan> {
  return request(`/manager/plans/${planId}/archive`, { method: "POST", csrf })
}

// Billing, manager facing

export interface BillingOverview {
  month: string
  billed_cents: number
  collected_cents: number
  outstanding_cents: number
  past_due_count: number
  autopay_share: number
  collection_curve: { day: number; collected_cents: number }[]
  needs_attention: {
    invoice_id: string
    resident_id: string
    status: InvoiceStatus
    total_cents: number
    paid_cents: number
    due_at: string
  }[]
}

export function managerBillingOverview(month: string): Promise<BillingOverview> {
  return request(`/manager/billing/overview?month=${encodeURIComponent(month)}`)
}

export interface ManagerInvoiceSummary {
  id: string
  resident_id: string
  period_start: string
  period_end: string
  status: InvoiceStatus
  total_cents: number
  paid_cents: number
  due_at: string
  is_adjustment: boolean
}

export function managerListInvoices(
  status?: string,
  residentId?: string,
): Promise<ManagerInvoiceSummary[]> {
  const params = new URLSearchParams()
  if (status) params.set("status", status)
  if (residentId) params.set("resident_id", residentId)
  const qs = params.toString()
  return request(`/manager/invoices${qs ? `?${qs}` : ""}`)
}

export interface ManagerInvoiceDetail extends ManagerInvoiceSummary {
  lines: InvoiceLine[]
  payments: Payment[]
  ledger_entries: {
    id: string
    account: string
    debit_cents: number
    credit_cents: number
    memo: string
    created_at: string
  }[]
  audit_events: { type: string; payload: Record<string, unknown>; created_at: string }[]
}

export function managerInvoiceDetail(invoiceId: string): Promise<ManagerInvoiceDetail> {
  return request(`/manager/invoices/${invoiceId}`)
}

export function managerRecordPayment(
  csrf: string,
  idempotencyKey: string,
  invoiceId: string,
  payload: { amount_cents: number; method: "cash" | "check" | "transfer"; reference?: string; paid_on?: string },
): Promise<Payment> {
  return request(`/manager/invoices/${invoiceId}/record-payment`, {
    method: "POST",
    body: payload,
    csrf,
    idempotencyKey,
  })
}

export interface ApprovalRequestOut {
  id: string
  kind: "refund" | "credit"
  amount_cents: number
  reason: string
  status: "pending" | "approved" | "rejected"
  requested_by: string
  approved_by: string | null
  created_at: string
}

export function managerIssueCredit(
  csrf: string,
  idempotencyKey: string,
  invoiceId: string,
  payload: { amount_cents: number; reason: string },
): Promise<{ status: string; approval?: ApprovalRequestOut; invoice_id?: string; amount_cents?: number }> {
  return request(`/manager/invoices/${invoiceId}/credit`, {
    method: "POST",
    body: payload,
    csrf,
    idempotencyKey,
  })
}

export function managerRefund(
  csrf: string,
  idempotencyKey: string,
  invoiceId: string,
  payload: { amount_cents: number; reason: string; payment_id: string },
): Promise<{ status: string; approval?: ApprovalRequestOut; invoice_id?: string; amount_cents?: number }> {
  return request(`/manager/invoices/${invoiceId}/refund`, {
    method: "POST",
    body: payload,
    csrf,
    idempotencyKey,
  })
}

export function managerVoidInvoice(
  csrf: string,
  invoiceId: string,
  reason: string,
): Promise<{ status: string; invoice_id: string }> {
  return request(`/manager/invoices/${invoiceId}/void`, { method: "POST", body: { reason }, csrf })
}

export function managerResendReceipt(
  csrf: string,
  invoiceId: string,
): Promise<{ status: string }> {
  return request(`/manager/invoices/${invoiceId}/resend-receipt`, { method: "POST", csrf })
}

export function managerListApprovals(): Promise<ApprovalRequestOut[]> {
  return request("/manager/approvals")
}

export function managerDecideApproval(
  csrf: string,
  approvalId: string,
  approve: boolean,
): Promise<{ status: string; approval: ApprovalRequestOut }> {
  return request(`/manager/approvals/${approvalId}/decide`, {
    method: "POST",
    body: { approve },
    csrf,
  })
}

export function monthCloseCsvUrl(month: string): string {
  return `${baseUrl}/manager/billing/month-close.csv?month=${encodeURIComponent(month)}`
}

export { baseUrl }
