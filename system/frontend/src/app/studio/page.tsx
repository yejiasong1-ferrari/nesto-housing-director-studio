"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/** Legacy path — redirect to home Studio. */
export default function StudioRedirectPage() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/");
  }, [router]);
  return (
    <main className="mx-auto max-w-lg px-6 py-16 text-studio-muted text-sm">
      Opening Studio…
    </main>
  );
}
