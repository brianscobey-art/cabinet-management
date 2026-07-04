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

export const addRoom = (jobId: number, data: Record<string, unknown>) =>
  api<RoomSelection>(`/jobs/${jobId}/rooms`, { method: "POST", body: JSON.stringify(data) });
export const deleteRoom = (id: number) => api<void>(`/rooms/${id}`, { method: "DELETE" });
export const addHardware = (jobId: number, data: Record<string, unknown>) =>
  api<HardwareSelection>(`/jobs/${jobId}/hardware`, { method: "POST", body: JSON.stringify(data) });
export const deleteHardware = (id: number) => api<void>(`/hardware/${id}`, { method: "DELETE" });
