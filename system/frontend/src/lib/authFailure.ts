/** Shared auth failure → invite page with optional reason modal. */

import { clearSessionCookie } from "@/lib/session";

export type AuthFailureDetail = {
  code?: string;
  message?: string;
};

export function parseAuthFailureDetail(body: unknown): AuthFailureDetail | null {
  if (!body || typeof body !== "object") return null;
  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail === "string") {
    return { message: detail };
  }
  if (detail && typeof detail === "object") {
    const d = detail as { code?: string; message?: string };
    return { code: d.code, message: d.message };
  }
  return null;
}

/** Redirect to invite with a reason flag for the forced-logout modal. */
export function redirectForAuthFailure(detail?: AuthFailureDetail | null) {
  if (typeof window === "undefined") return;
  clearSessionCookie();
  if (window.location.pathname.startsWith("/invite")) return;
  const code = detail?.code || "";
  const reason =
    code === "account_revoked"
      ? "revoked"
      : code === "session_expired"
        ? "expired"
        : "session";
  window.location.href = `/invite?reason=${encodeURIComponent(reason)}`;
}

export async function handleUnauthorizedResponse(res: Response): Promise<void> {
  if (res.status !== 401 || typeof window === "undefined") return;
  let detail: AuthFailureDetail | null = null;
  try {
    const body = await res.clone().json();
    detail = parseAuthFailureDetail(body);
  } catch {
    /* ignore */
  }
  redirectForAuthFailure(detail);
}
