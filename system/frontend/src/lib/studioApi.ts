import { authHeaders } from "@/lib/session";
import { handleUnauthorizedResponse } from "@/lib/authFailure";

const API_URL = (
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
).replace(/\/$/, "");

export interface ProjectSummary {
  slug: string;
  video_name: string;
  updated_at: string;
  director_brief: string;
  stages: Record<string, boolean>;
  all_complete: boolean;
  segment_count: number;
  room_count: number;
  duration: number;
  overall_score: number | null;
  final_video_url: string | null;
}

export interface TimelineSegment {
  id: string;
  role: string;
  room_type: string;
  video_start: number;
  video_end: number;
  duration: number;
  editing_window: number;
  /** Start on the non-overlapping Studio layout clock. */
  output_start?: number;
  /** Window length on the Studio layout clock. */
  output_duration?: number;
  /** Start of this segment on the real MP4 clock. */
  media_start?: number;
  media_duration?: number;
  /** Absolute MP4 time when narration becomes audible. */
  narration_at?: number;
  narration_text: string;
  audio_url: string | null;
  audio_duration: number;
  audio_offset: number;
  subtitle_enabled: boolean;
  visual_strategy: { type: string; target: string; strength: number };
  highlight: string[];
  pacing_style: string;
}

export interface ThinkingSummary {
  rooms: { room: string; confidence: number }[];
  highlights: string[];
  story: { opening: string[]; middle: string[]; ending: string[] };
  narration_count: number;
}

export interface JobStage {
  name: string;
  label: string;
  status: "pending" | "running" | "done" | "error" | "cancelled";
  detail: string;
}

export interface Job {
  id: string;
  slug: string;
  kind: string;
  segment_id: string;
  status: "pending" | "running" | "done" | "error" | "cancelled";
  stages: JobStage[];
  /** SaaS-style human stage label (Voice Generation, Rendering, …) */
  stage?: string;
  /** 0–100 progress from pipeline callbacks */
  progress?: number;
  error: string;
  result: Record<string, unknown>;
  cancel_requested?: boolean;
  created_at: number;
  updated_at: number;
}

export interface ProjectDetail {
  slug: string;
  video_name: string;
  director_brief: string;
  intent_meta: {
    source: string;
    was_vague: boolean;
    original: string;
    narration_language?: "en" | "zh" | string;
  };
  production?: {
    continuous_walkthrough: boolean;
    preserve_full_span: boolean;
  };
  stages: Record<string, boolean>;
  thinking: ThinkingSummary;
  timeline: TimelineSegment[];
  video: {
    source_url: string;
    draft_url: string | null;
    final_url: string | null;
    duration: number;
  };
  evaluation: {
    approved: boolean;
    overall_score: number;
    summary: string;
    scores: Record<string, number>;
  } | null;
  jobs: Job[];
}

function mediaUrl(path: string | null): string | null {
  if (!path) return null;
  if (path.startsWith("http")) return path;
  return `${API_URL}${path}`;
}

async function studioFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers || {});
  const auth = authHeaders() as Record<string, string>;
  Object.entries(auth).forEach(([k, v]) => {
    if (!headers.has(k)) headers.set(k, v);
  });
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers,
    credentials: "include",
  });
  if (res.status === 401 && typeof window !== "undefined") {
    await handleUnauthorizedResponse(res);
  }
  return res;
}

export async function listProjects(): Promise<ProjectSummary[]> {
  const res = await studioFetch("/api/studio/projects", { cache: "no-store" });
  if (!res.ok) throw new Error(`Failed to list projects: ${res.statusText}`);
  const data: ProjectSummary[] = await res.json();
  return data.map((p) => ({ ...p, final_video_url: mediaUrl(p.final_video_url) }));
}

export async function getProject(slug: string): Promise<ProjectDetail> {
  const res = await studioFetch(`/api/studio/projects/${slug}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Failed to load project: ${res.statusText}`);
  const data: ProjectDetail = await res.json();
  return {
    ...data,
    video: {
      ...data.video,
      source_url: `${API_URL}${data.video.source_url}`,
      draft_url: mediaUrl(data.video.draft_url),
      final_url: mediaUrl(data.video.final_url),
    },
    timeline: data.timeline.map((seg) => ({ ...seg, audio_url: mediaUrl(seg.audio_url) })),
  };
}

export async function reviseScript(
  slug: string,
  segmentId: string,
  text: string
): Promise<{ job_id: string }> {
  const res = await studioFetch(`/api/studio/projects/${slug}/revise`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ change_type: "script_update", segment_id: segmentId, text }),
  });
  if (!res.ok) throw new Error(`Failed to save narration: ${res.statusText}`);
  return res.json();
}

export async function reviseAudioOffset(
  slug: string,
  segmentId: string,
  offsetSeconds: number
): Promise<{ job_id: string }> {
  const res = await studioFetch(`/api/studio/projects/${slug}/revise`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      change_type: "audio_offset",
      segment_id: segmentId,
      offset_seconds: offsetSeconds,
    }),
  });
  if (!res.ok) throw new Error(`Failed to adjust audio: ${res.statusText}`);
  return res.json();
}

export async function exportFinalVideo(slug: string): Promise<{ job_id: string }> {
  const res = await studioFetch(`/api/studio/projects/${slug}/export`, { method: "POST" });
  if (!res.ok) throw new Error(`Failed to start export: ${res.statusText}`);
  return res.json();
}

export async function getJob(jobId: string): Promise<Job> {
  const res = await studioFetch(`/api/studio/jobs/${jobId}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Failed to load job: ${res.statusText}`);
  return res.json();
}

export async function cancelJob(jobId: string): Promise<Job> {
  const res = await studioFetch(`/api/studio/jobs/${jobId}/cancel`, { method: "POST" });
  if (!res.ok) throw new Error(`Failed to cancel job: ${res.statusText}`);
  return res.json();
}

export async function createProject(
  video: File,
  brief: string,
  language: "en" | "zh" = "en"
): Promise<{ job_id: string; slug: string; resolved_brief: string; was_vague: boolean }> {
  const formData = new FormData();
  formData.append("video", video);
  formData.append("brief", brief);
  formData.append("language", language);
  const res = await studioFetch("/api/studio/projects", {
    method: "POST",
    body: formData,
  });
  if (!res.ok) throw new Error(`Failed to create project: ${res.statusText}`);
  return res.json();
}

export async function pollJob(
  jobId: string,
  onUpdate: (job: Job) => void,
  intervalMs = 2000
): Promise<Job> {
  return new Promise((resolve, reject) => {
    const tick = async () => {
      try {
        const job = await getJob(jobId);
        onUpdate(job);
        if (
          job.status === "done" ||
          job.status === "error" ||
          job.status === "cancelled"
        ) {
          resolve(job);
          return;
        }
        setTimeout(tick, intervalMs);
      } catch (e) {
        reject(e);
      }
    };
    tick();
  });
}
