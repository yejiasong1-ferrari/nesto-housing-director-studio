"use client";

import { CheckCircle2, CircleDashed, Loader2, XCircle } from "lucide-react";
import type { Job } from "@/lib/studioApi";

function StageIcon({ status }: { status: string }) {
  if (status === "done") return <CheckCircle2 size={16} className="text-studio-accent2 shrink-0" />;
  if (status === "running")
    return <Loader2 size={16} className="text-studio-process animate-spin shrink-0" />;
  if (status === "error" || status === "cancelled")
    return <XCircle size={16} className="text-studio-danger shrink-0" />;
  return <CircleDashed size={16} className="text-[#D9D4C8] shrink-0" />;
}

export default function JobProgress({ job }: { job: Job }) {
  const progress = typeof job.progress === "number" ? job.progress : null;
  const showBar = progress != null && job.status !== "pending";

  return (
    <div className="space-y-3">
      {showBar ? (
        <div className="space-y-2 gen-fade-in">
          <div className="flex items-baseline justify-between gap-3">
            <p className="text-sm text-studio-primary truncate">
              {job.stage || (job.status === "running" ? "Working…" : "")}
            </p>
            <p className="tabular-nums text-sm font-medium text-studio-accent2 shrink-0">
              {Math.min(100, Math.max(0, progress))}%
            </p>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-[#EFE8DC]">
            <div
              className="h-full rounded-full bg-gradient-to-r from-[#C8A96E] to-[#3A9D9A] gen-progress-sheen transition-[width] duration-700 ease-out"
              style={{
                width: `${Math.max(
                  4,
                  Math.min(100, progress || (job.status === "running" ? 3 : 0))
                )}%`,
              }}
            />
          </div>
        </div>
      ) : null}

      <div className="space-y-2.5">
        {job.stages.map((s, i) => (
          <div
            key={s.name}
            className="flex items-center gap-2.5 text-sm gen-stage-row"
            style={{ animationDelay: `${i * 70}ms` }}
          >
            <StageIcon status={s.status} />
            <span
              className={
                s.status === "done"
                  ? "text-studio-primary"
                  : s.status === "running"
                  ? "text-studio-process"
                  : s.status === "error" || s.status === "cancelled"
                  ? "text-studio-danger"
                  : "text-studio-muted"
              }
            >
              {s.label}
            </span>
            {s.detail ? (
              <span className="text-xs text-studio-muted truncate">— {s.detail}</span>
            ) : null}
            {s.status === "running" ? (
              <span className="ml-auto flex gap-1 shrink-0" aria-hidden>
                <span className="gen-dot" />
                <span className="gen-dot" style={{ animationDelay: "0.2s" }} />
                <span className="gen-dot" style={{ animationDelay: "0.4s" }} />
              </span>
            ) : null}
          </div>
        ))}
      </div>
      {job.status === "error" && job.error && (
        <p className="text-xs text-studio-danger pt-1">{job.error}</p>
      )}
    </div>
  );
}
