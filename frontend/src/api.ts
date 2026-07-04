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

export async function login(email: string, password: string): Promise<void> {
  const body = new URLSearchParams({ username: email, password });
  const resp = await fetch("/api/auth/token", { method: "POST", body });
  if (!resp.ok) {
    const detail = (await resp.json().catch(() => null))?.detail;
    throw new Error(detail ?? "Login failed");
  }
  const data = await resp.json();
  setToken(data.access_token);
}

export async function fetchMe(): Promise<User> {
  const resp = await fetch("/api/auth/me", {
    headers: { Authorization: `Bearer ${getToken()}` },
  });
  if (!resp.ok) {
    setToken(null);
    throw new Error("Session expired");
  }
  return resp.json();
}
