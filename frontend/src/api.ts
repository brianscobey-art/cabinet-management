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
  "quote",
  "field_measure",
  "ordered",
  "delivery",
  "install",
  "quality",
  "punch",
  "warranty",
  "closed",
] as const;
export type JobStatus = (typeof JOB_STATUSES)[number];
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
  status: JobStatus;
  install_date: string | null;
  warranty_start_date: string | null;
  sales_contact_name: string;
  sales_contact_phone: string | null;
  sales_contact_email: string | null;
  field_contact_name: string;
  field_contact_phone: string | null;
  field_contact_email: string | null;
  notes: string | null;
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

export const listAccounts = () => api<Account[]>("/accounts");
export const getAccount = (id: number) => api<AccountDetail>(`/accounts/${id}`);
export const createAccount = (data: { name: string; type: string }) =>
  api<Account>("/accounts", { method: "POST", body: JSON.stringify(data) });
export const createCommunity = (data: { account_id: number; name: string; market?: string }) =>
  api<Community>("/communities", { method: "POST", body: JSON.stringify(data) });
export const listCommunities = (accountId: number) =>
  api<Community[]>(`/communities?account_id=${accountId}`);

export const listJobs = (params: Record<string, string> = {}) => {
  const qs = new URLSearchParams(params).toString();
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
export interface InstallItem {
  job_id: number;
  job_code: string | null;
  address: string;
  account_name: string;
  community_name: string | null;
  lot_number: string | null;
  status: JobStatus;
  install_date: string;
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
