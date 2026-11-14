"use client";

import { CheckCircle2, ChevronDown, Circle, Sparkles } from "lucide-react";
import { useState } from "react";
import type { ThinkingSummary } from "@/lib/studioApi";

const STAGE_LABELS: [string, string][] = [
  ["vision", "Understanding"],
  ["planner", "Planning"],
  ["script", "Narration"],
  ["voice", "Voice"],
  ["timeline", "Pacing"],
  ["editing", "Directing"],
  ["rendering", "Rendering"],
];

interface Props {
  stages: Record<string, boolean>;
  thinking: ThinkingSummary | null;
}

export default function StatusBar({ stages, thinking }: Props) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="border-b border-studio-border bg-studio-panel px-6 py-3 shrink-0">
      <div className="flex items-center gap-2 w-full">
        <div className="flex items-center flex-1 min-w-0">
          {STAGE_LABELS.map(([key, label], i) => {
            const done = stages[key];
            const keys = STAGE_LABELS.map(([k]) => k);
            const firstPending = keys.find((k) => !stages[k]);
            const current = key === firstPending;
            return (
              <div key={key} className="flex items-center flex-1 min-w-0">
                {i > 0 && (
                  <div
                    className={`flex-1 h-px mx-1.5 ${
                      done || current ? "bg-studio-accent2/50" : "bg-[#D9D4C8]"
                    }`}
                  />
                )}
                <div className="flex items-center gap-1.5 shrink-0">
                  {done ? (
                    <CheckCircle2 size={14} className="text-studio-accent2" />
                  ) : current ? (
                    <Circle size={14} className="text-studio-accent fill-studio-accent/30" />
                  ) : (
                    <Circle size={14} className="text-[#D9D4C8]" />
                  )}
                  <span
                    className={`text-xs whitespace-nowrap ${
                      done
                        ? "text-studio-primary"
                        : current
                        ? "text-studio-accent"
                        : "text-[#D9D4C8]"
                    }`}
                  >
                    {label}
                  </span>
                </div>
              </div>
            );
          })}
        </div>

        {thinking && (
          <button
            onClick={() => setExpanded((v) => !v)}
            className="flex items-center gap-1.5 text-xs text-studio-primary hover:text-studio-accent shrink-0 ml-4 transition-colors"
          >
            <Sparkles size={13} className="text-studio-accent2" />
            AI Director Thinking
            <ChevronDown
              size={13}
              className={`transition-transform ${expanded ? "rotate-180" : ""}`}
            />
          </button>
        )}
      </div>

      {expanded && thinking && (
        <div className="mt-3 grid grid-cols-3 gap-4 pt-3 border-t border-studio-border/70">
          <div className="rounded-xl bg-studio-thinking border border-studio-border/60 p-3">
            <p className="text-[11px] uppercase tracking-wide text-studio-muted mb-1.5">
              Detected spaces
            </p>
            <div className="flex flex-wrap gap-1.5">
              {thinking.rooms.map((r, i) => (
                <span
                  key={`${r.room}-${i}`}
                  className="px-2 py-0.5 rounded-full bg-studio-panel border border-studio-border text-[11px] text-studio-primary"
                >
                  {r.room}
                </span>
              ))}
            </div>
          </div>
          <div className="rounded-xl bg-studio-thinking border border-studio-border/60 p-3">
            <p className="text-[11px] uppercase tracking-wide text-studio-muted mb-1.5">
              Highlights found
            </p>
            <div className="flex flex-wrap gap-1.5">
              {thinking.highlights.map((h, i) => (
                <span
                  key={i}
                  className="px-2 py-0.5 rounded-full bg-[#C8A96E]/15 border border-studio-accent/40 text-[11px] text-studio-primary"
                >
                  {h}
                </span>
              ))}
            </div>
          </div>
          <div className="rounded-xl bg-studio-thinking border border-studio-border/60 p-3">
            <p className="text-[11px] uppercase tracking-wide text-studio-muted mb-1.5">
              Story arc · {thinking.narration_count} narration lines
            </p>
            <div className="flex items-center gap-1.5 text-[11px] text-studio-primary">
              <span className="px-2 py-0.5 rounded bg-studio-panel border border-studio-border">
                {thinking.story.opening.join(", ") || "opening"}
              </span>
              <span className="text-studio-muted">→</span>
              <span className="px-2 py-0.5 rounded bg-studio-panel border border-studio-border">
                {thinking.story.middle.join(", ") || "highlights"}
              </span>
              <span className="text-studio-muted">→</span>
              <span className="px-2 py-0.5 rounded bg-studio-panel border border-studio-border">
                {thinking.story.ending.join(", ") || "closing"}
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
