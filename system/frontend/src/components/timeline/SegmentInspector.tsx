"use client";

import { useEffect, useState } from "react";
import { Pencil, SlidersHorizontal } from "lucide-react";
import type { TimelineSegment } from "@/lib/studioApi";

interface Props {
  segment: TimelineSegment | null;
  onEditNarration: (id: string) => void;
  onApplyOffset: (id: string, offset: number) => void;
  busy: boolean;
}

export default function SegmentInspector({
  segment,
  onEditNarration,
  onApplyOffset,
  busy,
}: Props) {
  const [offsetDraft, setOffsetDraft] = useState<number | null>(null);

  useEffect(() => {
    setOffsetDraft(null);
  }, [segment?.id, segment?.audio_offset]);

  if (!segment) {
    return (
      <div className="rounded-lg border border-studio-border bg-studio-panel p-5 text-sm text-studio-muted studio-panel-topline">
        Select a block on the timeline to inspect and edit that scene.
      </div>
    );
  }

  const offset = offsetDraft ?? segment.audio_offset;

  const hasAudio = segment.audio_duration > 0.1;
  const sceneWindow =
    segment.output_duration || segment.editing_window || segment.duration;
  const maxOffset = Math.max(0, Math.round((sceneWindow - segment.audio_duration - 0.02) * 10) / 10);

  return (
    <aside className="rounded-lg border border-studio-border bg-studio-panel p-5 space-y-5 studio-panel-topline border-l-[3px] border-l-studio-accent">
      <div>
        <p className="text-[11px] uppercase tracking-wide text-studio-muted mb-1">Inspector</p>
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-medium text-studio-primary">
            {segment.room_type || segment.id}
          </h3>
          <span className="px-1.5 py-0.5 rounded text-[10px] bg-studio-panel2 border border-studio-border text-studio-muted">
            {segment.role}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div className="rounded-lg border border-studio-border bg-studio-panel2 px-3 py-2">
          <p className="text-[11px] uppercase tracking-wide text-studio-muted mb-1">Duration</p>
          <p className="text-sm text-studio-text">
            {(segment.editing_window || segment.duration).toFixed(1)}s
          </p>
        </div>
        <div className="rounded-lg border border-studio-border bg-studio-panel2 px-3 py-2">
          <p className="text-[11px] uppercase tracking-wide text-studio-muted mb-1">
            Visual strategy
          </p>
          <p className="text-sm text-studio-text capitalize">
            {segment.visual_strategy.type.replace(/_/g, " ")}
          </p>
        </div>
      </div>

      {segment.highlight.length > 0 && (
        <div>
          <p className="text-[11px] uppercase tracking-wide text-studio-muted mb-1.5">
            Highlight
          </p>
          <div className="flex flex-wrap gap-1.5">
            {segment.highlight.map((h) => (
              <span
                key={h}
                className="px-2 py-0.5 rounded-md text-[11px] bg-studio-panel2 border border-studio-border text-studio-text"
              >
                {h}
              </span>
            ))}
          </div>
        </div>
      )}

      <div>
        <div className="flex items-center justify-between mb-1.5">
          <p className="text-[11px] uppercase tracking-wide text-studio-muted">Narration</p>
          <button
            type="button"
            onClick={() => onEditNarration(segment.id)}
            disabled={busy}
            className="flex items-center gap-1 text-[11px] text-studio-accent hover:text-studio-accentHover disabled:opacity-40"
          >
            <Pencil size={11} />
            Edit Narration
          </button>
        </div>
        <p className="text-sm text-studio-text leading-relaxed">
          {segment.narration_text || (
            <span className="text-studio-muted italic">No narration</span>
          )}
        </p>
      </div>

      <div>
        <div className="flex items-center gap-1.5 mb-2">
          <SlidersHorizontal size={12} className="text-studio-muted" />
          <p className="text-[11px] uppercase tracking-wide text-studio-muted">
            Adjust audio start
          </p>
          <span className="ml-auto text-[11px] tabular-nums text-studio-text">
            {offset.toFixed(1)}s
          </span>
        </div>
        {hasAudio ? (
          <>
            <input
              type="range"
              className="offset-slider"
              min={0}
              max={Math.max(0.1, maxOffset)}
              step={0.1}
              value={Math.min(offset, maxOffset)}
              disabled={maxOffset <= 0 || busy}
              onChange={(e) => setOffsetDraft(parseFloat(e.target.value))}
            />
            <p className="text-[10.5px] text-studio-muted mt-1.5">
              Drag the clip on the Audio track, or fine-tune here. Timing is
              saved when you Apply.
            </p>
            <div className="flex justify-end mt-2">
              <button
                onClick={() => {
                  onApplyOffset(segment.id, offset);
                  setOffsetDraft(null);
                }}
                disabled={offsetDraft === null || busy}
                className="px-3 py-1 rounded-md bg-studio-accent hover:bg-studio-accentHover text-studio-primary text-[11px] font-medium disabled:opacity-30"
              >
                Apply
              </button>
            </div>
          </>
        ) : (
          <p className="text-[12px] text-studio-muted">No narration audio for this scene yet.</p>
        )}
      </div>
    </aside>
  );
}
