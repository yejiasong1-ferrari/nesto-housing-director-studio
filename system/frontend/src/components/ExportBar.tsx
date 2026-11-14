"use client";

import { Download, Loader2, Wand2, X } from "lucide-react";
import type { Job } from "@/lib/studioApi";

interface Props {
  onExport: () => void;
  onCancel?: () => void;
  job: Job | null;
  finalUrl: string | null;
  disabled: boolean;
  hasPendingEdits?: boolean;
}

export default function ExportBar({
  onExport,
  onCancel,
  job,
  finalUrl,
  disabled,
  hasPendingEdits,
}: Props) {
  const running = job?.status === "running" || job?.status === "pending";

  let hint: string;
  if (running) {
    hint = "Rendering the final cut… you can keep editing; cancel anytime.";
  } else if (hasPendingEdits) {
    hint = "Edits are saved. Click Regenerate Video when you're ready.";
  } else if (finalUrl) {
    hint = "Final video is ready.";
  } else {
    hint = "Edit script and audio timing, then regenerate the final video.";
  }

  return (
    <div className="border-t border-studio-border bg-studio-panel/95 px-6 py-3 flex items-center justify-between shrink-0 shadow-[0_-8px_24px_rgba(22,43,73,0.04)]">
      <div className="min-w-0">
        <p className="text-[11px] uppercase tracking-wide text-studio-muted">Output</p>
        <div className="text-[12px] text-studio-muted truncate">{hint}</div>
      </div>
      <div className="flex items-center gap-2">
        {finalUrl && !running && (
          <a
            href={finalUrl}
            download
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-studio-accent2/15 border border-studio-accent2/40 text-sm text-studio-primary hover:bg-studio-accent2/25 transition-colors"
          >
            <Download size={14} className="text-studio-accent2" />
            Download
          </a>
        )}
        {running && onCancel && (
          <button
            type="button"
            onClick={onCancel}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg border border-studio-border text-sm text-studio-muted hover:text-studio-danger hover:border-studio-danger/40"
          >
            <X size={14} />
            Cancel
          </button>
        )}
        <button
          onClick={onExport}
          disabled={disabled || running}
          className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-studio-accent hover:bg-studio-accentHover text-studio-primary text-sm font-medium disabled:opacity-30 transition-colors"
        >
          {running ? (
            <Loader2 size={14} className="animate-spin text-studio-process" />
          ) : (
            <Wand2 size={14} />
          )}
          {running ? "Rendering…" : "Regenerate Video"}
        </button>
      </div>
    </div>
  );
}
