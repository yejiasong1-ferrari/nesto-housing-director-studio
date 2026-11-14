/** Admin Console API client — uses X-Admin-Key from sessionStorage (not beta cookie). */

const API_URL = (
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
).replace(/\/$/, "");

export const ADMIN_KEY_STORAGE = "nesto_admin_key";

export function getAdminKey(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return sessionStorage.getItem(ADMIN_KEY_STORAGE);
  } catch {
    return null;
  }
}

export function setAdminKey(key: string) {
  sessionStorage.setItem(ADMIN_KEY_STORAGE, key);
}

export function clearAdminKey() {
  sessionStorage.removeItem(ADMIN_KEY_STORAGE);
}

async function parseError(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") return body.detail;
    return JSON.stringify(body?.detail || body);
  } catch {
    return res.statusText || `HTTP ${res.status}`;
  }
}

export async function adminFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const key = getAdminKey();
  if (!key) throw new Error("Admin key required");
  const headers = new Headers(init.headers || {});
  headers.set("X-Admin-Key", key);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  return fetch(`${API_URL}${path}`, { ...init, headers });
}

export async function adminJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await adminFetch(path, init);
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<T>;
}

export type AdminUser = {
  id: string;
  invite_code: string;
  status: string;
  device_id?: string | null;
  created_at?: string | null;
  expires_at?: string | null;
  remaining_seconds?: number | null;
  project_count: number;
  video_count: number;
  online: boolean;
  current_page?: string | null;
  current_project?: string | null;
  current_stage?: string | null;
};

export type AdminProject = {
  project_id: string;
  title: string;
  status: string;
  brief?: string;
  beta_account_id?: string | null;
  invite_code?: string | null;
  final_video?: string | null;
  has_final?: boolean;
  download_url?: string | null;
  stage?: string;
  progress?: number;
  workspace_slug?: string | null;
  error?: string;
};

export type AdminInvite = {
  code: string;
  status: string;
  remaining_seconds?: number | null;
  expires_at?: string | null;
  created_at?: string | null;
  beta_account_id?: string | null;
  account_status?: string | null;
  project_count: number;
  video_count: number;
  online: boolean;
};

export type AdminJob = {
  job_id: string;
  project_id: string;
  title?: string | null;
  beta_account_id?: string | null;
  invite_code?: string | null;
  kind?: string;
  status: string;
  stage?: string;
  progress?: number;
  error?: string;
  has_final?: boolean;
  download_url?: string | null;
};

/** <video src> friendly URL — Railway 302 to R2, no custom header needed. */
export function adminProjectStreamUrl(projectId: string): string | null {
  const key = getAdminKey();
  if (!key) return null;
  return `${API_URL}/api/admin/projects/${encodeURIComponent(projectId)}/stream?admin_key=${encodeURIComponent(key)}`;
}
