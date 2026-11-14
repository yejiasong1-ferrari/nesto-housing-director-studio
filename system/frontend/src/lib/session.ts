/** Beta invite session helpers (browser). */

export const SESSION_COOKIE = "nesto_session";
export const DEVICE_KEY = "nesto_device_id";

export function getCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

export function setSessionCookie(token: string, expiresIso?: string | null) {
  let maxAge = 60 * 60 * 3; // 3h default
  if (expiresIso) {
    const ms = new Date(expiresIso).getTime() - Date.now();
    if (Number.isFinite(ms) && ms > 0) maxAge = Math.floor(ms / 1000);
  }
  document.cookie = `${SESSION_COOKIE}=${encodeURIComponent(token)}; Path=/; Max-Age=${maxAge}; SameSite=Lax`;
}

export function clearSessionCookie() {
  document.cookie = `${SESSION_COOKIE}=; Path=/; Max-Age=0; SameSite=Lax`;
}

export function getSessionToken(): string | null {
  return getCookie(SESSION_COOKIE);
}

export function getOrCreateDeviceId(): string {
  if (typeof window === "undefined") return "server";
  try {
    const existing = localStorage.getItem(DEVICE_KEY);
    if (existing) return existing;
    const id =
      typeof crypto !== "undefined" && "randomUUID" in crypto
        ? `web_${crypto.randomUUID().replace(/-/g, "").slice(0, 16)}`
        : `web_${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`;
    localStorage.setItem(DEVICE_KEY, id);
    return id;
  } catch {
    return `web_anon_${Date.now()}`;
  }
}

export function authHeaders(extra?: HeadersInit): HeadersInit {
  const token = getSessionToken();
  const base: Record<string, string> = {};
  if (token) {
    base.Authorization = `Bearer ${token}`;
    base["X-Nesto-Session"] = token;
  }
  return { ...base, ...(extra as Record<string, string>) };
}
