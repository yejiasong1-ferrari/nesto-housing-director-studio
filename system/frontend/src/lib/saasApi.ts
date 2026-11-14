import { authHeaders } from "@/lib/session";
import { handleUnauthorizedResponse } from "@/lib/authFailure";
import { assertVideoLimits, uploadToR2, UploadCancelledError } from "@/lib/uploadR2";

const API_URL = (
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
).replace(/\/$/, "");

export type ProjectStatusResponse = {
  project_id: string;
  title?: string;
  brief?: string;
  status: string;
  stage: string;
  progress: number;
  video_url: string | null;
  download_url?: string | null;
  job_id: string | null;
  job_kind?: string | null;
  workspace_slug?: string | null;
  pipeline_status?: string;
  job_status?: string | null;
  final_video?: string | null;
  error?: string;
};

export type SaasProjectSummary = {
  project_id: string;
  title: string;
  status: string;
  brief: string;
  workspace_slug?: string | null;
  final_video?: string | null;
};

export type CreateProjectResponse = {
  project_id: string;
  status: string;
  message?: string;
  job_id?: string | null;
  language?: string;
  user_id?: string | null;
  title?: string;
};

async function parseError(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") return body.detail;
    return JSON.stringify(body?.detail || body);
  } catch {
    return res.statusText || `HTTP ${res.status}`;
  }
}

async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
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

export async function createSaasProject(input: {
  brief: string;
  language: string;
  title?: string;
  email?: string;
}): Promise<CreateProjectResponse> {
  const res = await apiFetch("/api/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      brief: input.brief,
      language: input.language,
      title: input.title || "Untitled",
      ...(input.email ? { email: input.email } : {}),
    }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function getUploadUrl(
  projectId: string,
  filename: string,
  contentType?: string
): Promise<{ upload_url: string; key: string; content_type: string }> {
  const res = await apiFetch("/api/upload-url", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      project_id: projectId,
      filename,
      content_type: contentType,
    }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function uploadComplete(
  projectId: string,
  key: string
): Promise<{ job_id?: string | null; video_url: string; status: string }> {
  const payload = {
    project_id: projectId,
    key,
    create_job: true,
  };
  let lastError = "Upload complete failed";
  for (let attempt = 1; attempt <= 4; attempt += 1) {
    try {
      const res = await apiFetch("/api/upload-complete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (res.ok) return res.json();
      lastError = await parseError(res);
    } catch (err) {
      lastError = err instanceof Error ? err.message : String(err);
    }
    if (attempt < 4) {
      await new Promise((resolve) => setTimeout(resolve, 1500 * attempt));
    }
  }
  throw new Error(lastError);
}

/** Fallback when R2 is unavailable: multipart to local disk + start job. */
export async function uploadLocalAndStart(
  projectId: string,
  file: File
): Promise<{ job_id?: string | null }> {
  const form = new FormData();
  form.append("file", file);
  form.append("project_id", projectId);
  const scoped = await apiFetch(`/api/projects/${projectId}/upload`, {
    method: "POST",
    body: form,
  });
  if (!scoped.ok) {
    const legacy = await apiFetch("/api/upload", {
      method: "POST",
      body: form,
    });
    if (!legacy.ok) throw new Error(await parseError(scoped));
  }
  const jobRes = await apiFetch("/api/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_id: projectId }),
  });
  if (!jobRes.ok) throw new Error(await parseError(jobRes));
  return jobRes.json();
}

export async function createProjectJob(
  projectId: string
): Promise<{ job_id?: string | null; status?: string; stage?: string; progress?: number }> {
  const res = await apiFetch("/api/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_id: projectId }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function cancelSaasProject(projectId: string): Promise<void> {
  const res = await apiFetch(`/api/projects/${projectId}/cancel`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(await parseError(res));
}

export async function getProjectStatus(
  projectId: string,
  init?: { signal?: AbortSignal }
): Promise<ProjectStatusResponse> {
  const res = await apiFetch(`/api/projects/${projectId}/status`, {
    cache: "no-store",
    signal: init?.signal,
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function listSaasProjects(): Promise<SaasProjectSummary[]> {
  const res = await apiFetch(`/api/projects`, { cache: "no-store" });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export type SaasGeneratePhase = "preparing" | "uploading" | "creating_job";

export async function startSaasGenerate(input: {
  file: File;
  brief: string;
  language: string;
  title?: string;
  onUploadProgress?: (percent: number) => void;
  onPhase?: (phase: SaasGeneratePhase) => void;
  onProjectCreated?: (projectId: string) => void;
  signal?: AbortSignal;
}): Promise<{ projectId: string; jobId?: string | null }> {
  await assertVideoLimits(input.file);
  if (input.signal?.aborted) throw new UploadCancelledError();

  // Distinct from byte upload — API/presign waits used to look like "0% uploading".
  input.onPhase?.("preparing");
  input.onUploadProgress?.(0);

  const project = await createSaasProject({
    brief: input.brief,
    language: input.language,
    title: input.title,
  });
  input.onProjectCreated?.(project.project_id);
  if (input.signal?.aborted) throw new UploadCancelledError();

  try {
    const presign = await getUploadUrl(
      project.project_id,
      input.file.name,
      input.file.type || undefined
    );
    if (input.signal?.aborted) throw new UploadCancelledError();

    input.onPhase?.("uploading");
    const contentType =
      presign.content_type || input.file.type || "video/mp4";

    await uploadToR2(
      presign.upload_url,
      input.file,
      contentType,
      input.onUploadProgress,
      input.signal
    );

    if (input.signal?.aborted) throw new UploadCancelledError();
    input.onPhase?.("creating_job");
    const done = await uploadComplete(project.project_id, presign.key);
    return { projectId: project.project_id, jobId: done.job_id };
  } catch (err) {
    if (err instanceof UploadCancelledError || input.signal?.aborted) {
      throw err instanceof UploadCancelledError ? err : new UploadCancelledError();
    }
    // Local multipart fallback only when R2 is not configured on the API
    // (dev). Upload timeout / network errors surface to the UI.
    const msg = err instanceof Error ? err.message : String(err);
    if (/R2 is not configured/i.test(msg)) {
      input.onPhase?.("creating_job");
      const local = await uploadLocalAndStart(project.project_id, input.file);
      return { projectId: project.project_id, jobId: local.job_id };
    }
    throw err instanceof Error ? err : new Error(msg || "Upload failed");
  }
}

export async function verifyInviteCode(input: {
  code: string;
  device_id: string;
  used_by?: string;
}): Promise<{
  success: boolean;
  token?: string | null;
  expires?: string | null;
  message: string;
}> {
  const res = await fetch(`${API_URL}/api/invite/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(input),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function checkInviteSession(): Promise<{
  valid: boolean;
  expires?: string | null;
  message: string;
}> {
  const res = await apiFetch("/api/invite/session", { cache: "no-store" });
  if (!res.ok) {
    // apiFetch already triggers invite redirect on 401
    return { valid: false, message: "Expired or missing" };
  }
  return res.json();
}
