"use client";

import { useEffect } from "react";
import DirectorStudio from "@/components/DirectorStudio";
import { checkInviteSession } from "@/lib/saasApi";

/** Default entry: original Director Studio. */
export default function HomePage() {
  // Extra gate: if Admin revoked us, bounce to /invite even before next heartbeat.
  useEffect(() => {
    void checkInviteSession();
  }, []);
  return <DirectorStudio />;
}
