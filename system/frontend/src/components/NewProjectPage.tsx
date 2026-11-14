"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { CheckCircle2, Clock3, Film, History, Languages, Loader2, Sparkles, UploadCloud, X } from "lucide-react";
import type { Job } from "@/lib/studioApi";
import { listSaasProjects, type SaasProjectSummary } from "@/lib/saasApi";
import JobProgress from "@/components/JobProgress";
import BrandMark from "@/components/BrandMark";

export type NarrationLanguage = "en" | "zh";
export type UploadPhase = "idle" | "preparing" | "uploading" | "creating_job";

interface Props {
  onCreate: (file: File, brief: string, language: NarrationLanguage) => void;
  onCancelJob?: () => void;
  submitting: boolean;
  uploadProgress?: number;
  uploadPhase?: UploadPhase;
  uploadError?: string | null;
  job: Job | null;
  jobTitle?: string;
  onOpenProject?: () => void;
  onReset?: () => void;
  projectsCount?: number;
  onBrowseProjects?: () => void;
  onOpenHistoryProject?: (
    projectId: string,
    workspaceSlug?: string | null,
    status?: string
  ) => void;
}

export default function NewProjectPage({
  onCreate,
  onCancelJob,
  submitting,
  uploadProgress = 0,
  uploadPhase = "idle",
  uploadError = null,
  job,
  jobTitle,
  onOpenProject,
  onReset,
  projectsCount = 0,
  onBrowseProjects,
  onOpenHistoryProject,
}: Props) {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [brief, setBrief] = useState("");
  const [language, setLanguage] = useState<NarrationLanguage>("zh");
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyItems, setHistoryItems] = useState<SaasProjectSummary[]>([]);
  const [historyError, setHistoryError] = useState<string | null>(null);

  const running = job && (job.status === "running" || job.status === "pending");
  const finished =
    job && (job.status === "done" || job.status === "error" || job.status === "cancelled");
  const showUploadPanel = submitting && !job;

  const briefPlaceholder =
    language === "zh"
      ? "例如：突出空间尺度、自然采光、窗外视野与家具质感；旁白可简约、详细，或偏小红书 / 抖音 / TikTok 风格。"
      : "e.g. Highlight space, natural light, views, and furniture character — keep narration concise or detailed, TikTok / Xiaohongshu / Douyin style.";

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    setHistoryError(null);
    try {
      const items = await listSaasProjects();
      // Hide abandoned creates (no upload / no job) so History isn't noise.
      const visible = items.filter(
        (item) =>
          item.status !== "created" ||
          !!item.workspace_slug ||
          !!item.final_video
      );
      setHistoryItems(visible);
    } catch (e) {
      setHistoryError(e instanceof Error ? e.message : "Failed to load history");
      setHistoryItems([]);
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  useEffect(() => {
    if (historyOpen) void loadHistory();
  }, [historyOpen, loadHistory]);

  const openHistoryItem = (item: SaasProjectSummary) => {
    setHistoryOpen(false);
    if (onOpenHistoryProject) {
      onOpenHistoryProject(item.project_id, item.workspace_slug, item.status);
      return;
    }
    if (item.status === "completed" && item.workspace_slug) {
      router.push(`/project/${item.project_id}/studio`);
    } else {
      router.push(`/project/${item.project_id}`);
    }
  };

  const startLabel =
    uploadPhase === "creating_job"
      ? "Creating job…"
      : uploadPhase === "uploading"
      ? `Uploading ${uploadProgress}%`
      : uploadPhase === "preparing"
      ? "Connecting…"
      : "Starting…";

  return (
    <div className="flex-1 min-h-0 relative flex flex-col">
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background:
            "linear-gradient(180deg, rgba(255,255,255,0.72), rgba(250,248,243,0.94)), linear-gradient(90deg, rgba(22,43,73,0.035) 1px, transparent 1px), linear-gradient(180deg, rgba(22,43,73,0.028) 1px, transparent 1px), #FAF8F3",
          backgroundSize: "auto, 36px 36px, 36px 36px, auto",
        }}
      />

      <div className="relative flex-1 flex flex-col items-center justify-center px-4 md:px-8 py-8 overflow-y-auto">
        <div className="w-full max-w-4xl my-auto flex flex-col items-stretch">
          <div className="mb-5 flex justify-center">
            <BrandMark size="landing" />
          </div>

          <div className="mb-4 grid grid-cols-3 gap-3">
            {[
              ["Upload", "Video + brief"],
              ["Direct", "AI tour cut"],
              ["Review", "Edit + export"],
            ].map(([title, caption], index) => (
              <div
                key={title}
                className="rounded-lg border border-studio-border/80 bg-white/75 px-4 py-3.5 studio-panel-topline studio-hover-lift studio-soft-rise"
                style={{ animationDelay: `${index * 80}ms` }}
              >
                <div className="flex items-center gap-2.5">
                  <span className="flex h-7 w-7 items-center justify-center rounded-full bg-studio-accent/20 font-display text-[13px] font-semibold text-studio-primary">
                    {index + 1}
                  </span>
                  <span className="font-display text-[17px] font-semibold text-studio-primary tracking-tight leading-none">
                    {title}
                  </span>
                </div>
                <p className="mt-2 pl-[38px] text-[13px] leading-5 text-studio-muted">
                  {caption}
                </p>
              </div>
            ))}
          </div>

          {job ? (
            <div className="rounded-lg border border-studio-border bg-studio-panel studio-panel-topline studio-breath p-6 md:p-7 space-y-5 gen-card-in">
              <p className="text-sm font-medium text-studio-primary/85">
                AI-powered real estate video director
              </p>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  {(jobTitle || (job.result?.title as string | undefined)) && (
                    <h2 className="text-xl font-display font-semibold text-studio-primary tracking-tight truncate mb-1">
                      {jobTitle || String(job.result?.title || "")}
                    </h2>
                  )}
                  <p className="text-sm font-medium text-studio-primary">
                    {job.status === "done"
                      ? "Draft ready"
                      : job.status === "cancelled"
                      ? "Generation cancelled"
                      : job.status === "error"
                      ? "Something went wrong"
                      : "Creating your draft"}
                  </p>
                  <p className="text-[12.5px] text-studio-muted mt-1">
                    {running
                      ? "Nesto is directing your tour. A typical video takes about 20 minutes."
                      : job.status === "done"
                      ? "Open the project to review and edit."
                      : job.error || "You can start again with a new video."}
                  </p>
                </div>
                {running && onCancelJob && (
                  <button
                    type="button"
                    onClick={onCancelJob}
                    className="shrink-0 w-8 h-8 rounded-lg border border-studio-border text-studio-muted hover:text-studio-danger hover:border-studio-danger/40 flex items-center justify-center"
                    title="Cancel generation"
                    aria-label="Cancel generation"
                  >
                    <X size={16} />
                  </button>
                )}
              </div>
              <JobProgress job={job} />
              {running ? (
                <div className="rounded-lg bg-studio-thinking px-4 py-3 text-[12.5px] leading-5 text-studio-muted">
                  <div className="flex items-start gap-2">
                    <Clock3 size={15} className="mt-0.5 shrink-0 text-studio-accent2" />
                    <p>
                      Average processing time is about 20 minutes. You can leave this page open and come back to History when the draft is ready.
                    </p>
                  </div>
                </div>
              ) : null}
              {finished && (
                <div className="flex justify-end gap-2 pt-1">
                  {job.status === "done" && onOpenProject && (
                    <button
                      type="button"
                      onClick={onOpenProject}
                      className="px-4 py-2 rounded-lg bg-studio-accent hover:bg-studio-accentHover text-studio-primary text-sm font-medium transition-colors"
                    >
                      Open project
                    </button>
                  )}
                  {(job.status === "error" || job.status === "cancelled") && (
                    <button
                      type="button"
                      onClick={() => onReset?.()}
                      className="px-4 py-2 rounded-lg border border-studio-border text-sm text-studio-primary"
                    >
                      Try again
                    </button>
                  )}
                </div>
              )}
            </div>
          ) : showUploadPanel ? (
            <div className="rounded-lg border border-studio-border bg-studio-panel studio-panel-topline studio-breath p-6 md:p-7 space-y-5 gen-card-in">
              <p className="text-sm font-medium text-studio-primary/85">
                AI-powered real estate video director
              </p>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  {jobTitle ? (
                    <h2 className="text-xl font-display font-semibold text-studio-primary tracking-tight truncate mb-1">
                      {jobTitle}
                    </h2>
                  ) : null}
                  <p className="text-sm font-medium text-studio-primary">
                    {uploadPhase === "creating_job"
                      ? "Creating AI Director job…"
                      : uploadPhase === "preparing"
                        ? "Connecting to upload server…"
                        : "Uploading your video"}
                  </p>
                </div>
                {onCancelJob ? (
                  <button
                    type="button"
                    onClick={onCancelJob}
                    className="shrink-0 w-8 h-8 rounded-lg border border-studio-border text-studio-muted hover:text-studio-danger hover:border-studio-danger/40 flex items-center justify-center"
                    title="Cancel upload"
                    aria-label="Cancel upload"
                  >
                    <X size={16} />
                  </button>
                ) : null}
              </div>
              <div className="space-y-2">
                <div className="flex items-baseline justify-between gap-3">
                  <p className="text-sm text-studio-primary">
                    {uploadPhase === "creating_job"
                      ? "Creating AI Director job…"
                      : uploadPhase === "preparing"
                        ? "Waiting for server…"
                        : `Uploading video: ${uploadProgress}%`}
                  </p>
                  <p className="tabular-nums text-sm font-medium text-studio-accent2 shrink-0">
                    {uploadPhase === "creating_job" || uploadPhase === "preparing"
                      ? "—"
                      : `${uploadProgress}%`}
                  </p>
                </div>
                <div className="h-2 w-full overflow-hidden rounded-full bg-[#EFE8DC]">
                  <div
                    className="h-full rounded-full bg-gradient-to-r from-[#C8A96E] to-[#3A9D9A] gen-progress-sheen transition-[width] duration-300 ease-out"
                    style={{
                      width: `${
                        uploadPhase === "creating_job"
                          ? 100
                          : uploadPhase === "preparing"
                            ? 12
                            : Math.max(4, Math.min(100, uploadProgress))
                      }%`,
                    }}
                  />
                </div>
                <p className="text-[12.5px] text-studio-muted">
                  {uploadPhase === "creating_job"
                    ? "Upload finished — queuing generation. The full draft usually takes about 20 minutes."
                    : uploadPhase === "preparing"
                      ? "Server is waking up or busy — this can take a minute."
                      : "Uploading to cloud storage. Cancel anytime with ✕."}
                </p>
              </div>
              {uploadError ? (
                <div className="rounded-lg border border-studio-danger/30 bg-studio-danger/10 px-3 py-2.5 text-sm text-studio-danger">
                  {uploadError}
                </div>
              ) : null}
            </div>
          ) : (
            <div className="rounded-lg border border-studio-border bg-studio-panel studio-panel-topline p-5 md:p-6 studio-soft-rise">
              <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_17rem] gap-5">
                <div className="space-y-5">
              <div>
                <p className="text-[12px] font-medium uppercase tracking-[0.14em] text-studio-primary/75 mb-2 flex items-center gap-1.5">
                  <Film size={13} className="text-studio-accent" />
                  Walkthrough video
                </p>
                <label className="studio-scan-line flex min-h-[5rem] items-center gap-3.5 px-4 py-4 rounded-lg border border-dashed border-studio-border bg-studio-panel2/80 cursor-pointer hover:border-studio-accent hover:bg-white transition-colors group">
                  <UploadCloud
                    size={22}
                    className="text-studio-accent shrink-0 group-hover:scale-105 transition-transform"
                  />
                  <span className="min-w-0">
                    <span className="block text-[15px] font-medium text-studio-primary truncate">
                      {file ? file.name : "Choose a video file…"}
                    </span>
                    <span className="mt-1 block text-[13px] leading-5 text-studio-muted">
                      MP4 recommended · max 100MB · max 5 minutes
                    </span>
                  </span>
                  <input
                    type="file"
                    accept="video/*"
                    className="hidden"
                    disabled={submitting}
                    onChange={(e) => setFile(e.target.files?.[0] || null)}
                  />
                </label>
              </div>

              {uploadError ? (
                <div className="rounded-lg border border-studio-danger/30 bg-studio-danger/10 px-3 py-2.5 text-sm text-studio-danger">
                  {uploadError}
                </div>
              ) : null}

              <div>
                <p className="text-[12px] font-medium uppercase tracking-[0.14em] text-studio-primary/75 mb-2 flex items-center gap-1.5">
                  <Languages size={13} className="text-studio-accent" />
                  Narration language
                </p>
                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => setLanguage("en")}
                    disabled={submitting}
                    className={`px-4 py-3 rounded-lg border text-left transition-colors ${
                      language === "en"
                        ? "border-studio-accent bg-[#C8A96E]/10 text-studio-primary"
                        : "border-studio-border bg-studio-panel2 text-studio-muted hover:text-studio-primary"
                    }`}
                  >
                    <span className="block text-[15px] font-medium">English</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setLanguage("zh")}
                    disabled={submitting}
                    className={`px-4 py-3 rounded-lg border text-left transition-colors ${
                      language === "zh"
                        ? "border-studio-accent bg-[#C8A96E]/10 text-studio-primary"
                        : "border-studio-border bg-studio-panel2 text-studio-muted hover:text-studio-primary"
                    }`}
                  >
                    <span className="block text-[15px] font-medium">中文</span>
                  </button>
                </div>
              </div>

              <div>
                <p className="text-[12px] font-medium uppercase tracking-[0.14em] text-studio-primary/75 mb-2 flex items-center gap-1.5">
                  <Sparkles size={13} className="text-studio-accent" />
                  Director brief
                </p>
                <textarea
                  value={brief}
                  onChange={(e) => setBrief(e.target.value)}
                  rows={5}
                  disabled={submitting}
                  placeholder={briefPlaceholder}
                  className="w-full rounded-lg border border-studio-border bg-studio-panel2 px-4 py-3 text-[15px] leading-6 text-studio-primary outline-none focus:border-studio-accent focus:bg-white resize-none placeholder:text-studio-muted/70 disabled:opacity-60"
                />
              </div>
                </div>

                <aside className="rounded-lg bg-studio-thinking p-4 flex flex-col justify-between">
                  <div>
                    <p className="text-[12px] font-medium uppercase tracking-[0.14em] text-studio-primary/75 mb-3">
                      Ready check
                    </p>
                    <div className="space-y-2.5 text-sm">
                      <div className="flex items-center gap-2">
                        <CheckCircle2
                          size={15}
                          className={file ? "text-studio-accent2" : "text-[#D9D4C8]"}
                        />
                        <span className={file ? "text-studio-primary" : "text-studio-muted"}>
                          Video selected
                        </span>
                      </div>
                      <div className="flex items-center gap-2">
                        <CheckCircle2 size={15} className="text-studio-accent2" />
                        <span className="text-studio-primary">
                          {language === "zh" ? "中文旁白" : "English narration"}
                        </span>
                      </div>
                      <div className="flex items-center gap-2">
                        <Clock3 size={15} className="text-studio-accent2" />
                        <span className="text-studio-primary">~20 min draft</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <CheckCircle2
                          size={15}
                          className={brief.trim() ? "text-studio-accent2" : "text-[#D9D4C8]"}
                        />
                        <span className={brief.trim() ? "text-studio-primary" : "text-studio-muted"}>
                          Brief optional
                        </span>
                      </div>
                    </div>
                  </div>
                  <p className="mt-5 text-[12px] leading-relaxed text-studio-muted">
                    A short brief is enough. Most drafts take about 20 minutes before the editor opens.
                  </p>
                </aside>
              </div>

              <div className="relative mt-5 flex items-center justify-between gap-3 border-t border-studio-border pt-4">
                <div className="relative">
                  <button
                    type="button"
                    onClick={() => setHistoryOpen((v) => !v)}
                    disabled={submitting}
                    className={`inline-flex items-center gap-2 px-3 py-2.5 rounded-lg border text-sm transition-colors ${
                      historyOpen
                        ? "border-studio-accent bg-[#C8A96E]/10 text-studio-primary"
                        : "border-studio-border bg-studio-panel2 text-studio-muted hover:text-studio-primary"
                    }`}
                  >
                    <History size={15} className="text-studio-accent shrink-0" />
                    <span className="font-medium">History</span>
                  </button>
                  {historyOpen && (
                    <>
                      <button
                        type="button"
                        aria-label="Close history"
                        className="fixed inset-0 z-30 cursor-default bg-transparent"
                        onClick={() => setHistoryOpen(false)}
                      />
                      <div className="absolute bottom-full left-0 mb-2 z-40 w-[min(100vw-3rem,20rem)] max-h-72 overflow-hidden rounded-lg border border-studio-border bg-studio-panel shadow-panel flex flex-col">
                        <div className="flex items-center justify-between px-3 py-2.5 border-b border-studio-border">
                          <p className="text-sm font-medium text-studio-primary">History</p>
                          <button
                            type="button"
                            onClick={() => setHistoryOpen(false)}
                            className="text-studio-muted hover:text-studio-primary"
                            aria-label="Close"
                          >
                            <X size={14} />
                          </button>
                        </div>
                        <div className="overflow-y-auto flex-1">
                          {historyLoading ? (
                            <div className="flex items-center gap-2 px-3 py-5 text-sm text-studio-muted">
                              <Loader2 size={14} className="animate-spin" />
                              Loading…
                            </div>
                          ) : historyError ? (
                            <p className="px-3 py-5 text-sm text-studio-danger">{historyError}</p>
                          ) : historyItems.length === 0 ? (
                            <p className="px-3 py-5 text-sm text-studio-muted">No projects yet.</p>
                          ) : (
                            historyItems.map((item) => (
                              <button
                                key={item.project_id}
                                type="button"
                                onClick={() => openHistoryItem(item)}
                                className="w-full text-left px-3 py-2.5 border-b border-studio-border/60 last:border-0 hover:bg-studio-panel2 transition-colors"
                              >
                                <div className="flex items-center justify-between gap-2">
                                  <span className="text-sm text-studio-primary truncate">
                                    {item.title || item.project_id}
                                  </span>
                                  <span className="text-[11px] text-studio-muted shrink-0 capitalize">
                                    {item.status}
                                  </span>
                                </div>
                                <p className="text-[11px] text-studio-muted truncate mt-0.5">
                                  {item.brief || item.project_id}
                                </p>
                              </button>
                            ))
                          )}
                        </div>
                      </div>
                    </>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => file && onCreate(file, brief, language)}
                  disabled={!file || submitting}
                  className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-studio-accent hover:bg-studio-accentHover text-studio-primary text-sm font-medium disabled:opacity-30 transition-colors"
                >
                  {submitting ? <Loader2 size={16} className="animate-spin" /> : null}
                  {submitting ? startLabel : "Start AI Director"}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
