const TOKEN_KEY = "cms_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export interface User {
  id: number;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
}

export interface Account {
  id: number;
  name: string;
  type: "builder" | "retail";
  notes: string | null;
  ksr?: string | null;
}

export interface Community {
  id: number;
  account_id: number;
  name: string;
  market: string | null;
}

export interface AccountDetail extends Account {
  communities: Community[];
}

export interface RoomSelection {
  id: number;
  job_id: number;
  room: string;
  zone: string | null;
  cabinet_brand: string | null;
  series: string | null;
  door_style: string | null;
  finish: string | null;
  wood_species: string | null;
  notes: string | null;
}

export interface HardwareSelection {
  id: number;
  job_id: number;
  room: string | null;
  hardware_type: "door" | "drawer" | null;
  vendor: string | null;
  item: string;
  qty: number;
}

export const JOB_STATUSES = [
  "1.0-Track",
  "1.1-PreOrd",
  "1.2-NdOrd",
  "1.3-Ord Prcss",
  "1.4-OrdSub",
  "1.5-OrdPO",
  "2.0-Ord",
  "2.1-Inst",
  "3.0-Nd QW",
  "3.1-Parts",
  "4.0-Punch",
  "4.1-Blue",
  "5.0-EPO",
  "6.0-Clsd",
  "7.0-War",
  "8.0-Void",
] as const;
export type JobStatus = (typeof JOB_STATUSES)[number];

// "3.0-Nd QW" -> "3-0-nd-qw" for CSS badge classes
export const statusSlug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-");
export type JobType = "tract" | "custom" | "remodel";

export interface JobListItem {
  id: number;
  job_code: string | null;
  account_id: number;
  account_name: string;
  community_name: string | null;
  lot_number: string | null;
  address: string;
  job_type: JobType;
  status: JobStatus;
  install_date: string | null;
}

export interface Job {
  id: number;
  job_code: string | null;
  account_id: number;
  community_id: number | null;
  lot_number: string | null;
  address: string;
  job_type: JobType;
  plan: string | null;
  status: JobStatus;
  install_date: string | null;
  measure_date: string | null;
  warranty_start_date: string | null;
  sales_contact_name: string;
  sales_contact_phone: string | null;
  sales_contact_email: string | null;
  field_contact_name: string;
  field_contact_phone: string | null;
  field_contact_email: string | null;
  notes: string | null;
  ksr: string | null;
  sale_date: string | null;
}

export interface JobDetail extends Job {
  account_name: string;
  community_name: string | null;
  room_selections: RoomSelection[];
  hardware_selections: HardwareSelection[];
}

async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const resp = await fetch(`/api${path}`, {
    ...options,
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      Authorization: `Bearer ${getToken()}`,
      ...options.headers,
    },
  });
  if (resp.status === 401) {
    setToken(null);
    window.location.hash = "";
    window.location.reload();
    throw new Error("Session expired");
  }
  if (!resp.ok) {
    const detail = (await resp.json().catch(() => null))?.detail;
    throw new Error(typeof detail === "string" ? detail : `Request failed (${resp.status})`);
  }
  if (resp.status === 204) return undefined as T;
  return resp.json();
}

export async function login(email: string, password: string): Promise<void> {
  const body = new URLSearchParams({ username: email, password });
  const resp = await fetch("/api/auth/token", { method: "POST", body });
  if (!resp.ok) {
    const detail = (await resp.json().catch(() => null))?.detail;
    throw new Error(detail ?? "Login failed");
  }
  setToken((await resp.json()).access_token);
}

export const fetchMe = () => api<User>("/auth/me");

// --- User management (admin only) ------------------------------------------
export interface ManagedUser extends User {
  created_at: string;
}
export const ROLES: { value: string; label: string; blurb: string }[] = [
  { value: "admin", label: "Admin", blurb: "Full access, including managing users" },
  { value: "sales", label: "Sales", blurb: "Create & edit jobs, quotes, orders, accounts" },
  { value: "field", label: "Field", blurb: "View everything; log phase updates" },
  {
    value: "installer_coordinator",
    label: "Installer coordinator",
    blurb: "View everything; log phase updates",
  },
  { value: "inspector", label: "Inspector", blurb: "View-only across the office app" },
  { value: "service_tech", label: "Service tech", blurb: "Autobot only — nothing else" },
];
export const roleLabel = (value: string) =>
  ROLES.find((r) => r.value === value)?.label ?? value;

export interface UserCreatedResult {
  user: ManagedUser;
  invite_sent: boolean;
  invite_error: string | null;
}
export interface ActivityRow {
  id: number;
  at: string | null;
  user_name: string | null;
  user_email: string | null;
  role: string | null;
  action: string;
  entity: string | null;
  entity_id: string | null;
  status_code: number;
  method: string;
  path: string;
}
export const listActivity = (params: { limit?: number; user_email?: string } = {}) => {
  const usp = new URLSearchParams();
  if (params.limit) usp.set("limit", String(params.limit));
  if (params.user_email) usp.set("user_email", params.user_email);
  const qs = usp.toString();
  return api<ActivityRow[]>(`/auth/activity${qs ? `?${qs}` : ""}`);
};

export const listUsers = () => api<ManagedUser[]>("/auth/users");
export const getInviteStatus = () => api<{ email_enabled: boolean }>("/auth/invite-status");
export const createUser = (data: {
  email: string;
  full_name: string;
  role: string;
  password?: string;
  send_invite?: boolean;
}) => api<UserCreatedResult>("/auth/users", { method: "POST", body: JSON.stringify(data) });
export const resendInvite = (id: number) =>
  api<{ invite_sent: boolean; email: string }>(`/auth/users/${id}/invite`, { method: "POST" });

/** Public — set a password from an emailed invite token; returns a login token. */
export async function setPasswordWithToken(token: string, password: string): Promise<void> {
  const resp = await fetch("/api/auth/set-password", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token, password }),
  });
  if (!resp.ok) {
    const detail = (await resp.json().catch(() => null))?.detail;
    throw new Error(typeof detail === "string" ? detail : "Could not set password");
  }
  setToken((await resp.json()).access_token);
}
export const updateUser = (
  id: number,
  data: { full_name?: string; role?: string; is_active?: boolean },
) => api<ManagedUser>(`/auth/users/${id}`, { method: "PATCH", body: JSON.stringify(data) });
export const resetUserPassword = (id: number, password: string) =>
  api<ManagedUser>(`/auth/users/${id}/password`, {
    method: "POST",
    body: JSON.stringify({ password }),
  });

export interface FeedResult {
  file?: string;
  created?: number;
  updated?: number;
  skipped?: number;
  no_job?: number;
  unchanged?: number;
  error?: string;
  skipped_locked?: string[];
}

export const runFeedSync = () =>
  api<Record<string, FeedResult>>("/sync/feeds", { method: "POST" });

export interface JobNote {
  id: number;
  job_id: number;
  body: string;
  author: string | null;
  created_at: string;
}

export const listJobNotes = (jobId: number) => api<JobNote[]>(`/jobs/${jobId}/notes`);
export const addJobNote = (jobId: number, body: string) =>
  api<JobNote>(`/jobs/${jobId}/notes`, { method: "POST", body: JSON.stringify({ body }) });

export const listAccounts = (activeOnly = false) =>
  api<Account[]>(`/accounts${activeOnly ? "?active_only=true" : ""}`);
export const getAccount = (id: number) => api<AccountDetail>(`/accounts/${id}`);
export const createAccount = (data: { name: string; type: string }) =>
  api<Account>("/accounts", { method: "POST", body: JSON.stringify(data) });
export const updateAccount = (id: number, data: Record<string, unknown>) =>
  api<Account>(`/accounts/${id}`, { method: "PATCH", body: JSON.stringify(data) });
export const listKsrs = () => api<string[]>("/ksrs");
export const createCommunity = (data: { account_id: number; name: string; market?: string }) =>
  api<Community>("/communities", { method: "POST", body: JSON.stringify(data) });
export const listCommunities = (accountId: number, activeOnly = true) =>
  api<Community[]>(`/communities?account_id=${accountId}${activeOnly ? "&active_only=true" : ""}`);
export const listAllCommunities = (activeOnly = true) =>
  api<Community[]>(`/communities${activeOnly ? "?active_only=true" : ""}`);

export const listJobs = (params: Record<string, string | string[]> = {}) => {
  const usp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (Array.isArray(v)) v.forEach((x) => x && usp.append(k, x));
    else if (v) usp.append(k, v);
  }
  const qs = usp.toString();
  return api<JobListItem[]>(`/jobs${qs ? `?${qs}` : ""}`);
};
export const getJob = (id: number) => api<JobDetail>(`/jobs/${id}`);
export const createJob = (data: Record<string, unknown>) =>
  api<Job>("/jobs", { method: "POST", body: JSON.stringify(data) });
export const updateJob = (id: number, data: Record<string, unknown>) =>
  api<Job>(`/jobs/${id}`, { method: "PATCH", body: JSON.stringify(data) });

export interface QuoteLine {
  id: number;
  quote_id: number;
  room: string | null;
  qty: number;
  sku: string;
  product_code: string | null;
  fin_end: string | null;
  color: string | null;
  list_price: string;
  notes: string | null;
  net_each: string;
  total: string;
  excluded: boolean;
}

export interface Quote {
  id: number;
  job_id: number;
  name: string;
  status: "draft" | "accepted";
  multiplier: string;
  notes: string | null;
  list_total: string;
  net_total: string;
  line_count: number;
}

export interface QuoteDetail extends Quote {
  lines: QuoteLine[];
}

export interface Order {
  id: number;
  job_id: number;
  quote_id: number;
  supplier: string;
  po_number: string | null;
  confirmation_status: "pending" | "confirmed" | "rejected";
  ship_status: "not_shipped" | "scheduled" | "shipped" | "delivered";
  has_file: boolean;
  skipped_skus?: string[];
}

export interface JobDocument {
  id: number;
  job_id: number;
  filename: string;
  doc_type: string;
}

export const listDocuments = (jobId: number) => api<JobDocument[]>(`/jobs/${jobId}/documents`);
export const registerDocument = (jobId: number, data: { file_path: string; doc_type?: string }) =>
  api<JobDocument>(`/jobs/${jobId}/documents`, { method: "POST", body: JSON.stringify(data) });
export const removeDocument = (id: number) => api<void>(`/documents/${id}`, { method: "DELETE" });

export async function openDocument(docId: number): Promise<void> {
  const resp = await fetch(`/api/documents/${docId}/file`, {
    headers: { Authorization: `Bearer ${getToken()}` },
  });
  if (!resp.ok) {
    const detail = (await resp.json().catch(() => null))?.detail;
    throw new Error(detail ?? "Could not open document");
  }
  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  window.open(url, "_blank");
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

export interface OrderingChecklist {
  job_id: number;
  stage1_done: boolean;
  stage2_done: boolean;
  stage3_done: boolean;
  stage4_done: boolean;
  stage1_date: string | null;
  stage2_date: string | null;
  stage3_date: string | null;
  stage4_date: string | null;
  notes: string | null;
}

export interface OrderingBoardRow {
  job_id: number;
  job_code: string | null;
  address: string;
  account_name: string;
  community_name: string | null;
  lot_number: string | null;
  status: JobStatus;
  checklist: OrderingChecklist;
}

export const getOrderingChecklist = (jobId: number) =>
  api<OrderingChecklist>(`/jobs/${jobId}/ordering`);
export const updateOrderingChecklist = (jobId: number, data: Record<string, unknown>) =>
  api<OrderingChecklist>(`/jobs/${jobId}/ordering`, { method: "PATCH", body: JSON.stringify(data) });
export interface PhaseDef {
  code: string;
  label: string;
}

export interface FieldMeasureNote {
  body: string;
  author: string | null;
  created_at: string;
}

export interface PhaseBoardRow {
  job_id: number;
  job_code: string | null;
  lot_number: string | null;
  address: string;
  plan: string | null;
  status: JobStatus;
  phase: string | null;
  phase_label: string | null;
  phase_date: string | null;
  measure_date: string | null;
  layout_doc_id: number | null;
  ordering_stages: boolean[];
  fm_complete_date: string | null;
  fm_correct: boolean;
  fm_incorrect: boolean;
  fm_super_notified: boolean;
  fm_notes: FieldMeasureNote[];
}

export interface PhaseEntry {
  id: number;
  job_id: number;
  phase: string;
  source: string;
  noted_by: string | null;
  noted_at: string;
}

/** Phase history for one job, newest first — [0] is the current phase. */
export const getJobPhases = (jobId: number) =>
  api<PhaseEntry[]>(`/jobs/${jobId}/phases`);

export const getPhaseDefs = () => api<PhaseDef[]>("/phases");
export const getPhaseBoard = (communityId: number) =>
  api<PhaseBoardRow[]>(`/phase-board?community_id=${communityId}`);
export const setJobPhase = (jobId: number, phase: string) =>
  api<{ phase: string; noted_at: string }>(`/jobs/${jobId}/phase`, {
    method: "POST",
    body: JSON.stringify({ phase }),
  });

export interface FieldMeasureNoteFull extends FieldMeasureNote {
  id: number;
  job_id: number;
}
export interface FieldMeasure {
  complete_date: string | null;
  correct: boolean;
  correct_by: string | null;
  correct_at: string | null;
  incorrect: boolean;
  incorrect_by: string | null;
  incorrect_at: string | null;
  super_notified: boolean;
  super_notified_by: string | null;
  super_notified_at: string | null;
}
export interface FieldMeasureDetail extends FieldMeasure {
  notes: FieldMeasureNoteFull[];
}

export const getFieldMeasure = (jobId: number) =>
  api<FieldMeasureDetail>(`/jobs/${jobId}/field-measure`);
export const updateFieldMeasure = (jobId: number, data: Partial<Record<string, unknown>>) =>
  api<FieldMeasure>(`/jobs/${jobId}/field-measure`, { method: "PATCH", body: JSON.stringify(data) });
export const addFieldMeasureNote = (jobId: number, body: string) =>
  api<FieldMeasureNoteFull>(`/jobs/${jobId}/field-measure/notes`, {
    method: "POST",
    body: JSON.stringify({ body }),
  });

export interface PhaseReportRow {
  account_name: string;
  community_name: string | null;
  job_id: number;
  job_code: string | null;
  lot_number: string | null;
  address: string;
  plan: string | null;
  phase: string | null;
  phase_label: string | null;
  phase_date: string | null;
  measure_date: string | null;
  install_date: string | null;
  fm_correct: boolean;
  fm_incorrect: boolean;
  layout_doc_id: number | null;
}

export const getPhaseReport = () => api<PhaseReportRow[]>("/reports/phases");

export interface ReportInfo {
  key: string;
  name: string;
  description: string;
  category: string;
}
export interface OpenPORow {
  job_id: number;
  job_code: string | null;
  account_name: string;
  community_name: string | null;
  lot_number: string | null;
  address: string;
  builder_po: string | null;
  po_amount: number;
  po_status: string | null;
}
export interface OpenPOReport {
  rows: OpenPORow[];
  total_amount: number;
  count: number;
}
export interface StatusSummaryRow {
  po_status: string;
  count: number;
  total_amount: number;
}
export interface RevenueGroup {
  label: string;
  sublabel: string | null;
  count: number;
  total_amount: number;
}
export interface InstallWeekRow {
  week_start: string;
  count: number;
  total_amount: number;
}
export interface NeedsOrderRow {
  job_id: number;
  job_code: string | null;
  account_name: string;
  community_name: string | null;
  lot_number: string | null;
  address: string;
  install_date: string;
  status: string;
}

export interface JobPLRow {
  job_id: number;
  job_code: string | null;
  account_name: string;
  community_name: string | null;
  lot_number: string | null;
  g_code: string | null;
  i_code: string | null;
  revenue: number;
  revenue_source: string;
  builder_po: string | null;
  po_check_number: string | null;
  po_paid_date: string | null;
  product_cost: number;
  labor_revenue: number;
  labor_cost: number;
  other_labor_net: number;
  wash_labor_net: number;
  margin: number;
  margin_pct: number | null;
  other_labor_codes: string | null;
  wash_labor_codes: string | null;
}
export interface JobPLReport {
  rows: JobPLRow[];
  total_revenue: number;
  total_cost: number;
  total_other_labor_net: number;
  total_wash_labor_net: number;
  total_margin: number;
  margin_pct: number | null;
  count: number;
  with_other_labor: number;
  drh_po_count: number;
  updated_at: string | null;
}
export const getJobPL = () => api<JobPLReport>("/reports/job-pl");
export const refreshJobPL = () =>
  api<Record<string, unknown>>("/reports/job-pl/refresh", { method: "POST" });

export interface OtherLaborRow {
  job_id: number;
  job_code: string | null;
  account_name: string;
  community_name: string | null;
  lot_number: string | null;
  i_code: string | null;
  c9009_margin: number;
  other_labor_net: number;
  all_in_margin: number;
  wash_labor_net: number;
  other_labor_codes: string | null;
  wash_labor_codes: string | null;
}
export interface WashCodeTotal {
  code: string;
  total: number;
  houses: number;
}
export interface OtherLaborReport {
  rows: OtherLaborRow[];
  count: number;
  total_other_labor_net: number;
  total_c9009_margin: number;
  total_all_in_margin: number;
  total_wash_labor_net: number;
  excluded_codes: string[];
  wash_by_code: WashCodeTotal[];
  updated_at: string | null;
}
export const getOtherLabor = () => api<OtherLaborReport>("/reports/other-labor");

export interface DomoCell {
  revenue: number;
  cost: number;
  product_margin: number;
  c9009_margin: number;
  other_labor_net: number;
  wash_labor_net: number;
  margin: number;
  margin_pct: number | null;
  jobs: number;
}
export interface DomoPeriod {
  key: string;
  label: string;
  start: string;
  end: string;
}
export interface DomoPLRow {
  label: string;
  sublabel: string | null;
  cells: DomoCell[];
}
export interface DomoPLReport {
  mode: string;
  builder: string | null;
  job: string | null;
  note: string | null;
  source: string | null;
  no_data: boolean;
  periods: DomoPeriod[];
  totals: DomoCell[];
  rows: DomoPLRow[];
  updated_at: string | null;
}
export const getDomoPL = (params: Record<string, string> = {}) => {
  const qs = new URLSearchParams(params).toString();
  return api<DomoPLReport>(`/reports/domo-pl${qs ? `?${qs}` : ""}`);
};
export const getDomoBuilders = () => api<string[]>("/reports/domo-pl/builders");
export const refreshDomoPL = () =>
  api<Record<string, unknown>>("/reports/domo-pl/refresh", { method: "POST" });

export interface OpenServiceRow {
  sr_id: number;
  job_id: number;
  job_code: string | null;
  account_name: string;
  community_name: string | null;
  lot_number: string | null;
  address: string;
  title: string | null;
  status: string;
  material_status: string | null;
  created_at: string;
  scheduled_date: string | null;
  open_lines: number;
  total_lines: number;
}
export const getOpenService = () => api<OpenServiceRow[]>("/reports/open-service");

export const getReportsList = () => api<ReportInfo[]>("/reports");

// --- PO Receipts (Deliveries) ----------------------------------------------
export interface PoReceiptRow {
  receipt_number: string;
  receipt_date: string | null;
  pos: string | null;
  supplier: string | null;
  supplier_cost: number | null;
  landed_cost: number | null;
  order_number: string | null;
  job_code: string | null;
  vendor: string | null;
  product: string | null;
  order_date: string | null;
  job_id: number | null;
  address: string | null;
  community_name: string | null;
  account_name: string | null;
  status: string | null;
  install_date: string | null;
}
export interface PoOutstandingRow {
  order_number: string;
  job_code: string | null;
  vendor: string | null;
  product: string | null;
  order_date: string | null;
  tent_due_date: string | null;
  days_overdue: number | null;
  job_id: number | null;
  address: string | null;
  community_name: string | null;
  account_name: string | null;
  status: string | null;
  install_date: string | null;
}
export interface PoReceiptsReport {
  as_of: string;
  total_receipts: number;
  received_this_month: number;
  matched_to_job: number;
  outstanding_count: number;
  rows: PoReceiptRow[];
  outstanding: PoOutstandingRow[];
}
export const getPoReceipts = () => api<PoReceiptsReport>("/reports/po-receipts");
export const refreshPoReceipts = () =>
  api<Record<string, unknown>>("/reports/po-receipts/refresh", { method: "POST" });

// --- Manager Sales Report ---------------------------------------------------
export interface InstalledPeriod {
  label: string;
  count: number;
  po_total: number;
}
export interface KsrSalesRow {
  ksr: string;
  count: number;
  po_total: number;
  is_new_q2: boolean;
}
export interface KsrMilesRow {
  ksr: string;
  jobs: number;
  monthly_miles: number;
}
export interface ManagerReport {
  generated_at: string;
  as_of: string;
  roster: string[];
  installed: Record<"current_month" | "previous_month" | "previous_quarter" | "ytd", InstalledPeriod>;
  open_pipeline: { count: number; po_total: number };
  by_ksr: KsrSalesRow[];
  pl_net_sales: { value: number | null; source_file: string; label: string | null } | null;
  capacity: {
    active_houses: number;
    houses_per_person: number;
    field_people_needed: number | null;
    coverage_sq_miles: number;
    trips_per_job: number;
    by_ksr_miles: KsrMilesRow[];
    miles_estimated: boolean;
    total_monthly_miles: number;
  };
}
export const getManagerReport = () => api<ManagerReport>("/reports/manager");
export const getShareStatus = () => api<{ token: string | null }>("/reports/manager/share");
export const enableShare = () =>
  api<{ token: string }>("/reports/manager/share", { method: "POST" });
export const disableShare = () =>
  api<{ token: null }>("/reports/manager/share", { method: "DELETE" });

/** Public (no auth) — used by the shareable link page. */
export async function getPublicManagerReport(token: string): Promise<ManagerReport> {
  const resp = await fetch(`/api/reports/manager/public?token=${encodeURIComponent(token)}`);
  if (!resp.ok) throw new Error("This report link is invalid or has been turned off.");
  return resp.json();
}
export const getOpenPO = () => api<OpenPOReport>("/reports/open-po");
export const getPoStatus = () => api<StatusSummaryRow[]>("/reports/po-status");
export const getRevenueBuilder = () => api<RevenueGroup[]>("/reports/revenue-builder");
export const getRevenueSalesperson = () => api<RevenueGroup[]>("/reports/revenue-salesperson");
export const getInstallWeek = () => api<InstallWeekRow[]>("/reports/install-week");
export const getNeedsOrdering = () => api<NeedsOrderRow[]>("/reports/unordered");

export interface InstallItem {
  job_id: number;
  job_code: string | null;
  address: string;
  account_name: string;
  community_name: string | null;
  lot_number: string | null;
  status: JobStatus;
  install_date: string;
  salesperson: string | null;
}

export const getInstalls = (params: Record<string, string>) => {
  const qs = new URLSearchParams(params).toString();
  return api<InstallItem[]>(`/schedule/installs?${qs}`);
};

export const getOrderingBoard = (params: Record<string, string> = {}) => {
  const qs = new URLSearchParams(params).toString();
  return api<OrderingBoardRow[]>(`/ordering${qs ? `?${qs}` : ""}`);
};

export const listQuotes = (jobId: number) => api<Quote[]>(`/jobs/${jobId}/quotes`);
export const getQuote = (id: number) => api<QuoteDetail>(`/quotes/${id}`);
export const createQuote = (jobId: number, name: string) =>
  api<Quote>(`/jobs/${jobId}/quotes`, { method: "POST", body: JSON.stringify({ name }) });
export const acceptQuote = (id: number) => api<Quote>(`/quotes/${id}/accept`, { method: "POST" });
export const deleteQuote = (id: number) => api<void>(`/quotes/${id}`, { method: "DELETE" });
export const addQuoteLine = (quoteId: number, data: Record<string, unknown>) =>
  api<QuoteLine>(`/quotes/${quoteId}/lines`, { method: "POST", body: JSON.stringify(data) });
export const deleteQuoteLine = (id: number) => api<void>(`/quote-lines/${id}`, { method: "DELETE" });

export const listOrders = (jobId: number) => api<Order[]>(`/jobs/${jobId}/orders`);
export const createOrder = (jobId: number, data: Record<string, unknown>) =>
  api<Order>(`/jobs/${jobId}/orders`, { method: "POST", body: JSON.stringify(data) });
export const updateOrder = (id: number, data: Record<string, unknown>) =>
  api<Order>(`/orders/${id}`, { method: "PATCH", body: JSON.stringify(data) });

export async function downloadOrderFile(orderId: number): Promise<void> {
  const resp = await fetch(`/api/orders/${orderId}/file`, {
    headers: { Authorization: `Bearer ${getToken()}` },
  });
  if (!resp.ok) throw new Error("Download failed");
  const disposition = resp.headers.get("content-disposition") ?? "";
  const match = disposition.match(/filename="?([^";]+)"?/);
  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = match?.[1] ?? `everluxe-order-${orderId}.xlsx`;
  a.click();
  URL.revokeObjectURL(url);
}

export const addRoom = (jobId: number, data: Record<string, unknown>) =>
  api<RoomSelection>(`/jobs/${jobId}/rooms`, { method: "POST", body: JSON.stringify(data) });
export const deleteRoom = (id: number) => api<void>(`/rooms/${id}`, { method: "DELETE" });
export const addHardware = (jobId: number, data: Record<string, unknown>) =>
  api<HardwareSelection>(`/jobs/${jobId}/hardware`, { method: "POST", body: JSON.stringify(data) });
export const deleteHardware = (id: number) => api<void>(`/hardware/${id}`, { method: "DELETE" });

// --- Service requests -------------------------------------------------------
export interface ServicePart {
  id: number;
  part: string;
  cabinet: string | null;
  style: string | null;
  color: string | null;
  vendor: string | null;
  order_number: string | null;
  order_date: string | null;
  due_date: string | null;
  qty: number;
  notes: string | null;
}
export interface ServiceLine {
  id: number;
  part_id: number | null;
  instruction: string;
  done: boolean;
  done_by: string | null;
  done_at: string | null;
  note: string | null;
}
export interface ServiceRequestSummary {
  id: number;
  job_id: number;
  title: string | null;
  status: string;
  created_by: string | null;
  created_at: string;
  part_count: number;
  line_count: number;
}
export interface ServiceRequestDetail {
  id: number;
  job_id: number;
  job_code: string | null;
  address: string;
  account_name: string | null;
  community_name: string | null;
  lot_number: string | null;
  title: string | null;
  status: string;
  material_status: string | null;
  scheduled_date: string | null;
  created_by: string | null;
  created_at: string;
  parts: ServicePart[];
  lines: ServiceLine[];
  rooms: RoomSelection[];
  hardware: HardwareSelection[];
}

export interface CommunityServiceRow {
  id: number;
  job_id: number;
  job_code: string | null;
  lot_number: string | null;
  address: string;
  status: string;
  material_status: string | null;
  scheduled_date: string | null;
  part_count: number;
  open_lines: number;
  total_lines: number;
  created_at: string;
}

export const listServiceRequests = (jobId: number) =>
  api<ServiceRequestSummary[]>(`/jobs/${jobId}/service-requests`);
export const listCommunityServiceRequests = (communityId: number) =>
  api<CommunityServiceRow[]>(`/communities/${communityId}/service-requests`);
export const createServiceRequest = (jobId: number, title: string | null) =>
  api<ServiceRequestDetail>(`/jobs/${jobId}/service-requests`, {
    method: "POST",
    body: JSON.stringify({ title }),
  });
export const getServiceRequest = (id: number) =>
  api<ServiceRequestDetail>(`/service-requests/${id}`);
export const patchServiceRequest = (id: number, data: Record<string, unknown>) =>
  api<ServiceRequestDetail>(`/service-requests/${id}`, { method: "PATCH", body: JSON.stringify(data) });
export const deleteServiceRequest = (id: number) =>
  api<void>(`/service-requests/${id}`, { method: "DELETE" });
export const addServicePart = (id: number, data: Record<string, unknown>) =>
  api<ServicePart>(`/service-requests/${id}/parts`, { method: "POST", body: JSON.stringify(data) });
export const deleteServicePart = (partId: number) =>
  api<void>(`/service-parts/${partId}`, { method: "DELETE" });
export const addServiceLine = (id: number, data: Record<string, unknown>) =>
  api<ServiceLine>(`/service-requests/${id}/lines`, { method: "POST", body: JSON.stringify(data) });
export const patchServiceLine = (lineId: number, data: Record<string, unknown>) =>
  api<ServiceLine>(`/service-lines/${lineId}`, { method: "PATCH", body: JSON.stringify(data) });
export const deleteServiceLine = (lineId: number) =>
  api<void>(`/service-lines/${lineId}`, { method: "DELETE" });

export async function downloadServiceTemplate(): Promise<void> {
  const resp = await fetch("/api/forms/service-template", {
    headers: { Authorization: `Bearer ${getToken()}` },
  });
  if (!resp.ok) throw new Error("Download failed");
  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "Service Request Template.xlsx";
  a.click();
  URL.revokeObjectURL(url);
}

export async function importServiceExcel(file: File): Promise<ServiceRequestDetail> {
  const fd = new FormData();
  fd.append("file", file);
  const resp = await fetch("/api/service-requests/import", {
    method: "POST",
    headers: { Authorization: `Bearer ${getToken()}` },
    body: fd,
  });
  if (!resp.ok) {
    const detail = (await resp.json().catch(() => null))?.detail;
    throw new Error(typeof detail === "string" ? detail : `Import failed (${resp.status})`);
  }
  return resp.json();
}

// --- Team notes & tasks -----------------------------------------------------
export const NOTE_TYPES: { value: string; label: string }[] = [
  { value: "urgent", label: "Urgent" },
  { value: "action", label: "Action Needed" },
  { value: "fyi", label: "FYI" },
  { value: "question", label: "Question" },
  { value: "blocker", label: "Blocker" },
];

export interface NoteRow {
  id: number;
  body: string;
  note_type: string;
  job_id: number | null;
  job_code: string | null;
  job_address: string | null;
  author_email: string;
  author_name: string | null;
  assignee_email: string | null;
  assignee_name: string | null;
  due_date: string | null;
  completed_at: string | null;
  completed_by: string | null;
  parent_id: number | null;
  created_at: string;
  tags: string[];
  is_task: boolean;
  is_overdue: boolean;
  unread: boolean;
  replies: NoteRow[];
}

export interface NoteInput {
  body: string;
  note_type?: string;
  job_id?: number | null;
  assignee_email?: string | null;
  due_date?: string | null;
  tags?: string[];
  parent_id?: number | null;
}

export const listNotes = (params: { scope?: string; job_id?: number; show_done?: boolean } = {}) => {
  const usp = new URLSearchParams();
  if (params.scope) usp.set("scope", params.scope);
  if (params.job_id != null) usp.set("job_id", String(params.job_id));
  if (params.show_done) usp.set("show_done", "true");
  const qs = usp.toString();
  return api<NoteRow[]>(`/notes${qs ? `?${qs}` : ""}`);
};
export const createNote = (data: NoteInput) =>
  api<NoteRow>("/notes", { method: "POST", body: JSON.stringify(data) });
export const completeNote = (id: number, done = true) =>
  api<NoteRow>(`/notes/${id}/complete?done=${done}`, { method: "POST" });
export const deleteNote = (id: number) => api<void>(`/notes/${id}`, { method: "DELETE" });
export const markNotesRead = (ids: number[]) =>
  api<{ marked: number }>("/notes/read", { method: "POST", body: JSON.stringify(ids) });
export const noteUnreadCount = () => api<{ count: number }>("/notes/unread-count");

/** True only for the Order Pack allowlist — /pack/meta 403s for everyone else.
 *  Used to decide whether the private "Bulk Ordering" button is shown. */
export async function isOrderPackOwner(): Promise<boolean> {
  try {
    const resp = await fetch("/api/ordering-platform/pack/meta", {
      headers: { Authorization: `Bearer ${getToken()}` },
    });
    return resp.ok;
  } catch {
    return false;
  }
}
