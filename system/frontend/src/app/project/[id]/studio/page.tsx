"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import DirectorStudio from "@/components/DirectorStudio";
import BrandMark from "@/components/BrandMark";
import { getProjectStatus, type ProjectStatusResponse } from "@/lib/saasApi";
import { getProject } from "@/lib/studioApi";

const MAX_WORKSPACE_OPEN_ATTEMPTS = 40;

export default function ProjectStudioPage() {
  const params = useParams();
  const router = useRouter();
  const projectId = String(params.id || "");
  const [status, setStatus] = useState<ProjectStatusResponse | null>(null);
  const [slugReady, setSlugReady] = useState(false);
  const [workspaceOk, setWorkspaceOk] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [playbackState, setPlaybackState] = useState<
    "loading" | "ready" | "waiting" | "error"
  >("loading");
  const [playbackRetry, setPlaybackRetry] = useState(0);
  const [workspaceAttempts, setWorkspaceAttempts] = useState(0);

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    let settled = false;

    const tick = async () => {
      if (settled) return;
      try {
        const s = await getProjectStatus(projectId);
        if (cancelled) return;
        setStatus(s);
        setError(s.error || null);

        if (s.status === "waiting" || s.status === "processing") {
          router.replace(`/project/${projectId}`);
          return;
        }

        if (s.status !== "completed") {
          setSlugReady(true);
          setWorkspaceOk(false);
          return;
        }

        const slug = s.workspace_slug;
        if (slug) {
          try {
            await getProject(slug);
            if (cancelled) return;
            setSlugReady(true);
            setWorkspaceOk(true);
            settled = true;
            return;
          } catch {
            // Railway may need a moment to hydrate the Mac Worker workspace from R2.
            // Keep retrying briefly so completed History items open the editor instead
            // of falling back to a plain final-video player after one transient miss.
            if (!cancelled && workspaceAttempts < MAX_WORKSPACE_OPEN_ATTEMPTS) {
              setStatus(s);
              setError("Preparing editor workspace...");
              setWorkspaceAttempts((n) => n + 1);
              return;
            }
          }
        }
        setSlugReady(true);
        setWorkspaceOk(false);
        // Freeze the completed response. A fresh presigned URL on every
        // 3-second poll remounts <video> and can make playback load forever.
        settled = true;
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Failed to load project");
          setSlugReady(true);
        }
      }
    };

    tick();
    const timer = setInterval(tick, 3000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [projectId, router, workspaceAttempts]);

  const waitingForWorkspace =
    status?.status === "completed" &&
    Boolean(status.workspace_slug) &&
    !workspaceOk &&
    workspaceAttempts > 0 &&
    workspaceAttempts < MAX_WORKSPACE_OPEN_ATTEMPTS;

  if (!slugReady || !status || waitingForWorkspace) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center bg-studio-bg gap-3">
        <Loader2 className="animate-spin text-studio-process" size={22} />
        <p className="text-sm text-studio-muted">
          {workspaceAttempts > 0 ? "Preparing editor workspace..." : "Opening editor..."}
        </p>
      </div>
    );
  }

  // Prefer R2 presign for playback even when the editor workspace is available —
  // Railway /media proxy is much slower for ~20MB+ finals.
  const title = (status.title || "").trim() || "Your video";
  const videoUrl = status.download_url || status.video_url || null;

  if (workspaceOk && status.workspace_slug) {
    return <DirectorStudio initialSlug={status.workspace_slug} saasMode />;
  }

  // Playback / review when full Studio workspace isn't available on Railway

  return (
    <div className="min-h-screen flex flex-col bg-studio-bg">
      <header className="border-b border-studio-border bg-studio-panel px-6 py-3 flex items-center justify-between shrink-0">
        <BrandMark size="header" />
        <Link
          href="/"
          className="text-sm text-studio-muted hover:text-studio-primary transition-colors"
        >
          New Project
        </Link>
      </header>

      <div className="flex-1 overflow-y-auto px-6 py-8">
        <div className="mx-auto w-full max-w-4xl space-y-5">
          <div>
            <p className="text-[11px] uppercase tracking-wide text-studio-muted">
              Final cut
            </p>
            <h1 className="mt-1 font-display text-2xl font-semibold text-studio-primary tracking-tight">
              {title}
            </h1>
            {status.brief ? (
              <p className="mt-1 text-sm text-studio-muted line-clamp-2">{status.brief}</p>
            ) : null}
          </div>

          <div className="rounded-2xl border border-studio-border bg-studio-panel shadow-panel overflow-hidden">
            {videoUrl ? (
              <video
                key={`${videoUrl}-${playbackRetry}`}
                src={videoUrl}
                controls
                playsInline
                preload="metadata"
                onLoadStart={() => setPlaybackState("loading")}
                onLoadedMetadata={() => setPlaybackState("ready")}
                onCanPlay={() => setPlaybackState("ready")}
                onWaiting={() => setPlaybackState("waiting")}
                onError={() => setPlaybackState("error")}
                className="w-full aspect-video bg-studio-video"
              />
            ) : (
              <div className="aspect-video flex items-center justify-center text-sm text-studio-muted bg-studio-panel2">
                Video URL not ready yet — refresh in a moment.
              </div>
            )}
            {videoUrl && playbackState !== "ready" ? (
              <div className="px-4 py-3 text-sm text-studio-muted border-t border-studio-border flex items-center justify-between gap-3">
                <span>
                  {playbackState === "error"
                    ? "Video could not be loaded."
                    : playbackState === "waiting"
                      ? "Buffering video…"
                      : "Loading video details…"}
                </span>
                {playbackState === "error" ? (
                  <button
                    type="button"
                    onClick={() => {
                      setPlaybackState("loading");
                      setPlaybackRetry((n) => n + 1);
                    }}
                    className="text-studio-primary underline"
                  >
                    Retry
                  </button>
                ) : null}
              </div>
            ) : null}
          </div>

          <div className="flex flex-wrap gap-3">
            {videoUrl ? (
              <a
                href={videoUrl}
                download
                target="_blank"
                rel="noreferrer"
                className="px-4 py-2.5 rounded-xl bg-studio-accent hover:bg-studio-accentHover text-studio-primary text-sm font-medium transition-colors"
              >
                Download video
              </a>
            ) : null}
            <Link
              href="/"
              className="px-4 py-2.5 rounded-xl border border-studio-border text-sm text-studio-primary hover:border-studio-accent transition-colors"
            >
              Back to Studio
            </Link>
          </div>

          {error ? (
            <p className="text-sm text-studio-danger" role="alert">
              {error}
            </p>
          ) : null}
        </div>
      </div>
    </div>
  );
}
