"use client";

import { useState } from "react";
import { X } from "lucide-react";
import type { TimelineSegment } from "@/lib/studioApi";

interface Props {
  segment: TimelineSegment;
  onClose: () => void;
  onSave: (text: string) => void;
  saving: boolean;
}

export default function ScriptEditorModal({ segment, onClose, onSave, saving }: Props) {
  const [text, setText] = useState(segment.narration_text);

  return (
    <div className="fixed inset-0 bg-zinc-900/30 backdrop-blur-[2px] flex items-center justify-center z-50 px-4">
      <div className="w-full max-w-lg rounded-xl border border-studio-border bg-studio-panel p-5">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-sm font-medium text-studio-text">Edit Narration</h3>
            <p className="text-[11px] text-studio-muted">
              {segment.room_type || segment.id} · {segment.role}
            </p>
          </div>
          <button onClick={onClose} className="text-studio-muted hover:text-studio-text">
            <X size={18} />
          </button>
        </div>

        <p className="text-[11px] uppercase tracking-wide text-studio-muted mb-1">Original</p>
        <p className="text-[12.5px] text-studio-muted mb-4 leading-relaxed">
          {segment.narration_text || "—"}
        </p>

        <p className="text-[11px] uppercase tracking-wide text-studio-muted mb-1.5">New</p>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={4}
          className="w-full rounded-lg border border-studio-border bg-studio-panel2 px-3 py-2 text-sm text-studio-text outline-none focus:border-studio-accent/60 resize-none"
          placeholder="Describe what's visible in this scene..."
        />
        <p className="text-[10.5px] text-studio-muted mt-1.5">
          Saving re-records the voiceover for this scene only and refreshes the preview.
        </p>

        <div className="flex justify-end gap-2 mt-4">
          <button
            onClick={onClose}
            disabled={saving}
            className="px-3 py-1.5 rounded-md text-sm text-studio-muted hover:text-studio-text disabled:opacity-40"
          >
            Cancel
          </button>
          <button
            onClick={() => onSave(text)}
            disabled={saving || !text.trim() || text.trim() === segment.narration_text.trim()}
            className="px-4 py-1.5 rounded-md bg-studio-accent hover:bg-studio-accentHover text-studio-primary text-sm font-medium disabled:opacity-30"
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
