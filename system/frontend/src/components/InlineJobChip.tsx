"use client";

import { Loader2, X } from "lucide-react";
import type { Job } from "@/lib/studioApi";

interface Props {
  job: Job;
  onCancel: () => void;
  onDismiss?: () => void;
}

export default function InlineJobChip({ job, onCancel, onDismiss }: Props) {
  const running = job.status === "running" || job.status === "pending";
  const done = job.status === "done";
  const failed = job.status === "error" || job.status === "cancelled";

  const total = Math.max(job.stages.length, 1);
  const finished = job.stages.filter((s) => s.status === "done").length;
  const activeBoost = job.stages.some((s) => s.status === "running") ? 0.35 : 0;
  const fromStages = Math.min(99, Math.round(((finished + activeBoost) / total) * 100));
  const percent = done
    ? 100
    : typeof job.progress === "number" && job.progress > 0
    ? Math.min(99, job.progress)
    : failed
    ? Math.round((finished / total) * 100)
    : fromStages;

  const label = done
    ? "Final video ready"
    : job.status === "cancelled"
    ? "Cancelled"
    : failed
    ? "Failed"
    : job.stage ||
      job.stages.find((s) => s.status === "running")?.label ||
      "Generating…";

  return (
    <div className="flex items-center gap-2 min-w-0 max-w-md rounded-full border border-studio-border bg-studio-panel shadow-sm pl-3 pr-1.5 py-1">
      {running && <Loader2 size={14} className="text-studio-process animate-spin shrink-0" />}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-[11px] text-studio-primary truncate">{label}</span>
          <span className="text-[10px] text-studio-muted tabular-nums shrink-0">{percent}%</span>
        </div>
        <div className="mt-0.5 h-1 rounded-full bg-studio-panel2 overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-300 ${
              failed ? "bg-studio-danger/70" : done ? "bg-studio-accent2" : "bg-studio-accent"
            }`}
            style={{ width: `${percent}%` }}
          />
        </div>
      </div>
      {running ? (
        <button
          type="button"
          onClick={onCancel}
          className="shrink-0 w-7 h-7 rounded-full text-studio-muted hover:text-studio-danger hover:bg-studio-panel2 flex items-center justify-center"
          title="Cancel generation"
          aria-label="Cancel generation"
        >
          <X size={14} />
        </button>
      ) : (
        onDismiss && (
          <button
            type="button"
            onClick={onDismiss}
            className="shrink-0 w-7 h-7 rounded-full text-studio-muted hover:text-studio-text hover:bg-studio-panel2 flex items-center justify-center"
            aria-label="Dismiss"
          >
            <X size={14} />
          </button>
        )
      )}
    </div>
  );
}
