"use client";

import Link from "next/link";

/**
 * Full console is saved at `src/admin-console/AdminConsole.tsx`.
 * Flip `ADMIN_CONSOLE_ENABLED` and mount that component to turn it back on.
 */
export default function AdminDisabledPage() {
  return (
    <div className="min-h-screen flex items-center justify-center px-6 bg-zinc-950 text-zinc-100">
      <div className="w-full max-w-md space-y-4 border border-zinc-800 bg-zinc-900/95 rounded-3xl p-10 text-center">
        <p className="font-display text-2xl tracking-tight text-amber-400/95">Nesto Ops</p>
        <h1 className="font-display text-3xl text-zinc-50 tracking-tight">Admin Console</h1>
        <p className="text-sm text-zinc-400 leading-relaxed">
          This console is saved in the project and is not enabled on the live site.
        </p>
        <Link
          href="/"
          className="inline-flex items-center justify-center rounded-xl border border-zinc-700 px-4 py-2 text-sm text-zinc-200 hover:border-amber-500/50"
        >
          Back to Studio
        </Link>
      </div>
    </div>
  );
}
