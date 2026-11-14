"use client";

import { ChevronDown, Plus } from "lucide-react";
import { useState } from "react";
import type { ProjectSummary } from "@/lib/studioApi";
import BrandMark from "@/components/BrandMark";

interface Props {
  projects: ProjectSummary[];
  selectedSlug: string | null;
  onSelect: (slug: string) => void;
  onNewProject: () => void;
}

export default function Header({
  projects,
  selectedSlug,
  onSelect,
  onNewProject,
}: Props) {
  const [open, setOpen] = useState(false);
  const selected = projects.find((p) => p.slug === selectedSlug);

  return (
    <header className="relative z-50 border-b border-studio-border bg-studio-panel px-6 py-3 flex items-center justify-between shrink-0">
      <BrandMark size="header" />

      <div className="flex items-center gap-3">
        <div className="relative z-50">
          <button
            onClick={() => setOpen((v) => !v)}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-studio-border bg-studio-panel2 hover:border-studio-accent text-sm text-studio-primary min-w-[220px] justify-between transition-colors"
          >
            <span className="truncate">
              {selected ? selected.video_name : "Select a project"}
            </span>
            <ChevronDown size={14} className="text-studio-muted shrink-0" />
          </button>
          {open && (
            <>
              <button
                type="button"
                aria-label="Close project list"
                className="fixed inset-0 z-40 cursor-default bg-transparent"
                onClick={() => setOpen(false)}
              />
              <div className="absolute left-0 right-0 mt-1 w-full max-h-96 overflow-y-auto rounded-lg border border-studio-border bg-studio-panel shadow-panel z-50">
                {projects.length === 0 && (
                  <div className="px-3 py-3 text-sm text-studio-muted">No projects yet</div>
                )}
                {projects.map((p) => (
                  <button
                    key={p.slug}
                    onClick={() => {
                      onSelect(p.slug);
                      setOpen(false);
                    }}
                    className={`w-full text-left px-3 py-2.5 hover:bg-studio-panel2 border-b border-studio-border/60 last:border-0 ${
                      p.slug === selectedSlug ? "bg-studio-panel2" : ""
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm text-studio-primary truncate">
                        {p.video_name}
                      </span>
                      {p.overall_score != null && (
                        <span className="text-[11px] text-studio-accent2 shrink-0">
                          {Math.round(p.overall_score)}
                        </span>
                      )}
                    </div>
                    <p className="text-[11px] text-studio-muted truncate mt-0.5">
                      {p.director_brief || "No brief"}
                    </p>
                  </button>
                ))}
              </div>
            </>
          )}
        </div>

        <button
          onClick={onNewProject}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-studio-accent hover:bg-studio-accentHover text-studio-primary text-sm font-medium transition-colors"
        >
          <Plus size={15} />
          New Project
        </button>
      </div>
    </header>
  );
}
