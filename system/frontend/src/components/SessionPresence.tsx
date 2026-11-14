"use client";

import { usePathname } from "next/navigation";
import { useSessionHeartbeat } from "@/lib/useSessionHeartbeat";

/** Site-wide heartbeat so Admin force-logout is detected outside Studio too. */
export function SessionPresence() {
  const pathname = usePathname() || "app";
  useSessionHeartbeat({
    currentPage: pathname.startsWith("/admin") ? "admin" : pathname || "app",
  });
  return null;
}
