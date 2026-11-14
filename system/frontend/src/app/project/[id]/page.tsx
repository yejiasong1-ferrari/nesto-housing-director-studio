"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import {
  ArrowDown,
  Captions,
  CheckCircle2,
  Clapperboard,
  Clock3,
  FileText,
  Loader2,
  Route,
  ScanLine,
  Waves,
} from "lucide-react";
import BrandMark from "@/components/BrandMark";
import { createProjectJob, getProjectStatus, type ProjectStatusResponse } from "@/lib/saasApi";

const DIRECTOR_STAGES = [
  {
    name: "understanding",
    title: "Understanding the property",
    caption: "Reading rooms, fixtures, transitions, and usable moments.",
    min: 0,
    Icon: ScanLine,
  },
  {
    name: "planning",
    title: "Planning the walkthrough",
    caption: "Building a natural viewing sequence.",
    min: 18,
    Icon: Route,
  },
  {
    name: "story",
    title: "Writing the story",
    caption: "Drafting narration that follows what the viewer can see.",
    min: 38,
    Icon: FileText,
  },
  {
    name: "voice",
    title: "Creating the voice",
    caption: "Turning approved lines into scene-by-scene narration.",
    min: 56,
    Icon: Waves,
  },
  {
    name: "cut",
    title: "Directing the cut",
    caption: "Aligning scenes, narration bars, pacing, and transitions.",
    min: 72,
    Icon: Clapperboard,
  },
  {
    name: "finish",
    title: "Finishing your walkthrough",
    caption: "Final render, captions, audio mix, and delivery.",
    min: 90,
    Icon: Captions,
  },
] as const;

const DETECTED_SPACES = [
  "Living Room",
  "Kitchen",
  "Dining Area",
  "Primary Bedroom",
  "Bathroom",
  "Balcony",
  "Laundry",
  "Entry",
  "Guest Room",
  "Study",
  "Storage",
  "City View",
];

const WALKTHROUGH_FLOW = ["Living Room", "Dining", "Kitchen", "Bedroom", "Balcony"];
const SCRIPT_LINES = [
  "The main living area opens into a bright and spacious layout.",
  "Natural light carries through the dining zone and into the kitchen.",
  "Private rooms are introduced only once the viewer is inside the space.",
];

function getSessionStageIndex(progress: number, done: boolean) {
  if (done) return DIRECTOR_STAGES.length;
  let idx = 0;
  DIRECTOR_STAGES.forEach((stage, i) => {
    if (progress >= stage.min) idx = i;
  });
  return idx;
}

function getRevealCount(progress: number, total: number, start: number, end: number) {
  if (progress <= start) return 0;
  if (progress >= end) return total;
  const ratio = (progress - start) / (end - start);
  return Math.max(1, Math.min(total, Math.ceil(ratio * total)));
}

function DirectorSessionVisual({
  progress,
  activeIndex,
  videoUrl,
}: {
  progress: number;
  activeIndex: number;
  videoUrl: string | null;
}) {
  const spaceCount = getRevealCount(progress, DETECTED_SPACES.length, 4, 28);
  const flowCount = getRevealCount(progress, WALKTHROUGH_FLOW.length, 18, 44);
  const scriptCount = getRevealCount(progress, SCRIPT_LINES.length, 38, 62);
  const scenesReady = Math.min(12, Math.max(1, Math.round((Math.max(progress, 48) - 42) / 4.8)));
  const cutCount = getRevealCount(progress, WALKTHROUGH_FLOW.length, 72, 92);

  if (activeIndex >= DIRECTOR_STAGES.length) {
    return (
      <div className="rounded-lg bg-studio-thinking px-5 py-6 text-center studio-reveal-up">
        <CheckCircle2 size={32} className="mx-auto text-studio-accent2" />
        <h2 className="mt-3 font-display text-2xl font-semibold tracking-tight text-studio-primary">
          Your walkthrough is ready.
        </h2>
        <p className="mt-1 text-sm text-studio-muted">
          Review the cut, script, timing, and final export in Studio.
        </p>
      </div>
    );
  }

  if (activeIndex === 0) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)] gap-5">
        <div className="studio-thumbnail-scan aspect-video rounded-lg border border-studio-border bg-studio-video">
          {videoUrl ? (
            <video src={videoUrl} muted playsInline className="h-full w-full object-cover opacity-80" />
          ) : (
            <div className="h-full w-full bg-studio-primary/90" />
          )}
        </div>
        <div>
          <p className="text-sm font-medium text-studio-primary">
            {spaceCount || 1} spaces identified
          </p>
          <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 md:grid-cols-1 gap-2">
            {DETECTED_SPACES.slice(0, Math.max(1, spaceCount)).map((room, index) => (
              <div
                key={room}
                className="flex items-center gap-2 text-sm text-studio-primary studio-reveal-up"
                style={{ animationDelay: `${index * 70}ms` }}
              >
                <CheckCircle2 size={14} className="text-studio-accent2" />
                {room}
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (activeIndex === 1) {
    return (
      <div className="rounded-lg bg-studio-thinking px-5 py-5">
        <div className="flex flex-wrap items-center gap-2">
          {WALKTHROUGH_FLOW.slice(0, Math.max(1, flowCount)).map((room, index, rooms) => (
            <div key={room} className="flex items-center gap-2 studio-reveal-up" style={{ animationDelay: `${index * 80}ms` }}>
              <span className="rounded-lg border border-studio-border bg-studio-panel px-3 py-2 text-sm text-studio-primary">
                {room}
              </span>
              {index < rooms.length - 1 ? <ArrowDown size={14} className="rotate-[-90deg] text-studio-muted" /> : null}
            </div>
          ))}
        </div>
        <p className="mt-4 text-sm text-studio-muted">Building a natural viewing sequence.</p>
      </div>
    );
  }

  if (activeIndex === 2) {
    return (
      <div className="rounded-lg border border-studio-border bg-studio-panel2 px-5 py-5">
        <p className="text-[11px] uppercase tracking-wide text-studio-muted">Preview script</p>
        <div className="mt-3 space-y-2">
          {SCRIPT_LINES.slice(0, Math.max(1, scriptCount)).map((line, index) => (
            <p
              key={line}
              className="text-sm leading-6 text-studio-primary studio-reveal-up"
              style={{ animationDelay: `${index * 120}ms` }}
            >
              “{line}”
            </p>
          ))}
        </div>
      </div>
    );
  }

  if (activeIndex === 3) {
    return (
      <div className="rounded-lg bg-studio-thinking px-5 py-5">
        <div className="flex items-end justify-between gap-4">
          <div>
            <p className="text-sm text-studio-muted">Narration</p>
            <p className="mt-1 font-display text-2xl font-semibold text-studio-primary">
              {scenesReady} / 12 scenes ready
            </p>
          </div>
          <div className="flex h-12 items-end gap-1.5">
            {Array.from({ length: 18 }).map((_, index) => (
              <span
                key={index}
                className="studio-wave-bar w-1.5 rounded-full bg-studio-accent2/70"
                style={{
                  height: `${18 + ((index * 7) % 26)}px`,
                  animationDelay: `${index * 55}ms`,
                }}
              />
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (activeIndex === 4) {
    return (
      <div className="rounded-lg border border-studio-border bg-studio-panel2 px-5 py-5">
        <div className="grid grid-cols-5 gap-2">
          {WALKTHROUGH_FLOW.map((room, index) => {
            const ready = index < cutCount;
            return (
              <div key={room} className="space-y-2">
                <div
                  className={`h-14 rounded-lg border ${
                    ready
                      ? "border-studio-accent/50 bg-studio-accent/15"
                      : "border-studio-border bg-studio-panel"
                  }`}
                />
                <div
                  className={`h-2 rounded-full ${
                    ready ? "bg-studio-accent2 studio-draw-line" : "bg-[#E8E1D5]"
                  }`}
                  style={{ animationDelay: `${index * 90}ms` }}
                />
                <p className="truncate text-center text-[11px] text-studio-muted">{room}</p>
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-lg bg-studio-thinking px-5 py-5">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
        {["Captions", "Voice mix", "Transitions", "Final render"].map((item, index) => (
          <div key={item} className="studio-reveal-up" style={{ animationDelay: `${index * 90}ms` }}>
            <div className="h-1 rounded-full bg-studio-accent2 studio-draw-line" />
            <p className="mt-2 text-studio-primary">{item}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function ProjectGenerationInner() {
  const params = useParams();
  const searchParams = useSearchParams();
  const projectId = String(params.id || "");
  const titleFromQuery = searchParams.get("title") || "";
  const [status, setStatus] = useState<ProjectStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState(false);

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;

    const tick = async () => {
      try {
        const data = await getProjectStatus(projectId);
        if (cancelled) return;
        setStatus(data);
        setError(data.error || null);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Failed to load status");
        }
      }
    };

    tick();
    const timer = setInterval(tick, 2000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [projectId]);

  const progress = status?.progress ?? 0;
  const displayTitle =
    (status?.title || "").trim() ||
    titleFromQuery.trim() ||
    "Your project";
  const done = status?.status === "completed";
  const loadFailed = !status && Boolean(error);
  const failed = status?.status === "error" || loadFailed;
  const retryable = status?.status === "error";
  const running = !done && !failed && (!status || status.status === "processing" || status.status === "waiting");
  const activeSessionIndex = getSessionStageIndex(progress, done);
  const activeSessionStage = DIRECTOR_STAGES[Math.min(activeSessionIndex, DIRECTOR_STAGES.length - 1)];

  const retryGeneration = async () => {
    if (!projectId || retrying) return;
    setRetrying(true);
    setError(null);
    try {
      const job = await createProjectJob(projectId);
      setStatus((prev) => ({
        project_id: projectId,
        title: prev?.title || titleFromQuery || "Your project",
        brief: prev?.brief,
        status: job.status === "running" ? "processing" : "waiting",
        stage: job.stage || "Queued",
        progress: job.progress ?? 0,
        video_url: prev?.video_url || null,
        job_id: job.job_id || null,
        workspace_slug: prev?.workspace_slug || null,
        final_video: prev?.final_video || null,
        error: "",
      }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to retry generation");
    } finally {
      setRetrying(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col studio-shell-bg relative overflow-hidden">

      <div className="relative flex-1 flex flex-col items-center justify-center px-4 md:px-8 py-10">
        <div className="w-full max-w-5xl flex flex-col items-stretch gap-5">
          <div className="mb-1 flex justify-center gen-fade-in">
            <BrandMark size="landing" />
          </div>

          <div className="rounded-lg border border-studio-border bg-studio-panel studio-panel-topline studio-breath p-6 md:p-8 space-y-7 gen-card-in">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="min-w-0">
                <p className="text-[11px] uppercase tracking-wide text-studio-muted">
                  Director Session
                </p>
                <h1 className="mt-2 font-display text-3xl md:text-4xl font-semibold text-studio-primary tracking-tight">
                  {done ? "Your walkthrough is ready." : "Your AI Director is working."}
                </h1>
                <p className="mt-2 text-sm text-studio-muted">
                  {failed
                    ? retryable
                      ? "Something went wrong — retry this project without uploading again."
                      : "We couldn't load this project status. Please verify your invite session and try again."
                    : done
                      ? "The first cut is complete. Enter Studio when you're ready."
                      : "You don't need to stay on this page. A typical video takes about 20 minutes."}
                </p>
                <p className="mt-1 text-[12px] text-studio-muted truncate">{displayTitle}</p>
              </div>
              <Link
                href="/"
                className="shrink-0 inline-flex items-center px-3 py-2 rounded-lg border border-studio-border bg-studio-panel2 text-sm text-studio-primary hover:border-studio-accent motion-fast"
              >
                ← Studio
              </Link>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-[15rem_minmax(0,1fr)] gap-6">
              <div className="space-y-3">
                {DIRECTOR_STAGES.map((stage, index) => {
                  const isDone = done || index < activeSessionIndex;
                  const isActive = !done && index === activeSessionIndex;
                  const Icon = stage.Icon;
                  return (
                    <div key={stage.name} className="relative pl-7">
                      {index < DIRECTOR_STAGES.length - 1 ? (
                        <span
                          className={`absolute left-[8px] top-6 h-[calc(100%+0.75rem)] w-px ${
                            isDone ? "bg-studio-accent2/50" : "bg-studio-border"
                          }`}
                        />
                      ) : null}
                      <div className="flex items-start gap-2.5">
                        <span
                          className={`absolute left-0 top-0 flex h-4 w-4 items-center justify-center rounded-full border ${
                            isDone
                              ? "border-studio-accent2 bg-studio-accent2"
                              : isActive
                                ? "border-studio-accent bg-studio-accent/20"
                                : "border-studio-border bg-studio-panel"
                          }`}
                        >
                          {isDone ? <CheckCircle2 size={11} className="text-white" /> : null}
                        </span>
                        <Icon
                          size={15}
                          className={
                            isActive || isDone ? "text-studio-accent" : "text-studio-muted/55"
                          }
                        />
                        <div className="min-w-0">
                          <p
                            className={`text-sm font-medium ${
                              isActive || isDone ? "text-studio-primary" : "text-studio-muted"
                            }`}
                          >
                            {stage.title}
                          </p>
                          {isActive ? (
                            <p className="mt-0.5 text-[11px] leading-4 text-studio-muted">
                              {stage.caption}
                            </p>
                          ) : null}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>

              <div className="min-w-0">
                <div className="mb-4 flex items-baseline justify-between gap-3">
                  <div>
                    <p className="text-sm font-medium text-studio-primary">
                      {done ? "Complete" : activeSessionStage.title}
                    </p>
                    <p className="mt-0.5 text-[12px] text-studio-muted">
                      {status?.stage || activeSessionStage.caption}
                    </p>
                  </div>
                  <p className="tabular-nums font-display text-2xl font-semibold text-studio-accent2 shrink-0">
                    {Math.min(100, Math.max(0, progress))}%
                  </p>
                </div>
                <div className="mb-5 h-2 w-full overflow-hidden rounded-full bg-[#EFE8DC]">
                  <div
                    className="h-full rounded-full bg-gradient-to-r from-[#C8A96E] to-[#3A9D9A] gen-progress-sheen transition-[width] duration-700 ease-out"
                    style={{
                      width: `${Math.max(4, Math.min(100, progress || (running ? 3 : 0)))}%`,
                    }}
                  />
                </div>
                <DirectorSessionVisual
                  progress={progress}
                  activeIndex={activeSessionIndex}
                  videoUrl={status?.video_url || null}
                />
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-[minmax(0,1fr)_auto] gap-3 border-t border-studio-border pt-5">
              {running ? (
                <div className="rounded-lg bg-studio-thinking px-4 py-3 text-[12.5px] leading-5 text-studio-muted">
                  <div className="flex items-start gap-2">
                    <Clock3 size={15} className="mt-0.5 shrink-0 text-studio-accent2" />
                    <p>
                      Average processing time is about 20 minutes. You can leave this page open or return from History later.
                    </p>
                  </div>
                </div>
              ) : null}

              {done && !failed ? (
                <Link
                  href={`/project/${projectId}/studio`}
                  className="inline-flex items-center justify-center rounded-lg bg-studio-accent hover:bg-studio-accentHover px-5 py-3 text-sm font-medium text-studio-primary motion-fast"
                >
                  Enter Studio →
                </Link>
              ) : null}

              {failed ? (
                <div className="flex flex-wrap items-center justify-end gap-2">
                  {retryable ? (
                    <button
                      type="button"
                      onClick={retryGeneration}
                      disabled={retrying}
                      className="inline-flex items-center justify-center gap-2 rounded-lg bg-studio-accent hover:bg-studio-accentHover disabled:cursor-not-allowed disabled:opacity-65 px-5 py-3 text-sm font-medium text-studio-primary motion-fast"
                    >
                      {retrying ? <Loader2 size={16} className="animate-spin" /> : null}
                      {retrying ? "Retrying..." : "Retry generation"}
                    </button>
                  ) : null}
                  <Link
                    href="/"
                    className="inline-flex items-center justify-center rounded-lg border border-studio-border bg-studio-panel2 hover:border-studio-accent px-5 py-3 text-sm font-medium text-studio-primary motion-fast"
                  >
                    New Project
                  </Link>
                </div>
              ) : null}
            </div>

            {failed && error ? (
              <p className="text-sm text-studio-danger" role="alert">
                {error}
              </p>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function ProjectGenerationPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen flex items-center justify-center bg-studio-bg text-sm text-studio-muted">
          Loading…
        </div>
      }
    >
      <ProjectGenerationInner />
    </Suspense>
  );
}
