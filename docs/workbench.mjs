import {
  VERSION,
  duration,
  timecode,
  toSrt,
  validate,
  sanitizeProject,
  exportProject,
  splitScene,
} from "./workbench-core.mjs";

const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const esc = (v) =>
  String(v ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const clone = (v) => structuredClone(v);
const uid = () =>
  crypto.randomUUID?.() ||
  `id-${Date.now()}-${Math.random().toString(36).slice(2)}`;
const stamp = () => new Date().toISOString();
let db,
  projects = [],
  current,
  selected = 0,
  view = "studio",
  sourceUrl = "",
  objectUrl = "",
  referenceUrl = "",
  history = [],
  playlist = false,
  saveTimer,
  toastTimer,
  saving = Promise.resolve();
let agentIndex = 0,
  mapIndex = 0,
  endpoint = "",
  endpointResult = "",
  renderActive = false,
  persistent = true,
  playIndex = 0;
const views = {
  studio: "Production studio",
  projects: "Projects",
  workflow: "Agent workflow",
  system: "System architecture",
  settings: "Connections & privacy",
};
const agents = [
  [
    "Vision",
    "Read the space",
    "Analyze representative frames and room segments to build a grounded scene inventory. This supplies the factual context used by planning and narration.",
    "Scene inventory · room features · representative frames",
    "Perception",
  ],
  [
    "Planner",
    "Shape the story",
    "Interpret the director brief, rank property highlights, choose a narrative arc and allocate attention across rooms.",
    "Director plan · scene roles · attention budget",
    "Reasoning",
  ],
  [
    "Script",
    "Write with evidence",
    "Compose scene-specific narration using the visual knowledge base. Validate style, coverage and the available speech window.",
    "Scene narration · duration estimates · coverage checks",
    "Reasoning",
  ],
  [
    "Voice",
    "Direct the delivery",
    "Plan voice style, rhythm and pronunciation. A separate TTS execution service synthesizes the audio and measures its duration.",
    "Voice specification · synthesized audio · measured duration",
    "Speech",
  ],
  [
    "Timeline",
    "Make time consistent",
    "Validate narration budgets before speech synthesis, then reconcile the final scene windows with measured audio durations.",
    "Aligned windows · offsets · constraint report",
    "Deterministic + reasoning",
  ],
  [
    "Editing",
    "Choose the treatment",
    "Produce structured decisions for pacing, visual operations, subtitles and audio treatment. Human edits can refine the plan in the Studio.",
    "Editing plan · effects · subtitle and audio settings",
    "Reasoning",
  ],
  [
    "Rendering",
    "Build the artifact",
    "Apply the approved media plan with MoviePy and FFmpeg. The browser editor also offers a local Canvas/MediaRecorder export of its storyboard.",
    "Rendered video · timing manifest · output metadata",
    "Execution",
  ],
  [
    "Evaluation",
    "Close the loop",
    "Check timing, audiovisual alignment, subtitle behavior and technical quality. Route a bounded correction pass when constraints fail.",
    "Evaluation report · categorized issues · correction route",
    "Review",
  ],
];

function toast(message) {
  $("#toast").textContent = message;
  $("#toast").classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $("#toast").classList.remove("show"), 4200);
}
function request(store, method, value) {
  if (!db) return Promise.resolve(null);
  return new Promise((resolve, reject) => {
    const tx = db.transaction(
      store,
      method === "get" || method === "getAll" ? "readonly" : "readwrite",
    );
    const req =
      value === undefined
        ? tx.objectStore(store)[method]()
        : tx.objectStore(store)[method](value);
    let result;
    req.onsuccess = () => {
      result = req.result;
    };
    tx.oncomplete = () => resolve(result);
    tx.onerror = () => reject(tx.error);
    tx.onabort = () =>
      reject(tx.error || new Error("Storage transaction aborted."));
  });
}
async function openDB() {
  db = await new Promise((resolve, reject) => {
    const r = indexedDB.open("nesto-studio", VERSION);
    r.onupgradeneeded = () => {
      if (!r.result.objectStoreNames.contains("projects"))
        r.result.createObjectStore("projects", { keyPath: "id" });
      if (!r.result.objectStoreNames.contains("media"))
        r.result.createObjectStore("media", { keyPath: "id" });
    };
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
  });
}
function checkpoint() {
  history.push(clone(current));
  if (history.length > 30) history.shift();
}
function queueSave() {
  current.updatedAt = stamp();
  $("#save-status").textContent = "Saving…";
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => persist(), 250);
}
async function persist() {
  clearTimeout(saveTimer);
  const snapshot = clone(current);
  const i = projects.findIndex((p) => p.id === snapshot.id);
  if (i < 0) projects.push(snapshot);
  else projects[i] = snapshot;
  saving = saving
    .then(() => request("projects", "put", snapshot))
    .then(() => {
      $("#save-status").textContent = persistent
        ? "Saved on this device"
        : "Session only · export to save";
    })
    .catch(() => {
      persistent = false;
      $("#save-status").textContent = "Storage full · export to save";
      toast(
        "Device storage is unavailable. Export the project JSON to keep your edits.",
      );
    });
  await saving;
}
async function setProject(project) {
  $$(".nav-button, #import-button, #export-button").forEach((button) => {
    button.disabled = true;
  });
  if (current) await persist();
  current = clone(project);
  selected = 0;
  history = [];
  playlist = false;
  if (objectUrl) URL.revokeObjectURL(objectUrl);
  objectUrl = "";
  sourceUrl = "";
  if (current.sourceKind === "reference") {
    // A complete local Blob supports accurate seeking even on simple static
    // servers that do not implement HTTP byte ranges.
    if (!referenceUrl) {
      const r = await fetch("assets/harbor-walkthrough.mp4");
      if (!r.ok) throw new Error("Reference media could not be loaded.");
      referenceUrl = URL.createObjectURL(await r.blob());
    }
    sourceUrl = referenceUrl;
  } else if (current.mediaKey && db) {
    const media = await request("media", "get", current.mediaKey);
    if (media?.blob) sourceUrl = objectUrl = URL.createObjectURL(media.blob);
  }
  try {
    localStorage.setItem("nesto-current", current.id);
  } catch {}
  view = "studio";
  render();
  await persist();
  $$(".nav-button, #import-button, #export-button").forEach((button) => {
    button.disabled = false;
  });
}
function download(name, content, type) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 60000);
}
const filename = () =>
  current.name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "") || "nesto-project";
function closeModal() {
  if (renderActive) return;
  $("#modal-root").innerHTML = "";
}
function modal(title, html) {
  $("#modal-root").innerHTML =
    `<div class="modal-backdrop"><section class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title"><div class="panel-bar"><h2 id="modal-title">${esc(title)}</h2><button class="button ghost" data-close aria-label="Close dialog">✕</button></div><div class="modal-content">${html}</div></section></div>`;
  $("[data-close]").onclick = closeModal;
  $(".modal-backdrop").onclick = (e) => {
    if (e.target === e.currentTarget) closeModal();
  };
  setTimeout(
    () => $(".modal input, .modal button:not([data-close])")?.focus(),
    0,
  );
}
function formModal(title, value, onSave) {
  modal(
    title,
    `<form id="name-form"><label class="field-label" for="project-name">Project name</label><input class="field" id="project-name" maxlength="80" required value="${esc(value)}"><div class="modal-actions"><button class="button" type="button" data-cancel>Cancel</button><button class="button primary">Save</button></div></form>`,
  );
  $("[data-cancel]").onclick = closeModal;
  $("#name-form").onsubmit = async (e) => {
    e.preventDefault();
    const name = $("#project-name").value.trim();
    if (!name) return;
    await onSave(name);
    closeModal();
  };
}

function render() {
  $("#current-view").textContent = views[view];
  $$(".nav-button").forEach((b) =>
    b.classList.toggle("active", b.dataset.view === view),
  );
  $("#export-button").disabled = !current;
  if (view === "studio") renderStudio();
  else if (view === "projects") renderProjects();
  else if (view === "workflow") renderWorkflow();
  else if (view === "system") renderSystem();
  else renderSettings();
}
function renderStudio() {
  selected = Math.max(0, Math.min(selected, current.scenes.length - 1));
  const s = current.scenes[selected];
  $("#main").innerHTML =
    `<div class="project-header"><div><div class="section-label">PROPERTY VIDEO / WORKSPACE</div><h1>${esc(current.name)}</h1><p class="muted">${current.sourceKind === "reference" ? "Reference project · recorded output · editable storyboard" : "Local footage · private on this device"}</p></div><div class="actions"><button class="button small" id="rename-project">Rename</button><button class="button small" id="undo" ${history.length ? "" : "disabled"}>↶ Undo</button></div></div>
    <div class="studio-grid"><div class="preview-panel"><div class="panel-bar"><span>Program monitor</span><span class="tag gold">${current.sourceKind === "reference" ? "SAVED OUTPUT" : "LOCAL VIDEO"}</span></div><div class="video-stage">${sourceUrl ? `<video id="preview" src="${esc(sourceUrl)}" controls playsinline preload="metadata" ${current.sourceKind === "reference" ? 'poster="assets/reference-poster.jpg"' : ""}></video>` : '<div class="media-empty"><b>Relink the source video</b><p>Project files contain edits, not your footage.</p><button class="button primary" id="relink-video">Choose local video</button></div>'}</div><div class="source-note">${current.sourceKind === "reference" ? '55-second saved render · Chinese narration · MorrisHK walkthrough footage. <a href="https://github.com/yejiasong1-ferrari/nesto-housing-director-studio/blob/main/docs/MEDIA_NOTES.md" target="_blank" rel="noopener">Media provenance ↗</a>' : "Local file playback. Importing video does not upload it to a server."}</div><div class="brief-block"><label class="field-label" for="brief">DIRECTOR BRIEF</label><textarea class="field" id="brief" rows="2" maxlength="4000">${esc(current.brief)}</textarea></div></div>
    <aside class="inspector"><div class="panel-bar"><span>Scene inspector</span><span class="tag">${s ? String(selected + 1).padStart(2, "0") : "—"}</span></div><div class="inspector-body">${
      s
        ? `<label class="field-label" for="scene-name">SCENE NAME</label><input class="field" id="scene-name" maxlength="80" value="${esc(s.name)}"><div class="two-fields"><div><label class="field-label" for="scene-role">STORY ROLE</label><select class="field" id="scene-role">${["HERO", "SUPPORT", "TRANSITION"].map((v) => `<option ${s.role === v ? "selected" : ""}>${v}</option>`).join("")}</select></div><div><label class="field-label">DURATION</label><div class="field" id="scene-duration">${(s.end - s.start).toFixed(2)} s</div></div></div><div class="two-fields"><div><label class="field-label" for="scene-start">IN / SECONDS</label><input type="number" class="field" id="scene-start" min="0" max="${current.sourceDuration}" step="0.1" value="${s.start}"></div><div><label class="field-label" for="scene-end">OUT / SECONDS</label><input type="number" class="field" id="scene-end" min="0" max="${current.sourceDuration}" step="0.1" value="${s.end}"></div></div><label class="field-label" for="narration">NARRATION</label><textarea class="field" id="narration" maxlength="4000" rows="4">${esc(s.narration)}</textarea><p class="helper">${s.voiceDirty ? "Text changed. Recorded voice requires server-side regeneration." : s.voiceDuration != null ? `Recorded voice: ${s.voiceDuration.toFixed(2)} s. Text edits export to subtitles; they do not replace this audio.` : "Write narration for subtitle export or private server-side synthesis."}</p><label class="field-label" for="scene-effect">LOCAL EXPORT TREATMENT</label><select class="field" id="scene-effect">${[
            ["none", "Original framing"],
            ["slow_zoom", "Gentle push-in"],
            ["ken_burns", "Slow pan & zoom"],
          ]
            .map(
              ([v, t]) =>
                `<option value="${v}" ${s.effect === v ? "selected" : ""}>${t}</option>`,
            )
            .join(
              "",
            )}</select><p class="helper">Framing treatments apply during local video export.</p><div class="inspector-actions"><button class="button small" id="move-left" ${selected === 0 ? "disabled" : ""}>← Earlier</button><button class="button small" id="move-right" ${selected === current.scenes.length - 1 ? "disabled" : ""}>Later →</button><button class="button small" id="split-scene">Split at playhead</button><button class="button small danger" id="remove-scene">Remove scene</button></div>`
        : '<p class="muted">Add a scene to begin.</p>'
    }</div></aside>
    <section class="timeline"><div class="timeline-head"><div><h2>Storyboard timeline <span class="muted small">${current.scenes.length} scenes</span></h2><p class="small muted">Select a scene to inspect and edit its source range.</p></div><div class="actions"><button class="button small" id="add-scene">+ Add scene</button><button class="button small primary" id="play-story" ${sourceUrl && s ? "" : "disabled"}>▶ Play sequence</button></div></div><div class="timeline-track">${current.scenes.map((scene, i) => `<button class="scene-tile ${i === selected ? "selected" : ""}" data-scene="${i}" style="flex:${Math.max(1, scene.end - scene.start)}"><span class="scene-num">${String(i + 1).padStart(2, "0")} / ${esc(scene.role)}</span><span class="scene-name">${esc(scene.name)}</span><span class="scene-dur">${(scene.end - scene.start).toFixed(1)} s</span></button>`).join("")}</div><div class="timeline-footer"><span id="playhead">Source <b>00:00:00</b></span><span>Total output <b>${timecode(duration(current))}</b> · ${duration(current).toFixed(2)} s</span><button class="button ghost small" id="validate">✓ Validate timeline</button></div></section></div>
    <section class="statusbar"><div><span class="dot"></span><b>Local editing ready</b><span class="muted"> · ${current.scenes.length} structured scenes · no upload required</span></div><button class="button ghost small" data-go="workflow">Inspect agent workflow →</button></section><div id="validation-results"></div>`;
  $("#rename-project").onclick = () =>
    formModal("Rename project", current.name, async (name) => {
      checkpoint();
      current.name = name;
      await persist();
      render();
    });
  $("#undo").onclick = () => {
    const last = history.pop();
    if (last) {
      current = last;
      queueSave();
      render();
    }
  };
  $("#brief").onchange = (e) => {
    checkpoint();
    current.brief = e.target.value;
    queueSave();
  };
  $("#relink-video")?.addEventListener("click", () => chooseVideo(true));
  $("[data-go]")?.addEventListener("click", (e) => {
    view = e.currentTarget.dataset.go;
    render();
  });
  $$("[data-scene]").forEach(
    (b) =>
      (b.onclick = () => {
        playlist = false;
        selected = Number(b.dataset.scene);
        renderStudio();
        seekPreview(current.scenes[selected].start);
      }),
  );
  const video = $("#preview");
  const advance = () => {
    if (!playlist) return;
    if (playIndex + 1 < current.scenes.length) {
      playIndex++;
      video.currentTime = current.scenes[playIndex].start;
      highlightScene();
      video.play().catch(() => {
        playlist = false;
      });
    } else {
      playlist = false;
      video.pause();
      $("#play-story").textContent = "▶ Play sequence";
      highlightScene();
    }
  };
  if (video) {
    video.addEventListener("timeupdate", () => {
      const el = $("#playhead b");
      if (el) el.textContent = timecode(video.currentTime);
      if (
        playlist &&
        current.scenes[playIndex] &&
        video.currentTime >= current.scenes[playIndex].end - 0.035
      )
        advance();
    });
    video.addEventListener("ended", advance);
  }
  $("#play-story").onclick = async () => {
    if (playlist) {
      playlist = false;
      video.pause();
      $("#play-story").textContent = "▶ Play sequence";
      highlightScene();
      return;
    }
    playlist = true;
    playIndex = selected;
    video.currentTime = current.scenes[playIndex].start;
    highlightScene();
    try {
      await video.play();
      $("#play-story").textContent = "Ⅱ Pause sequence";
    } catch {
      playlist = false;
      toast("Use the video play button to allow playback.");
    }
  };
  $("#add-scene").onclick = () => {
    checkpoint();
    const start =
      current.scenes.at(-1)?.end < current.sourceDuration - 0.1
        ? current.scenes.at(-1).end
        : 0;
    current.scenes.push({
      id: uid(),
      name: `Scene ${current.scenes.length + 1}`,
      role: "SUPPORT",
      start,
      end: Math.min(current.sourceDuration, start + 5),
      narration: "",
      voiceDuration: null,
      voiceDirty: false,
      effect: "none",
    });
    selected = current.scenes.length - 1;
    queueSave();
    render();
    seekPreview(start);
  };
  $("#validate").onclick = showValidation;
  if (!s) return;
  const bind = (id, key) => {
    $(id).onchange = (e) => {
      checkpoint();
      s[key] = e.target.value;
      queueSave();
      if (key === "name") {
        $$("[data-scene] .scene-name")[selected].textContent = s.name;
      }
    };
  };
  bind("#scene-name", "name");
  bind("#scene-role", "role");
  bind("#scene-effect", "effect");
  $("#narration").onchange = (e) => {
    checkpoint();
    s.narration = e.target.value;
    s.voiceDirty = Boolean(s.narration);
    queueSave();
    $(".inspector .helper").textContent =
      "Text changed. Recorded voice requires server-side regeneration.";
  };
  for (const id of ["#scene-start", "#scene-end"])
    $(id).onchange = (e) => {
      const key = id.endsWith("start") ? "start" : "end";
      const n = Number(e.target.value);
      if (
        !Number.isFinite(n) ||
        n < 0 ||
        n > current.sourceDuration ||
        (key === "start" ? n >= s.end : n <= s.start)
      ) {
        e.target.value = s[key];
        toast("Choose a valid range inside the source video.");
        return;
      }
      checkpoint();
      s[key] = n;
      queueSave();
      render();
      seekPreview(s.start);
    };
  const move = (delta) => {
    checkpoint();
    [current.scenes[selected], current.scenes[selected + delta]] = [
      current.scenes[selected + delta],
      current.scenes[selected],
    ];
    selected += delta;
    queueSave();
    render();
    seekPreview(current.scenes[selected].start);
  };
  $("#move-left").onclick = () => move(-1);
  $("#move-right").onclick = () => move(1);
  $("#split-scene").onclick = () => {
    try {
      const parts = splitScene(s, video?.currentTime ?? s.start);
      checkpoint();
      current.scenes.splice(selected, 1, ...parts);
      queueSave();
      render();
    } catch (e) {
      toast(e.message);
    }
  };
  $("#remove-scene").onclick = () => {
    checkpoint();
    current.scenes.splice(selected, 1);
    queueSave();
    render();
    toast("Scene removed. Undo restores it.");
  };
}
function highlightScene() {
  $$("[data-scene]").forEach((b) =>
    b.classList.toggle(
      "playing",
      playlist && Number(b.dataset.scene) === playIndex,
    ),
  );
}
function seekPreview(t) {
  const v = $("#preview");
  if (!v) return;
  if (v.readyState >= 1) v.currentTime = t;
  else
    v.addEventListener(
      "loadedmetadata",
      () => {
        v.currentTime = t;
      },
      { once: true },
    );
}
function showValidation() {
  const issues = validate(current);
  $("#validation-results").innerHTML =
    `<div class="issues">${issues.length ? issues.map((i) => `<div class="issue ${i.severity === "error" ? "error" : "info"}">${esc(i.message)}</div>`).join("") : '<div class="issue ok">✓ All scene ranges and recorded voice windows fit. This is a timeline check, not a model quality score.</div>'}</div>`;
}

function renderProjects() {
  const active = projects.filter((p) => !p.archived),
    archived = projects.filter((p) => p.archived);
  const rows = (list, isArchive = false) =>
    list
      .map(
        (p) =>
          `<div class="project-row"><div class="project-avatar">N</div><div><h3>${esc(p.name)}</h3><p class="small muted">${p.sourceKind === "reference" ? "Reference render" : "Local footage"} · ${p.scenes.length} scenes · ${duration(p).toFixed(1)} s</p></div><div class="actions">${isArchive ? `<button class="button small" data-restore="${esc(p.id)}">Restore</button>` : `<button class="button small" data-open="${esc(p.id)}">Open</button><button class="button small" data-duplicate="${esc(p.id)}">Duplicate</button><button class="button ghost small" data-archive="${esc(p.id)}">Archive</button>`}</div></div>`,
      )
      .join("");
  $("#main").innerHTML =
    `<div class="project-header"><div><div class="section-label">YOUR LIBRARY</div><h1>Projects</h1><p class="muted">Storyboards and footage are stored in this browser, on this device.</p></div><div class="actions"><button class="button" id="import-json">Import project JSON</button><button class="button primary" id="new-project">+ New project</button></div></div><div class="project-list">${rows(active)}</div>${archived.length ? `<h2 style="margin-top:28px">Archived <span class="small muted">${archived.length}</span></h2><div class="project-list">${rows(archived, true)}</div>` : ""}<p class="helper">Project JSON exports contain the edit plan. Video files remain local and must be relinked on another device.</p>`;
  $("#new-project").onclick = () => chooseVideo();
  $("#import-json").onclick = () => $("#project-file").click();
  $$("[data-open]").forEach(
    (b) =>
      (b.onclick = () =>
        setProject(projects.find((p) => p.id === b.dataset.open))),
  );
  $$("[data-duplicate]").forEach(
    (b) =>
      (b.onclick = async () => {
        await persist();
        const p = clone(projects.find((p) => p.id === b.dataset.duplicate));
        p.id = uid();
        p.name += " · Copy";
        p.createdAt = p.updatedAt = stamp();
        projects.push(p);
        await request("projects", "put", p);
        renderProjects();
        toast(
          "Project duplicated. Local footage is shared between these edit plans.",
        );
      }),
  );
  $$("[data-archive]").forEach(
    (b) =>
      (b.onclick = async () => {
        await persist();
        const p = projects.find((p) => p.id === b.dataset.archive);
        p.archived = true;
        if (current.id === p.id) current.archived = true;
        await request("projects", "put", p);
        if (current.id === p.id) {
          const next = projects.find((v) => !v.archived);
          if (next) {
            await setProject(next);
            view = "projects";
          } else {
            current = await referenceProject();
            projects.push(current);
            await setProject(current);
            view = "projects";
          }
        }
        render();
      }),
  );
  $$("[data-restore]").forEach(
    (b) =>
      (b.onclick = async () => {
        const p = projects.find((p) => p.id === b.dataset.restore);
        p.archived = false;
        await request("projects", "put", p);
        renderProjects();
      }),
  );
}
function artifact(index) {
  const s = current.scenes[selected] || current.scenes[0];
  return [
    {
      source:
        current.sourceKind === "reference" ? "saved render" : "local video",
      scene_count: current.scenes.length,
      source_duration: current.sourceDuration,
      note: "Automatic visual analysis requires the private backend.",
    },
    {
      director_brief: current.brief,
      story: current.scenes.map((s) => ({ scene: s.name, role: s.role })),
    },
    {
      narration: current.scenes.map((s) => ({
        scene: s.name,
        text: s.narration,
        status: s.voiceDirty ? "edited" : "saved",
      })),
    },
    {
      voice: "Recorded Mandarin narration in the reference output",
      synthesis: "Server-side TTS only",
      measured_windows: current.scenes.map((s) => ({
        scene: s.name,
        seconds: s.voiceDuration,
        regeneration_needed: s.voiceDirty,
      })),
    },
    {
      output_duration: duration(current),
      windows: current.scenes.map((s) => ({
        name: s.name,
        in: s.start,
        out: s.end,
      })),
      issues: validate(current),
    },
    {
      scene: s?.name,
      local_treatment: s?.effect,
      source_audio: "preserved",
      subtitle_export: "SRT",
    },
    {
      browser_export: "Canvas + MediaRecorder",
      server_export: "MoviePy + FFmpeg",
      input: "ordered scene ranges",
      output: "video + project JSON + subtitles",
    },
    {
      local_timeline_issues: validate(current),
      server_evaluation:
        "Requires a private processing run. No generated quality score is shown here.",
    },
  ][index];
}
function renderWorkflow() {
  const a = agents[agentIndex];
  $("#main").innerHTML =
    `<div class="project-header"><div><div class="section-label">EIGHT AGENTS / SHARED PROJECT STATE</div><h1>From footage to a finished story.</h1><p class="muted">Inspect each responsibility, its output contract and the current project artifact.</p></div><span class="tag gold">${current.sourceKind === "reference" ? "Recorded reference state" : "Local edit state"}</span></div><div class="diagram-wrap"><img class="diagram" src="assets/agent-workflow.svg" alt="Eight-agent workflow from Vision through Evaluation, with shared project state and bounded feedback."></div><div class="system-layout"><div class="agent-list">${agents.map((a, i) => `<button class="agent-button ${i === agentIndex ? "active" : ""}" data-agent="${i}"><span>${String(i + 1).padStart(2, "0")}</span><div><b>${a[0]}</b><small>${a[1]}</small></div></button>`).join("")}</div><section class="agent-detail"><span class="tag">${a[4]}</span><h2>${a[0]} Agent</h2><h3>${a[1]}</h3><p class="muted">${a[2]}</p><div class="field-label">OUTPUT CONTRACT</div><p>${a[3]}</p><div class="panel-bar"><span>Current project artifact</span><span class="tag">${agentIndex === 4 ? "LOCAL VALIDATION" : "INSPECTABLE STATE"}</span></div><pre class="artifact">${esc(JSON.stringify(artifact(agentIndex), null, 2))}</pre><p class="helper">The reference output was generated previously. Model inference and TTS run on a configured private backend; this view does not simulate agent execution.</p></section></div>`;
  $$("[data-agent]").forEach(
    (b) =>
      (b.onclick = () => {
        agentIndex = Number(b.dataset.agent);
        renderWorkflow();
      }),
  );
}
function renderSystem() {
  const maps = [
    ["System overview", "system-overview.svg"],
    ["Agent collaboration", "agent-workflow.svg"],
    ["Data boundaries", "data-boundaries.svg"],
  ];
  $("#main").innerHTML =
    `<div class="project-header"><div><div class="section-label">ARCHITECTURE / BUILT TO BE INSPECTED</div><h1>One system. Clear boundaries.</h1><p class="muted">A local workspace for human review, a private processing plane for generation.</p></div><a class="button" href="https://github.com/yejiasong1-ferrari/nesto-housing-director-studio/tree/main/system" target="_blank" rel="noopener">Explore source ↗</a></div><div class="map-tabs">${maps.map((a, i) => `<button class="button ${mapIndex === i ? "primary" : ""}" data-map="${i}">${a[0]}</button>`).join("")}</div><div class="diagram-wrap"><img class="diagram" src="assets/${maps[mapIndex][1]}" alt="${maps[mapIndex][0]} architecture diagram"></div><div class="system-notes"><section class="panel"><h3>01 / Interaction plane</h3><p class="muted">Import video, edit the storyboard, revise narration, validate timing and export on this device. Browser media is not uploaded automatically.</p></section><section class="panel"><h3>02 / Processing plane</h3><p class="muted">FastAPI, specialized agents and a worker coordinate model calls, TTS, media rendering and bounded review. Use the included Next.js Studio for server jobs.</p></section><section class="panel"><h3>03 / Artifact plane</h3><p class="muted">Typed project state links visual evidence, narrative choices, measured speech and the final timeline. Runtime files and credentials stay outside the public repository.</p></section></div><section class="panel" style="margin-top:20px"><div class="panel-bar"><h2>System walkthrough</h2><span class="tag">RECORDED ARTIFACT</span></div><video controls playsinline preload="none" poster="assets/reference-poster.jpg" src="assets/nesto-system-overview.mp4" style="width:100%;max-height:480px"></video></section>`;
  $$("[data-map]").forEach(
    (b) =>
      (b.onclick = () => {
        mapIndex = Number(b.dataset.map);
        renderSystem();
      }),
  );
}
function renderSettings() {
  $("#main").innerHTML =
    `<div class="project-header"><div><div class="section-label">CONNECTIONS / PRIVACY</div><h1>Your footage. Your processing.</h1><p class="muted">Use local editing immediately. Configure model providers only on your private server.</p></div></div><div class="settings-layout"><section class="panel"><h2>Private processing service</h2><p class="muted">Connect to your own FastAPI service to check availability. This page never asks for provider keys or stores session tokens.</p><label class="field-label" for="backend-url">BACKEND BASE URL</label><input class="field" id="backend-url" type="url" placeholder="http://127.0.0.1:8000" value="${esc(endpoint)}"><p class="helper">URL only. Credentials, query strings and fragments are rejected. The address is kept in memory for this session.</p><div class="actions"><button class="button" id="check-backend">Check health</button><a class="button primary" href="http://127.0.0.1:3001" target="_blank" rel="noopener">Open private Studio ↗</a></div><p class="service-status" id="service-status">${esc(endpointResult || "Not connected · local editing is available")}</p><p class="helper">A healthy API does not confirm provider credentials or a running worker. The private Studio handles authenticated generation jobs.</p><a href="https://github.com/yejiasong1-ferrari/nesto-housing-director-studio/blob/main/docs/LOCAL_SETUP.md" target="_blank" rel="noopener">Backend, provider and worker setup ↗</a></section><section class="panel"><h2>Data stays where it belongs</h2><div class="issues"><div class="issue ok">Local video: stored as a browser Blob on this device.</div><div class="issue ok">Project exports: allowlisted storyboard fields only; no tokens, paths or remote media URLs.</div><div class="issue info">API credentials: server environment variables only. Never enter them into project text or a repository file.</div></div><p class="muted">Browser storage is tied to this origin and can be cleared by the browser. Export project JSON and retain your source footage as a backup.</p><a href="https://github.com/yejiasong1-ferrari/nesto-housing-director-studio/blob/main/docs/SECURITY.md" target="_blank" rel="noopener">Publication and privacy controls ↗</a></section></div><div class="diagram-wrap" style="margin-top:20px"><img class="diagram" src="assets/data-boundaries.svg" alt="Public code, browser-local files and private server data are kept in separate boundaries."></div>`;
  $("#check-backend").onclick = async () => {
    const input = $("#backend-url").value.trim();
    let url;
    try {
      url = new URL(input);
      if (
        !["https:", "http:"].includes(url.protocol) ||
        url.username ||
        url.password ||
        url.search ||
        url.hash
      )
        throw new Error();
    } catch {
      toast(
        "Enter an HTTP(S) base URL without credentials, query strings or fragments.",
      );
      return;
    }
    endpoint = url.href.replace(/\/$/, "");
    $("#service-status").textContent = "Checking service…";
    try {
      const r = await fetch(endpoint + "/health", {
        credentials: "omit",
        cache: "no-store",
        signal: AbortSignal.timeout(6000),
      });
      endpointResult = r.ok
        ? "API reachable · verify providers and worker in your private Studio."
        : `API returned HTTP ${r.status}.`;
    } catch {
      endpointResult =
        "Could not reach the service. Check the address, HTTPS/CORS and that your backend is running.";
    }
    $("#service-status").textContent = endpointResult;
  };
}

let relinking = false;
function chooseVideo(relink = false) {
  relinking = relink;
  $("#video-file").value = "";
  $("#video-file").click();
}
$("#video-file").onchange = async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  if (!file.type.startsWith("video/")) {
    toast("Choose a video file.");
    return;
  }
  const temp = URL.createObjectURL(file),
    v = document.createElement("video");
  v.preload = "metadata";
  v.src = temp;
  try {
    await new Promise((resolve, reject) => {
      v.onloadedmetadata = resolve;
      v.onerror = () =>
        reject(
          new Error(
            "This browser cannot read that video. Try an MP4 with H.264 video.",
          ),
        );
    });
    if (!Number.isFinite(v.duration) || v.duration <= 0 || v.duration > 86400)
      throw new Error("Choose a video shorter than 24 hours.");
    const key = uid();
    if (!db)
      throw new Error(
        "Device storage is unavailable. Enable browser storage before importing video.",
      );
    await request("media", "put", { id: key, blob: file });
    if (relinking) {
      if (current.scenes.some((s) => s.end > v.duration + 0.06))
        throw new Error(
          "The replacement video is shorter than this storyboard. Choose the original source.",
        );
      checkpoint();
      current.mediaKey = key;
      current.sourceKind = "local";
      current.sourceDuration = v.duration;
      await setProject(current);
      toast("Source video relinked.");
    } else {
      const count = Math.min(7, Math.max(1, Math.ceil(v.duration / 8)));
      const p = sanitizeProject({
        name: file.name.replace(/\.[^.]+$/, "").slice(0, 80),
        brief: "",
        sourceKind: "local",
        sourceDuration: v.duration,
        scenes: Array.from({ length: count }, (_, i) => ({
          name: `Scene ${i + 1}`,
          role: i === 0 ? "HERO" : "SUPPORT",
          start: +((i * v.duration) / count).toFixed(3),
          end:
            i === count - 1
              ? v.duration
              : +(((i + 1) * v.duration) / count).toFixed(3),
          narration: "",
          effect: "none",
        })),
      });
      p.id = uid();
      p.mediaKey = key;
      await setProject(p);
      toast(
        "Video imported locally. Equal scene windows are ready for your review.",
      );
    }
  } catch (err) {
    toast(err.message || "Import failed. The device may be out of storage.");
  } finally {
    URL.revokeObjectURL(temp);
    v.removeAttribute("src");
    v.load();
  }
};
$("#project-file").onchange = async (e) => {
  const file = e.target.files[0];
  e.target.value = "";
  if (!file) return;
  try {
    if (file.size > 2 * 1024 * 1024)
      throw new Error("Project JSON must be smaller than 2 MB.");
    const p = sanitizeProject(JSON.parse(await file.text()));
    p.id = uid();
    await setProject(p);
    toast(
      p.sourceKind === "reference"
        ? "Reference storyboard imported."
        : "Project imported. Relink its source video to preview.",
    );
  } catch (err) {
    toast(err.message || "Could not read that project file.");
  }
};

function exportModal() {
  modal(
    "Export your production",
    `<p class="muted">${esc(current.name)} · ${current.scenes.length} scenes · ${duration(current).toFixed(2)} seconds</p><button class="export-option" id="export-json"><b>Project JSON ↗</b><span>Portable storyboard, narration, timings and edit decisions.</span></button><button class="export-option" id="export-srt"><b>Subtitles / SRT ↗</b><span>Narration aligned to the edited scene order.</span></button><button class="export-option" id="export-video" ${sourceUrl && current.scenes.length && window.MediaRecorder && HTMLCanvasElement.prototype.captureStream ? "" : "disabled"}><b>Render video on this device ↗</b><span>Actual sequence export with original audio and selected framing.</span></button><label class="small"><input type="checkbox" id="burn-captions"> Add narration text as captions during local export</label><p class="helper">Rendering takes roughly the sequence duration. Text edits do not synthesize new speech. The reference video already contains recorded narration and subtitles.</p>`,
  );
  $("#export-json").onclick = () => {
    download(
      filename() + ".nesto.json",
      JSON.stringify(exportProject(current), null, 2),
      "application/json",
    );
    toast("Project JSON exported.");
  };
  $("#export-srt").onclick = () => {
    download(filename() + ".srt", toSrt(current), "application/x-subrip");
    toast("Subtitles exported.");
  };
  $("#export-video").onclick = () => renderVideo($("#burn-captions").checked);
}
async function renderVideo(captions) {
  const errors = validate(current).filter((i) => i.severity === "error");
  if (errors.length) {
    toast("Fix invalid scene ranges before rendering.");
    return;
  }
  const project = clone(current),
    media = sourceUrl;
  let recorder,
    stream,
    audioContext,
    v,
    raf,
    aborted = false,
    outputUrl = "";
  const cancellation = new AbortController();
  const waitMedia = (event, ready, start = () => {}) => {
    if (cancellation.signal.aborted)
      return Promise.reject(
        new Error("Rendering cancelled. Your project is still saved."),
      );
    if (ready()) return Promise.resolve();
    return new Promise((resolve, reject) => {
      const finish = (error) => {
        clearTimeout(timer);
        v.removeEventListener(event, onReady);
        v.removeEventListener("error", onError);
        cancellation.signal.removeEventListener("abort", onCancel);
        error ? reject(error) : resolve();
      };
      const onReady = () => finish();
      const onError = () =>
        finish(new Error("Could not read the source video. Try an H.264 MP4."));
      const onCancel = () =>
        finish(new Error("Rendering cancelled. Your project is still saved."));
      const timer = setTimeout(
        () =>
          finish(
            new Error("Media preparation timed out. Try a smaller local MP4."),
          ),
        15000,
      );
      v.addEventListener(event, onReady, { once: true });
      v.addEventListener("error", onError, { once: true });
      cancellation.signal.addEventListener("abort", onCancel, { once: true });
      start();
    });
  };
  renderActive = true;
  modal(
    "Render video",
    `<p>Rendering ${esc(project.name)} on this device.</p><progress class="render-progress" id="render-progress" max="${duration(project)}" value="0"></progress><p id="render-state" class="muted">Preparing media…</p><p class="helper">Keep this tab visible until rendering finishes. No video is uploaded.</p><div id="render-output"></div><div class="modal-actions"><button class="button" id="cancel-render">Cancel rendering</button></div>`,
  );
  $("#cancel-render").onclick = () => {
    aborted = true;
    cancellation.abort();
    if (recorder?.state === "recording") recorder.stop();
  };
  try {
    v = document.createElement("video");
    v.src = media;
    v.playsInline = true;
    v.preload = "auto";
    v.crossOrigin = "anonymous";
    v.style.cssText =
      "position:fixed;width:1px;height:1px;opacity:0;pointer-events:none";
    document.body.append(v);
    const ctxClass = window.AudioContext || window.webkitAudioContext;
    audioContext = ctxClass ? new ctxClass() : null;
    if (audioContext) await audioContext.resume();
    await waitMedia("loadedmetadata", () => v.readyState >= 1);
    if (project.scenes.some((scene) => scene.end > v.duration + 0.06))
      throw new Error(
        "A scene exceeds the actual source video. Relink the original footage or trim that scene.",
      );
    const canvas = document.createElement("canvas");
    canvas.width = Math.min(1280, v.videoWidth || 1280);
    canvas.height =
      Math.round(
        (canvas.width * (v.videoHeight || 720)) / (v.videoWidth || 1280) / 2,
      ) * 2;
    const ctx = canvas.getContext("2d");
    stream = canvas.captureStream(30);
    if (audioContext) {
      const source = audioContext.createMediaElementSource(v),
        dest = audioContext.createMediaStreamDestination();
      source.connect(dest);
      for (const track of dest.stream.getAudioTracks()) stream.addTrack(track);
    }
    const mime = [
      "video/webm;codecs=vp8,opus",
      "video/webm;codecs=vp9,opus",
      "video/mp4",
      "video/webm",
    ].find((t) => MediaRecorder.isTypeSupported(t));
    if (!mime)
      throw new Error(
        "This browser does not support local video recording. Export JSON and SRT instead.",
      );
    recorder = new MediaRecorder(stream, {
      mimeType: mime,
      videoBitsPerSecond: 4000000,
    });
    const chunks = [];
    recorder.ondataavailable = (e) => {
      if (e.data.size) chunks.push(e.data);
    };
    const stopped = new Promise((resolve, reject) => {
      recorder.onstop = resolve;
      recorder.onerror = (e) =>
        reject(e.error || new Error("Video recording failed."));
    });
    let elapsed = 0,
      started = false;
    const seek = (t) =>
      waitMedia(
        "seeked",
        () => Math.abs(v.currentTime - t) < 0.002 && v.readyState >= 2,
        () => {
          v.currentTime = t;
        },
      );
    for (const scene of project.scenes) {
      if (aborted) break;
      v.pause();
      if (started && recorder.state === "recording") recorder.pause();
      await seek(scene.start);
      const length = scene.end - scene.start;
      const draw = () => {
        const p = Math.max(
          0,
          Math.min(1, (v.currentTime - scene.start) / length),
        );
        const zoom = scene.effect === "none" ? 1 : 1 + 0.06 * p;
        const sw = v.videoWidth / zoom,
          sh = v.videoHeight / zoom;
        const sx =
          scene.effect === "ken_burns"
            ? (v.videoWidth - sw) * p
            : (v.videoWidth - sw) / 2;
        ctx.drawImage(
          v,
          sx,
          (v.videoHeight - sh) / 2,
          sw,
          sh,
          0,
          0,
          canvas.width,
          canvas.height,
        );
        if (captions && scene.narration) {
          ctx.font = `500 ${Math.round(canvas.width / 38)}px sans-serif`;
          ctx.textAlign = "center";
          const chars = [...scene.narration],
            lines = [];
          let line = "";
          for (const char of chars) {
            if (ctx.measureText(line + char).width > canvas.width * 0.84) {
              lines.push(line);
              line = "";
            }
            line += char;
          }
          if (line) lines.push(line);
          const page = Math.min(
            Math.ceil(lines.length / 3) - 1,
            Math.floor(p * Math.ceil(lines.length / 3)),
          );
          const visible = lines.slice(page * 3, page * 3 + 3),
            lh = canvas.width / 29,
            base = canvas.height - canvas.height * 0.08;
          ctx.fillStyle = "rgba(0,0,0,.72)";
          ctx.fillRect(
            canvas.width * 0.05,
            base - visible.length * lh,
            canvas.width * 0.9,
            visible.length * lh + lh * 0.35,
          );
          ctx.fillStyle = "white";
          visible.forEach((l, i) =>
            ctx.fillText(
              l,
              canvas.width / 2,
              base - (visible.length - 1 - i) * lh,
            ),
          );
        }
        $("#render-progress").value =
          elapsed + Math.min(length, Math.max(0, v.currentTime - scene.start));
      };
      draw();
      if (!started) {
        recorder.start(300);
        started = true;
      } else if (recorder.state === "paused") recorder.resume();
      await v.play();
      $("#render-state").textContent =
        `Scene ${project.scenes.indexOf(scene) + 1} / ${project.scenes.length} · ${scene.name}`;
      await new Promise((resolve) => {
        const tick = () => {
          draw();
          if (aborted || v.currentTime >= scene.end - 0.025 || v.ended) {
            resolve();
            return;
          }
          raf = requestAnimationFrame(tick);
        };
        raf = requestAnimationFrame(tick);
      });
      elapsed += length;
    }
    v.pause();
    if (recorder.state !== "inactive") recorder.stop();
    await stopped;
    if (aborted)
      throw new Error("Rendering cancelled. Your project is still saved.");
    const blob = new Blob(chunks, { type: mime });
    outputUrl = URL.createObjectURL(blob);
    const ext = mime.startsWith("video/mp4") ? "mp4" : "webm";
    $("#render-progress").value = duration(project);
    $("#render-state").textContent =
      `Render complete · ${(blob.size / 1024 / 1024).toFixed(1)} MB · ${ext.toUpperCase()}`;
    $("#render-output").innerHTML =
      `<video class="render-result" controls src="${outputUrl}"></video><a class="button primary" id="download-render" href="${outputUrl}" download="${esc(filename())}.${ext}">Download video ↗</a>`;
    $("#cancel-render").textContent = "Done";
    $("#cancel-render").onclick = () => {
      closeModal();
      setTimeout(() => URL.revokeObjectURL(outputUrl), 60000);
    };
  } catch (e) {
    $("#render-state").textContent =
      e.message || "Rendering failed. Export JSON and SRT instead.";
    $("#cancel-render").textContent = "Close";
    $("#cancel-render").onclick = closeModal;
  } finally {
    cancelAnimationFrame(raf);
    if (recorder && recorder.state !== "inactive") recorder.stop();
    v?.pause();
    v?.remove();
    stream?.getTracks().forEach((t) => t.stop());
    if (audioContext) await audioContext.close();
    renderActive = false;
  }
}

async function referenceProject() {
  const r = await fetch("reference-project.json");
  if (!r.ok) throw new Error("Reference project could not be loaded.");
  const p = sanitizeProject(await r.json());
  p.id = uid();
  return p;
}
$$(".nav-button").forEach(
  (b) =>
    (b.onclick = async () => {
      if (renderActive) return;
      await persist();
      playlist = false;
      view = b.dataset.view;
      render();
    }),
);
$("#import-button").onclick = () => chooseVideo();
$("#export-button").onclick = exportModal;
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden" && current) persist();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeModal();
});
try {
  try {
    await openDB();
    projects = await request("projects", "getAll");
  } catch {
    persistent = false;
    toast(
      "Device storage is unavailable. You can edit this session and export project JSON.",
    );
  }
  let last;
  try {
    last = localStorage.getItem("nesto-current");
  } catch {}
  const project =
    projects.find((p) => p.id === last && !p.archived) ||
    projects.find((p) => !p.archived) ||
    (await referenceProject());
  await setProject(project);
  const requestedView = new URL(location.href).searchParams.get("view");
  if (["workflow", "system", "settings", "projects"].includes(requestedView)) {
    view = requestedView;
    render();
  }
} catch (e) {
  $("#main").innerHTML =
    `<section class="panel"><h1>Workspace could not start</h1><p>${esc(e.message)}</p><p>Serve this folder over HTTP rather than opening the HTML file directly.</p></section>`;
}
