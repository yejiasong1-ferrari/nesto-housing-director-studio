"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  adminFetch,
  adminJson,
  adminProjectStreamUrl,
  clearAdminKey,
  getAdminKey,
  setAdminKey,
  type AdminInvite,
  type AdminJob,
  type AdminProject,
  type AdminUser,
} from "@/lib/adminApi";

type Tab = "users" | "invites" | "jobs";

function fmtRemaining(sec?: number | null) {
  if (sec == null) return "—";
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function Dot({ on }: { on: boolean }) {
  return (
    <span
      className={`inline-block h-2.5 w-2.5 rounded-full ring-2 ring-zinc-800 ${
        on ? "bg-emerald-400" : "bg-zinc-600"
      }`}
      title={on ? "Online" : "Offline"}
    />
  );
}

type ProjectDetail = {
  project_id?: string;
  title?: string;
  invite_code?: string;
  beta_account_id?: string;
  status?: string;
  progress?: number;
  stage?: string;
  download_url?: string | null;
  video_url?: string | null;
  final_video?: string | null;
  artifacts?: { available?: string[] };
  jobs?: Array<{
    job_id: string;
    kind?: string;
    status?: string;
    stage?: string;
    progress?: number;
  }>;
  error?: string;
};

/** Saved Admin Console UI. Not mounted while ADMIN_CONSOLE_ENABLED is false. */
export default function AdminConsole() {
  const [keyInput, setKeyInput] = useState("");
  const [authed, setAuthed] = useState(false);
  const [tab, setTab] = useState<Tab>("users");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [loggingIn, setLoggingIn] = useState(false);
  const [actionBusy, setActionBusy] = useState<string | null>(null);
  const [actionNote, setActionNote] = useState<string | null>(null);

  const [users, setUsers] = useState<AdminUser[]>([]);
  const [projects, setProjects] = useState<AdminProject[]>([]);
  const [invites, setInvites] = useState<AdminInvite[]>([]);
  const [jobs, setJobs] = useState<AdminJob[]>([]);

  const [selectedUserId, setSelectedUserId] = useState<string | null>(null);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [projectDetail, setProjectDetail] = useState<ProjectDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [debugName, setDebugName] = useState<string | null>(null);
  const [debugJson, setDebugJson] = useState<unknown>(null);
  const [newInviteCode, setNewInviteCode] = useState<string | null>(null);

  useEffect(() => {
    if (getAdminKey()) setAuthed(true);
  }, []);

  const refresh = useCallback(async () => {
    if (!getAdminKey()) return;
    setLoading(true);
    setError(null);
    try {
      const [u, p, i, j] = await Promise.all([
        adminJson<{ users: AdminUser[] }>("/api/admin/users"),
        adminJson<{ projects: AdminProject[] }>("/api/admin/projects"),
        adminJson<{ codes: AdminInvite[] }>("/api/admin/invites"),
        adminJson<{ jobs: AdminJob[] }>("/api/admin/jobs"),
      ]);
      setUsers(u.users || []);
      setProjects(p.projects || []);
      setInvites(i.codes || []);
      setJobs(j.jobs || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
      if (String(e).includes("Invalid admin key") || String(e).includes("403")) {
        clearAdminKey();
        setAuthed(false);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!authed) return;
    let cancelled = false;
    let timer: number | null = null;

    const tick = async () => {
      if (cancelled) return;
      // Skip background tab to save load; catch up when focused
      if (typeof document !== "undefined" && document.visibilityState === "hidden") {
        timer = window.setTimeout(() => void tick(), 5000);
        return;
      }
      await refresh();
      if (!cancelled) {
        timer = window.setTimeout(() => void tick(), 8000);
      }
    };

    void tick();
    const onVis = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      cancelled = true;
      if (timer != null) window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [authed, refresh]);

  const selectedUser = useMemo(
    () => users.find((u) => u.id === selectedUserId) || null,
    [users, selectedUserId]
  );

  const userProjects = useMemo(() => {
    if (!selectedUserId) return [];
    return projects.filter((p) => p.beta_account_id === selectedUserId);
  }, [projects, selectedUserId]);

  const loadProject = async (project: AdminProject) => {
    setSelectedProjectId(project.project_id);
    setDebugName(null);
    setDebugJson(null);
    // Instant shell from list row — detail panel feels immediate
    setProjectDetail({
      project_id: project.project_id,
      title: project.title,
      invite_code: project.invite_code || undefined,
      beta_account_id: project.beta_account_id || undefined,
      status: project.status,
      progress: project.progress,
      stage: project.stage,
      final_video: project.final_video,
      download_url: null,
    });
    setDetailLoading(true);
    try {
      // Status/progress first — don't block the panel on slow media/presign.
      const detail = await adminJson<ProjectDetail>(
        `/api/admin/projects/${project.project_id}`
      );
      setProjectDetail({
        ...detail,
        download_url:
          detail.download_url ||
          adminProjectStreamUrl(project.project_id) ||
          null,
      });
      setDetailLoading(false);
      void adminJson<{ download_url?: string; video_url?: string }>(
        `/api/admin/projects/${project.project_id}/media`
      )
        .then((media) => {
          if (media.download_url) {
            setProjectDetail((prev) =>
              prev && prev.project_id === project.project_id
                ? { ...prev, download_url: media.download_url || prev.download_url }
                : prev
            );
          }
        })
        .catch(() => undefined);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load project");
      setDetailLoading(false);
    }
  };

  const selectUser = (user: AdminUser) => {
    setSelectedUserId(user.id);
    setSelectedProjectId(null);
    setProjectDetail(null);
    setTab("users");
  };

  const loadArtifact = async (name: string) => {
    if (!selectedProjectId) return;
    setDebugName(name);
    try {
      const res = await adminJson<{ data: unknown }>(
        `/api/admin/projects/${selectedProjectId}/artifacts/${name}`
      );
      setDebugJson(res.data);
    } catch (e) {
      setDebugJson({ error: e instanceof Error ? e.message : "Failed" });
    }
  };

  const onLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const key = keyInput.trim();
    if (!key) {
      setError("Enter admin key");
      return;
    }
    setLoggingIn(true);
    setAdminKey(key);
    try {
      // Fast auth only — do not wait for full users/projects scan
      const ctrl = new AbortController();
      const timer = window.setTimeout(() => ctrl.abort(), 20000);
      try {
        await adminJson("/api/admin/ping", { signal: ctrl.signal });
      } finally {
        window.clearTimeout(timer);
      }
      setAuthed(true);
    } catch (err) {
      clearAdminKey();
      const msg =
        err instanceof Error
          ? err.name === "AbortError"
            ? "Server is waking up — try again in a few seconds."
            : err.message
          : "Invalid key";
      setError(msg);
    } finally {
      setLoggingIn(false);
    }
  };

  const createInvite = async () => {
    try {
      const res = await adminJson<{ code: string }>("/api/admin/invites", {
        method: "POST",
        body: "{}",
      });
      setNewInviteCode(res.code);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Create failed");
    }
  };

  const revokeInvite = async (code: string) => {
    if (
      !confirm(
        `Revoke ${code}?\n\nThis invite code can no longer be used.\nIt does not cancel running jobs — use Force logout for that.`
      )
    ) {
      return;
    }
    setActionBusy(`revoke:${code}`);
    setActionNote(null);
    setError(null);
    // Instant UI — don't wait for slow list refresh
    setInvites((prev) =>
      prev.map((c) => (c.code === code ? { ...c, status: "expired", online: false } : c))
    );
    setUsers((prev) =>
      prev.map((u) =>
        u.invite_code === code ? { ...u, status: "revoked", online: false } : u
      )
    );
    setActionNote(`${code} revoked — code is no longer usable.`);
    const ctrl = new AbortController();
    const timer = window.setTimeout(() => ctrl.abort(), 20000);
    try {
      await adminFetch(`/api/admin/invites/${encodeURIComponent(code)}/revoke`, {
        method: "POST",
        signal: ctrl.signal,
      });
    } catch (e) {
      setActionNote(null);
      setError(
        e instanceof Error
          ? e.name === "AbortError"
            ? "Server timed out — try Revoke again."
            : e.message
          : "Revoke failed"
      );
    } finally {
      window.clearTimeout(timer);
      setActionBusy(null);
    }
  };

  const extendInvite = async (code: string) => {
    setActionBusy(`extend:${code}`);
    setError(null);
    try {
      await adminFetch(`/api/admin/invites/${encodeURIComponent(code)}/extend`, {
        method: "POST",
        body: JSON.stringify({ hours: 3 }),
      });
      void refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Extend failed");
    } finally {
      setActionBusy(null);
    }
  };

  const forceLogout = async (accountId: string) => {
    const user = users.find((u) => u.id === accountId);
    const label = user?.invite_code || accountId;
    if (
      !confirm(
        `Force logout ${label}?\n\n• Signs them out immediately\n• Cancels their waiting/running jobs`
      )
    ) {
      return;
    }
    setActionBusy(`logout:${accountId}`);
    setActionNote(null);
    setError(null);
    // Instant feedback
    setUsers((prev) =>
      prev.map((u) =>
        u.id === accountId ? { ...u, status: "revoked", online: false } : u
      )
    );
    setActionNote(`${label}: force logout sent — jobs cancelled, user kicked.`);
    const ctrl = new AbortController();
    const timer = window.setTimeout(() => ctrl.abort(), 20000);
    try {
      const res = await adminJson<{ jobs_cancelled?: number }>(
        `/api/admin/users/${encodeURIComponent(accountId)}/force-logout`,
        { method: "POST", signal: ctrl.signal }
      );
      const n = res.jobs_cancelled ?? 0;
      setActionNote(
        `${label}: signed out · ${n} job${n === 1 ? "" : "s"} cancelled.`
      );
    } catch (e) {
      if (user) {
        setUsers((prev) =>
          prev.map((u) =>
            u.id === accountId ? { ...u, status: user.status, online: user.online } : u
          )
        );
      }
      setActionNote(null);
      setError(
        e instanceof Error
          ? e.name === "AbortError"
            ? "Server timed out — try Force logout again."
            : e.message
          : "Force logout failed"
      );
    } finally {
      window.clearTimeout(timer);
      setActionBusy(null);
    }
  };

  const viewAsUser = async (accountId: string) => {
    try {
      const res = await adminJson<{ token: string; expires_at?: string }>(
        `/api/admin/users/${encodeURIComponent(accountId)}/view-as`,
        { method: "POST", body: JSON.stringify({ ttl_hours: 1 }) }
      );
      const url = `/?view_as=${encodeURIComponent(res.token)}`;
      const win = window.open(url, "nesto-view-as", "noopener,noreferrer,width=1280,height=860");
      if (!win) {
        setError("Popup blocked — allow popups, or open: " + url);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "View-as failed");
    }
  };

  const onlineCount = useMemo(() => users.filter((u) => u.online).length, [users]);
  const detail = projectDetail;

  if (!authed) {
    return (
      <div className="min-h-screen relative flex items-center justify-center px-6 overflow-hidden bg-zinc-950 text-zinc-100">
        <div
          className="pointer-events-none absolute inset-0"
          style={{
            background:
              "radial-gradient(ellipse 80% 50% at 50% -10%, rgba(200,169,110,0.18), transparent 55%), radial-gradient(ellipse 45% 35% at 90% 90%, rgba(58,157,154,0.1), transparent 50%)",
          }}
        />
        <form
          onSubmit={onLogin}
          className="relative w-full max-w-md space-y-7 border border-zinc-800 bg-zinc-900/95 backdrop-blur rounded-3xl p-10 shadow-2xl shadow-black/50"
        >
          <div className="space-y-3 text-center">
            <p className="font-display text-2xl sm:text-3xl tracking-tight text-amber-400/95">
              Nesto Ops
            </p>
            <h1 className="font-display text-4xl text-zinc-50 tracking-tight">Admin Console</h1>
            <p className="text-sm text-zinc-400 leading-relaxed max-w-sm mx-auto">
              Observe beta users, play finals, and control invites — separate from Studio History.
            </p>
          </div>
          <input
            type="password"
            value={keyInput}
            onChange={(e) => setKeyInput(e.target.value)}
            placeholder="INVITE_ADMIN_KEY"
            className="w-full rounded-2xl border border-zinc-700 bg-zinc-950 px-4 py-3.5 text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:border-amber-500/50"
          />
          {error && <p className="text-sm text-amber-400">{error}</p>}
          <button
            type="submit"
            disabled={loggingIn}
            className="w-full rounded-2xl bg-amber-600 hover:bg-amber-500 disabled:opacity-60 text-zinc-950 font-medium py-3.5 text-sm transition-colors"
          >
            {loggingIn ? "Checking key…" : "Enter console"}
          </button>
        </form>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100">
      <header className="sticky top-0 z-20 border-b border-zinc-800/90 bg-zinc-950/90 backdrop-blur px-5 py-3.5 flex items-center gap-4">
        <div className="min-w-0">
          <p className="font-display text-base text-amber-400/90 tracking-tight">Nesto Ops</p>
          <h1 className="font-display text-xl tracking-tight text-zinc-50">Control Center</h1>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2 text-xs text-zinc-400">
          <span className="rounded-full bg-zinc-900 border border-zinc-800 px-3 py-1.5">
            {onlineCount} online
          </span>
          <span className="rounded-full bg-zinc-900 border border-zinc-800 px-3 py-1.5">
            {users.length} users
          </span>
          <span className="rounded-full bg-zinc-900 border border-zinc-800 px-3 py-1.5">
            {projects.length} projects
          </span>
          <button
            type="button"
            onClick={() => void refresh()}
            className="rounded-full border border-zinc-700 bg-zinc-900 px-3 py-1.5 hover:border-zinc-500 text-zinc-300"
          >
            {loading ? "Refreshing…" : "Refresh"}
          </button>
          <button
            type="button"
            onClick={() => {
              window.open("/admin", "nesto-admin", "noopener,noreferrer,width=1400,height=900");
            }}
            className="rounded-full border border-zinc-700 bg-zinc-900 px-3 py-1.5 hover:border-zinc-500 text-zinc-300"
          >
            Pop out
          </button>
          <button
            type="button"
            onClick={() => {
              clearAdminKey();
              setAuthed(false);
            }}
            className="rounded-full border border-zinc-700 bg-zinc-900 px-3 py-1.5 hover:border-amber-600/50 text-zinc-300"
          >
            Lock
          </button>
        </div>
      </header>

      {error && (
        <div className="mx-5 mt-3 rounded-2xl border border-amber-700/40 bg-amber-950/40 px-4 py-2.5 text-sm text-amber-200">
          {error}
        </div>
      )}
      {actionNote && !error && (
        <div className="mx-5 mt-3 rounded-2xl border border-emerald-800/50 bg-emerald-950/30 px-4 py-2.5 text-sm text-emerald-300">
          {actionNote}
        </div>
      )}

      <div className="flex gap-1 px-5 pt-4">
        {(
          [
            ["users", "Users & Projects"],
            ["invites", "Invites"],
            ["jobs", "Jobs"],
          ] as [Tab, string][]
        ).map(([t, label]) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={`rounded-full px-4 py-2 text-sm transition-colors ${
              tab === t
                ? "bg-zinc-100 text-zinc-950"
                : "text-zinc-500 hover:text-zinc-200 hover:bg-zinc-900"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "users" && (
        <div className="grid grid-cols-1 xl:grid-cols-[280px_1fr_400px] gap-4 p-5">
          <section className="rounded-3xl border border-zinc-800 bg-zinc-900/50 overflow-hidden min-h-[560px]">
            <div className="px-4 py-3 border-b border-zinc-800 bg-zinc-900/80">
              <p className="text-[11px] uppercase tracking-wide text-zinc-500">Users</p>
              <p className="text-sm text-zinc-300 mt-0.5">Click a user to see projects</p>
            </div>
            <ul className="divide-y divide-zinc-800/80 max-h-[70vh] overflow-auto">
              {users.map((u) => (
                <li key={u.id}>
                  <button
                    type="button"
                    onClick={() => selectUser(u)}
                    className={`w-full text-left px-4 py-3.5 hover:bg-zinc-800/60 transition-colors ${
                      selectedUserId === u.id ? "bg-zinc-800/80" : ""
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <Dot on={u.online} />
                      <span className="font-mono text-xs font-medium truncate text-zinc-100">{u.invite_code}</span>
                    </div>
                    <div className="mt-1.5 flex gap-3 text-[11px] text-zinc-500">
                      <span>{u.project_count} projects</span>
                      <span>{u.video_count} videos</span>
                      <span
                        className={`capitalize ${
                          u.status === "revoked" ? "text-amber-400 font-medium" : ""
                        }`}
                      >
                        {u.status}
                      </span>
                    </div>
                  </button>
                </li>
              ))}
              {users.length === 0 && (
                <li className="p-6 text-sm text-zinc-500">No beta users yet.</li>
              )}
            </ul>
          </section>

          <section className="rounded-3xl border border-zinc-800 bg-zinc-900/50 overflow-hidden min-h-[560px]">
            <div className="px-4 py-3 border-b border-zinc-800 bg-zinc-900/80 flex items-start justify-between gap-3">
              <div>
                <p className="text-[11px] uppercase tracking-wide text-zinc-500">Projects</p>
                <p className="text-sm text-zinc-300 mt-0.5">
                  {selectedUser
                    ? `Under ${selectedUser.invite_code}`
                    : "Select a user on the left"}
                </p>
              </div>
              {selectedUser && (
                <div className="flex gap-2 shrink-0">
                  <button
                    type="button"
                    onClick={() => void viewAsUser(selectedUser.id)}
                    className="rounded-full bg-amber-600 text-zinc-950 text-xs font-medium px-3 py-1.5 hover:bg-amber-500"
                  >
                    View as
                  </button>
                  <button
                    type="button"
                    disabled={actionBusy === `logout:${selectedUser.id}`}
                    onClick={() => void forceLogout(selectedUser.id)}
                    className="rounded-full border border-zinc-700 text-xs px-3 py-1.5 text-zinc-300 hover:border-amber-600/50 disabled:opacity-50"
                  >
                    {actionBusy === `logout:${selectedUser.id}`
                      ? "Logging out…"
                      : selectedUser.status === "revoked"
                        ? "Logged out"
                        : "Force logout"}
                  </button>
                </div>
              )}
            </div>
            {!selectedUser ? (
              <p className="p-8 text-sm text-zinc-500">
                Pick a user to list their projects and open a final video.
              </p>
            ) : userProjects.length === 0 ? (
              <p className="p-8 text-sm text-zinc-500">This user has no projects yet.</p>
            ) : (
              <ul className="divide-y divide-zinc-800/80 max-h-[70vh] overflow-auto">
                {userProjects.map((p) => (
                  <li key={p.project_id}>
                    <button
                      type="button"
                      onClick={() => void loadProject(p)}
                      className={`w-full text-left px-4 py-3.5 hover:bg-zinc-800/60 transition-colors ${
                        selectedProjectId === p.project_id ? "bg-zinc-800/80" : ""
                      }`}
                    >
                      <div className="flex items-center justify-between gap-3">
                        <span className="font-medium text-sm truncate text-zinc-100">
                          {p.title || p.project_id}
                        </span>
                        {p.has_final ? (
                          <span className="shrink-0 text-[10px] uppercase tracking-wide rounded-full bg-emerald-950 text-emerald-400 border border-emerald-800/60 px-2 py-0.5">
                            Final
                          </span>
                        ) : null}
                      </div>
                      <div className="mt-1 text-[11px] text-zinc-500">
                        {p.status}
                        {p.stage ? ` · ${p.stage}` : ""}
                        {p.progress != null ? ` · ${p.progress}%` : ""}
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <aside className="rounded-3xl border border-zinc-800 bg-zinc-900/50 p-5 space-y-4 min-h-[560px]">
            {!detail ? (
              <div className="h-full flex items-center justify-center text-sm text-zinc-500 px-4 text-center">
                Click a project to open detail and play the final video.
              </div>
            ) : (
              <>
                <div>
                  <p className="text-[10px] uppercase tracking-wide text-zinc-500">
                    Project detail {detailLoading ? "· loading…" : ""}
                  </p>
                  <h2 className="font-display text-2xl mt-1 leading-tight text-zinc-50">
                    {detail.title || selectedProjectId}
                  </h2>
                  <p className="text-xs text-zinc-500 mt-1">
                    {detail.invite_code || "—"} · {detail.beta_account_id || "—"}
                  </p>
                </div>
                <div className="grid grid-cols-2 gap-2 text-sm">
                  <div className="rounded-2xl bg-zinc-950/70 border border-zinc-800 p-3">
                    <p className="text-zinc-500 text-[11px]">Status</p>
                    <p className="font-medium mt-0.5 text-zinc-100">{detail.status}</p>
                  </div>
                  <div className="rounded-2xl bg-zinc-950/70 border border-zinc-800 p-3">
                    <p className="text-zinc-500 text-[11px]">Progress</p>
                    <p className="font-medium mt-0.5 text-zinc-100">
                      {detail.progress ?? 0}% · {detail.stage || "—"}
                    </p>
                  </div>
                </div>

                {detail.download_url ? (
                  <div className="space-y-2">
                    <video
                      key={detail.download_url}
                      src={detail.download_url}
                      controls
                      playsInline
                      preload="metadata"
                      className="w-full rounded-2xl bg-black aspect-video"
                    />
                    <a
                      href={detail.download_url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex text-sm text-amber-400 hover:underline"
                    >
                      Open / download final
                    </a>
                  </div>
                ) : detailLoading ? (
                  <div className="rounded-2xl border border-dashed border-zinc-700 bg-zinc-950/50 aspect-video flex items-center justify-center text-sm text-zinc-500">
                    Fetching final video…
                  </div>
                ) : (
                  <div className="rounded-2xl border border-dashed border-zinc-700 bg-zinc-950/50 p-4 text-sm text-zinc-500 space-y-1">
                    <p>No playable final video yet.</p>
                    {detail.final_video || detail.video_url ? (
                      <p className="text-[11px] break-all text-zinc-600">
                        Stored: {detail.final_video || detail.video_url}
                      </p>
                    ) : null}
                  </div>
                )}

                {detail.error ? (
                  <p className="text-xs text-amber-300 whitespace-pre-wrap">{detail.error}</p>
                ) : null}

                <div>
                  <p className="text-[10px] uppercase tracking-wide text-zinc-500 mb-2">
                    Debug view
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {(
                      detail.artifacts?.available || [
                        "vkb",
                        "planner",
                        "script",
                        "timeline",
                        "render",
                      ]
                    ).map((name) => (
                      <button
                        key={name}
                        type="button"
                        onClick={() => void loadArtifact(name)}
                        className={`rounded-full border px-3 py-1 text-xs ${
                          debugName === name
                            ? "border-amber-500/70 bg-amber-950/40 text-amber-300"
                            : "border-zinc-700 text-zinc-400 hover:border-zinc-500"
                        }`}
                      >
                        {name}
                      </button>
                    ))}
                  </div>
                  {debugJson != null && (
                    <pre className="mt-3 max-h-72 overflow-auto rounded-2xl bg-black border border-zinc-800 text-zinc-300 p-3 text-[11px] leading-relaxed">
                      {JSON.stringify(debugJson, null, 2)}
                    </pre>
                  )}
                </div>

                {detail.jobs && detail.jobs.length > 0 && (
                  <div>
                    <p className="text-[10px] uppercase tracking-wide text-zinc-500 mb-2">
                      Jobs
                    </p>
                    <ul className="space-y-1 text-xs text-zinc-500">
                      {detail.jobs.map((j) => (
                        <li key={j.job_id}>
                          {j.kind} · {j.status} · {j.stage} · {j.progress}%
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </>
            )}
          </aside>
        </div>
      )}

      {tab === "invites" && (
        <div className="p-5">
          <section className="rounded-3xl border border-zinc-800 bg-zinc-900/50 overflow-hidden">
            <div className="p-4 border-b border-zinc-800 flex items-center gap-3 bg-zinc-900/80">
              <button
                type="button"
                onClick={() => void createInvite()}
                className="rounded-full bg-amber-600 text-zinc-950 px-4 py-2 text-sm font-medium hover:bg-amber-500"
              >
                Create invite
              </button>
              {newInviteCode && (
                <span className="font-mono text-sm text-emerald-400">{newInviteCode}</span>
              )}
            </div>
            <table className="w-full text-sm">
              <thead className="text-left text-zinc-500 border-b border-zinc-800 bg-zinc-950/40">
                <tr>
                  <th className="p-3">Invite</th>
                  <th className="p-3">Status</th>
                  <th className="p-3">Remaining</th>
                  <th className="p-3">Projects</th>
                  <th className="p-3">Videos</th>
                  <th className="p-3">Online</th>
                  <th className="p-3">Actions</th>
                </tr>
              </thead>
              <tbody>
                {invites.map((c) => (
                  <tr key={c.code} className="border-b border-zinc-800/80">
                    <td className="p-3 font-mono text-xs text-zinc-200">{c.code}</td>
                    <td className="p-3 text-zinc-300">{c.status}</td>
                    <td className="p-3 font-mono text-xs text-zinc-400">{fmtRemaining(c.remaining_seconds)}</td>
                    <td className="p-3 text-zinc-300">{c.project_count}</td>
                    <td className="p-3 text-zinc-300">{c.video_count}</td>
                    <td className="p-3">
                      <Dot on={c.online} />
                    </td>
                    <td className="p-3 space-x-3 text-xs">
                      <button
                        type="button"
                        className="text-zinc-300 hover:underline"
                        onClick={() => void extendInvite(c.code)}
                      >
                        Extend
                      </button>
                      <button
                        type="button"
                        className="text-amber-400 hover:underline disabled:opacity-50"
                        disabled={actionBusy === `revoke:${c.code}` || c.status === "expired"}
                        onClick={() => void revokeInvite(c.code)}
                      >
                        {actionBusy === `revoke:${c.code}`
                          ? "Revoking…"
                          : c.status === "expired"
                            ? "Revoked"
                            : "Revoke"}
                      </button>
                      {c.beta_account_id && (
                        <button
                          type="button"
                          className="text-emerald-400 hover:underline"
                          onClick={() => {
                            const u = users.find((x) => x.id === c.beta_account_id);
                            if (u) selectUser(u);
                          }}
                        >
                          Open user
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </div>
      )}

      {tab === "jobs" && (
        <div className="p-5">
          <section className="rounded-3xl border border-zinc-800 bg-zinc-900/50 overflow-hidden">
            <table className="w-full text-sm">
              <thead className="text-left text-zinc-500 border-b border-zinc-800 bg-zinc-950/40">
                <tr>
                  <th className="p-3">User</th>
                  <th className="p-3">Project</th>
                  <th className="p-3">Job</th>
                  <th className="p-3">Status</th>
                  <th className="p-3">Stage</th>
                  <th className="p-3">Progress</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((j) => (
                  <tr
                    key={j.job_id}
                    className="border-b border-zinc-800/80 hover:bg-zinc-800/40 cursor-pointer"
                    onClick={() => {
                      if (j.beta_account_id) {
                        const u = users.find((x) => x.id === j.beta_account_id);
                        if (u) selectUser(u);
                      }
                      const p = projects.find((x) => x.project_id === j.project_id);
                      if (p) void loadProject(p);
                    }}
                  >
                    <td className="p-3 font-mono text-xs text-zinc-300">{j.invite_code || "—"}</td>
                    <td className="p-3 text-zinc-200">{j.title || j.project_id}</td>
                    <td className="p-3 font-mono text-xs text-zinc-500">{j.job_id}</td>
                    <td className="p-3 text-zinc-300">{j.status}</td>
                    <td className="p-3 text-zinc-500 text-xs">{j.stage || "—"}</td>
                    <td className="p-3 text-zinc-300">{j.progress ?? 0}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </div>
      )}
    </div>
  );
}

