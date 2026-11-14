"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { AlertCircle, CheckCircle2, PanelsTopLeft, SlidersHorizontal, X } from "lucide-react";
import Header from "@/components/Header";
import StatusBar from "@/components/StatusBar";
import VideoViewer, { type PreviewMode } from "@/components/VideoViewer";
import Timeline from "@/components/timeline/Timeline";
import SegmentInspector from "@/components/timeline/SegmentInspector";
import ScriptEditorModal from "@/components/ScriptEditorModal";
import NewProjectPage, {
  type NarrationLanguage,
  type UploadPhase,
} from "@/components/NewProjectPage";
import ExportBar from "@/components/ExportBar";
import InlineJobChip from "@/components/InlineJobChip";
import {
  layoutTimeline,
  layoutTimeToVideoTime,
  videoTimeToLayoutTime,
} from "@/lib/timelineLayout";
import {
  cancelJob,
  exportFinalVideo,
  getProject,
  listProjects,
  pollJob,
  reviseAudioOffset,
  reviseScript,
  type Job,
  type ProjectDetail,
  type ProjectSummary,
} from "@/lib/studioApi";
import { startSaasGenerate, cancelSaasProject } from "@/lib/saasApi";
import { UploadCancelledError } from "@/lib/uploadR2";
import { setSessionCookie } from "@/lib/session";
import { useSessionHeartbeat } from "@/lib/useSessionHeartbeat";
type View = "landing" | "studio";

type DirectorStudioProps = {
  /** Open directly into Studio for this workspace slug (SaaS → Studio handoff). */
  initialSlug?: string | null;
  /** Hide the local New Project landing when arriving from SaaS flow. */
  saasMode?: boolean;
};

export default function DirectorStudio({
  initialSlug = null,
  saasMode = false,
}: DirectorStudioProps) {
  const router = useRouter();
  const [viewAsReadOnly, setViewAsReadOnly] = useState(false);

  // Admin View-as: ?view_as=<token> installs a read-only beta session
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const token = params.get("view_as");
    if (!token) return;
    setSessionCookie(token);
    setViewAsReadOnly(true);
    params.delete("view_as");
    const next = `${window.location.pathname}${params.toString() ? `?${params}` : ""}`;
    window.history.replaceState({}, "", next);
  }, []);

  useSessionHeartbeat({
    currentPage: viewAsReadOnly ? "view-as" : "studio",
    currentProject: null,
    currentStage: null,
  });

  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [view, setView] = useState<View>(initialSlug ? "studio" : "landing");
  const [selectedSlug, setSelectedSlug] = useState<string | null>(initialSlug);
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [selectedSegmentId, setSelectedSegmentId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [videoRefreshKey, setVideoRefreshKey] = useState(0);

  const [exportJob, setExportJob] = useState<Job | null>(null);
  const [showExportChip, setShowExportChip] = useState(false);
  const [busy, setBusy] = useState(false);

  const [editingSegmentId, setEditingSegmentId] = useState<string | null>(null);
  const [savingScript, setSavingScript] = useState(false);

  const [creatingJob, setCreatingJob] = useState<Job | null>(null);
  const [creatingSubmitting, setCreatingSubmitting] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadPhase, setUploadPhase] = useState<UploadPhase>("idle");
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [pendingOpenSlug, setPendingOpenSlug] = useState<string | null>(null);
  const [saasProjectId, setSaasProjectId] = useState<string | null>(null);
  const [creatingTitle, setCreatingTitle] = useState<string>("");
  const createPollGenRef = useRef(0);
  const uploadAbortRef = useRef<AbortController | null>(null);
  const saasProjectIdRef = useRef<string | null>(null);

  const videoRef = useRef<HTMLVideoElement>(null);
  const pendingSeekRef = useRef<number | null>(null);
  const lastVideoSeekAtRef = useRef(0);
  const offsetJobGenRef = useRef(0);
  const exportJobGenRef = useRef(0);
  const exportJobIdRef = useRef<string | null>(null);
  const projectSlugRef = useRef<string | null>(null);
  const [previewMode, setPreviewMode] = useState<PreviewMode>("final");
  const [playheadTime, setPlayheadTime] = useState(0);
  const [hasPendingEdits, setHasPendingEdits] = useState(false);
  const [editNotice, setEditNotice] = useState<string | null>(null);
  const [exportReadyNotice, setExportReadyNotice] = useState(false);

  const refreshProjects = useCallback(async () => {
    try {
      const list = await listProjects();
      setProjects(list);
      return list;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load projects");
      return [];
    }
  }, []);

  const loadProject = useCallback(async (slug: string) => {
    try {
      const detail = await getProject(slug);
      setProject(detail);
      setSelectedSegmentId((prev) =>
        prev && detail.timeline.some((s) => s.id === prev) ? prev : detail.timeline[0]?.id ?? null
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load project");
    }
  }, []);

  useEffect(() => {
    refreshProjects().then((list) => {
      if (saasMode && initialSlug) {
        setView("studio");
        setSelectedSlug(initialSlug);
        return;
      }
      // Landing-first: only auto-open if returning with a selection later.
      if (list.length === 0) setView("landing");
    });
  }, [refreshProjects, saasMode, initialSlug]);

  useEffect(() => {
    if (view === "studio" && selectedSlug) loadProject(selectedSlug);
  }, [selectedSlug, loadProject, view]);

  useEffect(() => {
    if (!editNotice) return;
    const t = window.setTimeout(() => setEditNotice(null), 4500);
    return () => window.clearTimeout(t);
  }, [editNotice]);

  useEffect(() => {
    if (!project) return;
    setPreviewMode(project.video.final_url ? "final" : project.video.draft_url ? "draft" : "source");
    setPlayheadTime(0);
    setHasPendingEdits(false);
  }, [project?.slug]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    const sync = () => {
      if (!video.paused) return;
      const layout = project ? layoutTimeline(project.timeline) : null;
      setPlayheadTime(
        layout ? videoTimeToLayoutTime(video.currentTime, layout) : video.currentTime
      );
    };
    video.addEventListener("seeked", sync);
    video.addEventListener("pause", sync);
    video.addEventListener("ended", sync);
    return () => {
      video.removeEventListener("seeked", sync);
      video.removeEventListener("pause", sync);
      video.removeEventListener("ended", sync);
    };
  }, [previewMode, videoRefreshKey, project]);

  const handleLoadedMetadata = () => {
    const video = videoRef.current;
    if (video && pendingSeekRef.current != null) {
      video.currentTime = pendingSeekRef.current;
      pendingSeekRef.current = null;
    }
  };

  const handleScrub = useCallback(
    (layoutTime: number, opts?: { immediate?: boolean }) => {
      setPlayheadTime(layoutTime);
      const video = videoRef.current;
      if (!video) return;

      const seekTime = project
        ? layoutTimeToVideoTime(layoutTime, layoutTimeline(project.timeline))
        : layoutTime;

      if (previewMode === "source") {
        pendingSeekRef.current = seekTime;
        setPreviewMode(project?.video.draft_url ? "draft" : "final");
        return;
      }

      const now = performance.now();
      if (opts?.immediate || now - lastVideoSeekAtRef.current > 80) {
        video.currentTime = seekTime;
        lastVideoSeekAtRef.current = now;
      }
    },
    [previewMode, project]
  );

  const selectedSegment =
    project?.timeline.find((s) => s.id === selectedSegmentId) ?? null;
  const editingSegment =
    project?.timeline.find((s) => s.id === editingSegmentId) ?? null;

  projectSlugRef.current = project?.slug ?? null;

  const handleSaveScript = async (text: string) => {
    if (!project || !editingSegmentId) return;
    setSavingScript(true);
    setBusy(true);
    try {
      const { job_id } = await reviseScript(project.slug, editingSegmentId, text);
      setEditingSegmentId(null);
      const job = await pollJob(job_id, () => {});
      if (job.status === "error") {
        throw new Error(job.error || "Failed to save narration");
      }
      await loadProject(project.slug);
      setHasPendingEdits(true);
      setEditNotice("Narration saved.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save narration");
    } finally {
      setSavingScript(false);
      setBusy(false);
    }
  };

  const handleApplyOffset = useCallback(
    async (segmentId: string, offset: number) => {
      const slug = projectSlugRef.current;
      if (!slug) return;

      setProject((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          timeline: prev.timeline.map((s) =>
            s.id === segmentId ? { ...s, audio_offset: offset } : s
          ),
        };
      });
      setHasPendingEdits(true);

      const gen = ++offsetJobGenRef.current;
      try {
        const { job_id } = await reviseAudioOffset(slug, segmentId, offset);
        const job = await pollJob(job_id, () => {}, 500);
        if (gen !== offsetJobGenRef.current) return;
        if (job.status === "error") {
          throw new Error(job.error || "Failed to adjust audio");
        }
        await loadProject(slug);
        setEditNotice("Audio timing saved.");
      } catch (e) {
        if (gen !== offsetJobGenRef.current) return;
        setError(e instanceof Error ? e.message : "Failed to adjust audio");
      }
    },
    [loadProject]
  );

  const handleExport = useCallback(async () => {
    const slug = projectSlugRef.current;
    if (!slug) return;

    const gen = ++exportJobGenRef.current;
    const prevId = exportJobIdRef.current;
    if (prevId && prevId !== "starting") {
      try {
        await cancelJob(prevId);
      } catch {
        /* supersede */
      }
    }

    setBusy(true);
    setShowExportChip(true);
    setHasPendingEdits(true);
    setExportReadyNotice(false);
    setExportJob({
      id: "starting",
      slug,
      kind: "export",
      segment_id: "",
      status: "pending",
      stages: [
        { name: "prepare", label: "Loading edited project", status: "pending", detail: "" },
        { name: "render", label: "Rendering final video", status: "pending", detail: "" },
        { name: "finalize", label: "Saving output", status: "pending", detail: "" },
      ],
      error: "",
      result: {},
      created_at: Date.now() / 1000,
      updated_at: Date.now() / 1000,
    });
    exportJobIdRef.current = "starting";

    try {
      const { job_id } = await exportFinalVideo(slug);
      if (gen !== exportJobGenRef.current) {
        try {
          await cancelJob(job_id);
        } catch {
          /* superseded */
        }
        return;
      }
      exportJobIdRef.current = job_id;
      const job = await pollJob(job_id, (j) => {
        if (gen === exportJobGenRef.current) setExportJob(j);
      });
      if (gen !== exportJobGenRef.current) return;
      if (job.status === "cancelled") {
        return;
      }
      if (job.status === "error") {
        throw new Error(job.error || "Export failed");
      }
      await loadProject(slug);
      await refreshProjects();
      setVideoRefreshKey((k) => k + 1);
      setHasPendingEdits(false);
      setPreviewMode("final");
      setExportReadyNotice(true);
    } catch (e) {
      if (gen !== exportJobGenRef.current) return;
      setError(e instanceof Error ? e.message : "Export failed");
      setExportJob((prev) =>
        prev
          ? {
              ...prev,
              status: "error",
              error: e instanceof Error ? e.message : "Export failed",
              stages: prev.stages.map((s) =>
                s.status === "running" || s.status === "pending"
                  ? { ...s, status: "error" as const }
                  : s
              ),
            }
          : prev
      );
    } finally {
      if (gen === exportJobGenRef.current) {
        setBusy(false);
        exportJobIdRef.current = null;
      }
    }
  }, [loadProject, refreshProjects]);


  const handleCancelExport = async () => {
    exportJobGenRef.current += 1;
    const id = exportJob?.id || exportJobIdRef.current;
    exportJobIdRef.current = null;
    if (!id || id === "starting") {
      setExportJob((prev) =>
        prev ? { ...prev, status: "cancelled", error: "Cancelled by user" } : prev
      );
      setBusy(false);
      return;
    }
    try {
      const job = await cancelJob(id);
      setExportJob(job);
    } catch {
      setExportJob((prev) =>
        prev ? { ...prev, status: "cancelled", error: "Cancelled by user" } : prev
      );
    } finally {
      setBusy(false);
    }
  };

  const handleCreateProject = async (
    file: File,
    brief: string,
    language: NarrationLanguage
  ) => {
    setCreatingSubmitting(true);
    setError(null);
    setUploadError(null);
    setUploadProgress(0);
    setUploadPhase("preparing");
    setPendingOpenSlug(null);
    setSaasProjectId(null);
    setCreatingJob(null);
    const title = file.name || "Untitled";
    setCreatingTitle(title);
    const pollGen = ++createPollGenRef.current;
    uploadAbortRef.current?.abort();
    const abort = new AbortController();
    uploadAbortRef.current = abort;
    try {
      // Queue for Mac Worker (R2 + Supabase), but keep v3.1 in-place progress on landing.
      const { projectId } = await startSaasGenerate({
        file,
        brief,
        language,
        title,
        signal: abort.signal,
        onUploadProgress: (percent) => {
          if (pollGen !== createPollGenRef.current) return;
          setUploadProgress(percent);
        },
        onPhase: (phase) => {
          if (pollGen !== createPollGenRef.current) return;
          setUploadPhase(phase);
        },
        onProjectCreated: (id) => {
          saasProjectIdRef.current = id;
          setSaasProjectId(id);
        },
      });
      if (pollGen !== createPollGenRef.current) return;
      uploadAbortRef.current = null;
      setSaasProjectId(projectId);
      setCreatingSubmitting(false);
      setUploadPhase("idle");
      router.push(`/project/${projectId}?title=${encodeURIComponent(title)}`);
    } catch (e) {
      if (pollGen !== createPollGenRef.current) return;
      if (e instanceof UploadCancelledError) {
        setCreatingSubmitting(false);
        setUploadPhase("idle");
        setUploadProgress(0);
        setUploadError(null);
        setError(null);
        setCreatingTitle("");
        return;
      }
      const message = e instanceof Error ? e.message : "Failed to create project";
      setUploadError(message);
      setError(message);
      setCreatingSubmitting(false);
      setUploadPhase("idle");
    } finally {
      if (uploadAbortRef.current === abort) {
        uploadAbortRef.current = null;
      }
    }
  };

  const handleCancelCreate = async () => {
    // Abort in-flight R2 upload, tell the API to cancel, and stop polling.
    // Worker sees cancelled on the next progress / LLM call and frees the queue.
    uploadAbortRef.current?.abort();
    uploadAbortRef.current = null;
    createPollGenRef.current += 1;
    const projectId = saasProjectIdRef.current || saasProjectId;
    if (projectId) {
      try {
        await cancelSaasProject(projectId);
      } catch (err) {
        console.warn("cancel project failed", err);
      }
    }
    setCreatingSubmitting(false);
    setUploadPhase("idle");
    setUploadProgress(0);
    setUploadError(null);
    setError(null);
    setCreatingJob((prev) =>
      prev
        ? {
            ...prev,
            status: "cancelled",
            error: "Cancelled by user",
            stages: prev.stages.map((s) =>
              s.status === "running" || s.status === "pending"
                ? { ...s, status: "cancelled" as const }
                : s
            ),
          }
        : prev
    );
  };

  const tryOpenStudio = async (slug: string | null | undefined, projectId?: string | null) => {
    // SaaS projects must open by project_id — never fall back to an unrelated
    // local Studio workspace (that caused Open Project → wrong video).
    if (projectId) {
      router.push(`/project/${projectId}/studio`);
      return;
    }
    if (slug) {
      try {
        await getProject(slug);
        openStudio(slug);
        return;
      } catch {
        setError("Could not open this project workspace.");
      }
    }
  };

  const openStudio = (slug: string) => {
    setSelectedSlug(slug);
    setView("studio");
    setCreatingJob(null);
    setPendingOpenSlug(null);
  };

  const goLanding = () => {
    createPollGenRef.current += 1;
    uploadAbortRef.current?.abort();
    uploadAbortRef.current = null;
    setView("landing");
    setCreatingJob(null);
    setPendingOpenSlug(null);
    setSaasProjectId(null);
    setCreatingTitle("");
    setCreatingSubmitting(false);
    setUploadProgress(0);
    setUploadPhase("idle");
    setUploadError(null);
  };

  const exportChipVisible =
    showExportChip &&
    exportJob &&
    (exportJob.status === "running" ||
      exportJob.status === "pending" ||
      exportJob.status === "error" ||
      exportJob.status === "cancelled" ||
      exportJob.status === "done");

  return (
    <div className="h-screen flex flex-col studio-shell-bg">
      {viewAsReadOnly && (
        <div className="px-4 py-2 bg-amber-100 border-b border-amber-300 text-amber-950 text-sm text-center">
          Admin View-as (read-only) — you see this account’s History and projects; writes are blocked.
        </div>
      )}
      {view === "studio" && (
        <Header
          projects={projects}
          selectedSlug={selectedSlug}
          onSelect={(slug) => {
            setSelectedSlug(slug);
            setView("studio");
          }}
          onNewProject={goLanding}
        />
      )}

      {error && (
        <div className="flex items-center gap-2 px-6 py-2 bg-studio-danger/10 border-b border-studio-danger/30 text-studio-danger text-sm">
          <AlertCircle size={14} />
          {error}
          <button className="ml-auto text-xs underline" onClick={() => setError(null)}>
            dismiss
          </button>
        </div>
      )}

      {editNotice && (
        <div className="flex items-center gap-2 px-6 py-2 bg-studio-accent2/10 border-b border-studio-accent2/30 text-studio-primary text-sm">
          <CheckCircle2 size={14} className="text-studio-accent2 shrink-0" />
          <span>{editNotice}</span>
          <button
            type="button"
            className="ml-auto text-studio-muted hover:text-studio-primary"
            onClick={() => setEditNotice(null)}
            aria-label="Dismiss"
          >
            <X size={14} />
          </button>
        </div>
      )}

      {exportReadyNotice && (
        <div className="fixed right-5 top-5 z-50 w-[min(92vw,22rem)] rounded-lg border border-studio-accent2/35 bg-studio-panel px-4 py-3 text-sm text-studio-primary studio-panel-topline studio-toast-in">
          <div className="flex items-start gap-2.5">
            <CheckCircle2 size={17} className="mt-0.5 shrink-0 text-studio-accent2" />
            <div className="min-w-0">
              <p className="font-medium">Final video is ready.</p>
              <p className="mt-0.5 text-[12px] leading-5 text-studio-muted">
                You can preview it here or download it from Output.
              </p>
            </div>
            <button
              type="button"
              className="ml-auto text-studio-muted hover:text-studio-primary motion-fast"
              onClick={() => setExportReadyNotice(false)}
              aria-label="Dismiss final video notification"
            >
              <X size={14} />
            </button>
          </div>
        </div>
      )}

      {view === "landing" ? (
        <NewProjectPage
          onCreate={handleCreateProject}
          onCancelJob={handleCancelCreate}
          submitting={creatingSubmitting}
          uploadProgress={uploadProgress}
          uploadPhase={uploadPhase}
          uploadError={uploadError}
          job={creatingJob}
          jobTitle={creatingTitle}
          projectsCount={projects.length}
          onBrowseProjects={() => {
            if (saasProjectId) {
              router.push(`/project/${saasProjectId}/studio`);
              return;
            }
            if (projects[0]) openStudio(projects[0].slug);
          }}
          onOpenProject={() => {
            void tryOpenStudio(
              pendingOpenSlug || creatingJob?.slug || null,
              saasProjectId
            );
          }}
          onOpenHistoryProject={(projectId, workspaceSlug, status) => {
            if (status === "completed") {
              void tryOpenStudio(workspaceSlug, projectId);
              return;
            }
            // In-progress / error → dedicated progress page (not a random local slug)
            router.push(`/project/${projectId}`);
          }}
          onReset={() => {
            createPollGenRef.current += 1;
            uploadAbortRef.current?.abort();
            uploadAbortRef.current = null;
            setCreatingJob(null);
            setPendingOpenSlug(null);
            setSaasProjectId(null);
            setCreatingTitle("");
            setCreatingSubmitting(false);
            setUploadProgress(0);
            setUploadPhase("idle");
            setUploadError(null);
          }}
        />
      ) : !project ? (
        <div className="flex-1 flex items-center justify-center text-sm text-studio-muted">
          Loading project…
        </div>
      ) : (
        <>
          <StatusBar stages={project.stages} thinking={project.thinking} />

          <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <p className="text-[11px] uppercase tracking-wide text-studio-muted">
                  Review workspace
                </p>
                <h1 className="font-display text-2xl font-semibold tracking-tight text-studio-primary">
                  {project.video_name || "Current project"}
                </h1>
              </div>
              <div className="flex items-center gap-2 rounded-lg border border-studio-border bg-studio-panel/85 px-3 py-2 text-[12px] text-studio-muted studio-panel-topline">
                <PanelsTopLeft size={14} className="text-studio-accent" />
                <span>Preview</span>
                <span className="h-1 w-1 rounded-full bg-studio-border" />
                <SlidersHorizontal size={14} className="text-studio-accent2" />
                <span>Inspect</span>
                <span className="h-1 w-1 rounded-full bg-studio-border" />
                <span className="font-medium text-studio-primary">Export</span>
              </div>
            </div>
            <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_300px] gap-5 items-start">
              <VideoViewer
                sourceUrl={project.video.source_url}
                draftUrl={project.video.draft_url}
                finalUrl={project.video.final_url}
                refreshKey={videoRefreshKey}
                mode={previewMode}
                onModeChange={setPreviewMode}
                videoRef={videoRef}
                onLoadedMetadata={handleLoadedMetadata}
                trailing={
                  exportChipVisible && exportJob ? (
                    <InlineJobChip
                      job={exportJob}
                      onCancel={handleCancelExport}
                      onDismiss={() => {
                        setShowExportChip(false);
                        if (exportJob.status === "done" || exportJob.status === "cancelled") {
                          setExportJob(null);
                        }
                      }}
                    />
                  ) : null
                }
              />
              <SegmentInspector
                segment={selectedSegment}
                onEditNarration={setEditingSegmentId}
                onApplyOffset={handleApplyOffset}
                busy={busy}
              />
            </div>

            <Timeline
              segments={project.timeline}
              selectedId={selectedSegmentId}
              onSelect={setSelectedSegmentId}
              onEditNarration={setEditingSegmentId}
              onApplyOffset={handleApplyOffset}
              playheadTime={playheadTime}
              onScrub={handleScrub}
              videoRef={videoRef}
              mediaKey={`${previewMode}-${videoRefreshKey}`}
              disabled={false}
            />
          </div>

          <ExportBar
            onExport={handleExport}
            onCancel={handleCancelExport}
            job={exportJob}
            finalUrl={project.video.final_url}
            disabled={false}
            hasPendingEdits={hasPendingEdits}
          />
        </>
      )}

      {editingSegment && (
        <ScriptEditorModal
          segment={editingSegment}
          onClose={() => setEditingSegmentId(null)}
          onSave={handleSaveScript}
          saving={savingScript}
        />
      )}
    </div>
  );
}
