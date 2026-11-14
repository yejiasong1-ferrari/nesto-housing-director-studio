/** Map SaaS project status → Studio Job shape (v3.1 JobProgress UI). */

import type { Job, JobStage } from "@/lib/studioApi";
import type { ProjectStatusResponse } from "@/lib/saasApi";
import { SAAS_STAGE_DEFS as STAGE_DEFS } from "@/lib/saasStageDefs";

/** Only trust API project/job completion — never treat mid-pipeline
 *  stage "Completed" / progress 100 as done (Worker still uploads studio). */
export function isSaasDone(s: ProjectStatusResponse): boolean {
  return s.status === "completed";
}

export function mapSaasStatusToJob(
  projectId: string,
  s: ProjectStatusResponse,
  opts?: { title?: string }
): Job {
  const stage = s.stage || "";
  const progress = s.progress ?? 0;
  const done = isSaasDone(s);
  const failed = s.status === "error";
  const cancelled = s.status === "cancelled";

  let activeIdx = STAGE_DEFS.findIndex((d) => d.match.test(stage));
  if (activeIdx < 0) {
    activeIdx = STAGE_DEFS.reduce(
      (acc, d, i) => (progress >= d.minProgress ? i : acc),
      0
    );
  }
  if (s.status === "waiting" && progress === 0) activeIdx = 0;

  const stages: JobStage[] = STAGE_DEFS.map((d, i) => {
    if (done) return { name: d.name, label: d.label, status: "done", detail: "" };
    if (cancelled) {
      if (i < activeIdx) return { name: d.name, label: d.label, status: "done", detail: "" };
      if (i === activeIdx)
        return { name: d.name, label: d.label, status: "cancelled", detail: "Cancelled" };
      return { name: d.name, label: d.label, status: "cancelled", detail: "" };
    }
    if (failed) {
      if (i < activeIdx) return { name: d.name, label: d.label, status: "done", detail: "" };
      if (i === activeIdx)
        return { name: d.name, label: d.label, status: "error", detail: s.error || "" };
      return { name: d.name, label: d.label, status: "pending", detail: "" };
    }
    if (i < activeIdx) return { name: d.name, label: d.label, status: "done", detail: "" };
    if (i === activeIdx)
      return {
        name: d.name,
        label: d.label,
        status: "running",
        detail:
          s.status === "waiting"
            ? "Waiting for Worker…"
            : stage && !d.match.test(stage)
              ? stage
              : "",
      };
    return { name: d.name, label: d.label, status: "pending", detail: "" };
  });

  const now = Date.now() / 1000;
  return {
    id: s.job_id || projectId,
    slug: s.workspace_slug || "",
    kind: "create",
    segment_id: "",
    status: done ? "done" : failed ? "error" : cancelled ? "cancelled" : "running",
    stages,
    stage: done ? "Completed" : stage || (s.status === "waiting" ? "Queued" : ""),
    progress: done ? 100 : progress,
    error: s.error || "",
    result: opts?.title ? { title: opts.title } : {},
    created_at: now,
    updated_at: now,
  };
}

export function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}
