"use client";

import { useEffect } from "react";
import { authHeaders, getSessionToken } from "@/lib/session";
import { handleUnauthorizedResponse } from "@/lib/authFailure";

const API_URL = (
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
).replace(/\/$/, "");

/**
 * Ping /api/session/heartbeat every 30s so Admin Console can show online status.
 * Also surfaces force-logout (account_revoked) within ~30s.
 */
export function useSessionHeartbeat(opts?: {
  currentPage?: string;
  currentProject?: string | null;
  currentStage?: string | null;
}) {
  const page = opts?.currentPage || "studio";
  const project = opts?.currentProject || null;
  const stage = opts?.currentStage || null;

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!getSessionToken()) return;

    let cancelled = false;

    const beat = async () => {
      if (cancelled || !getSessionToken()) return;
      try {
        const res = await fetch(`${API_URL}/api/session/heartbeat`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(authHeaders() as Record<string, string>),
          },
          credentials: "include",
          body: JSON.stringify({
            current_page: page,
            current_project: project,
            current_stage: stage,
          }),
        });
        if (res.status === 401) {
          await handleUnauthorizedResponse(res);
        }
      } catch {
        /* ignore transient errors */
      }
    };

    void beat();
    const id = window.setInterval(() => void beat(), 10000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [page, project, stage]);
}
