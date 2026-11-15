export const VERSION = 2;
export const clamp = (n, lo, hi) => Math.min(hi, Math.max(lo, n));
export const duration = (p) =>
  p.scenes.reduce((sum, s) => sum + Math.max(0, s.end - s.start), 0);
export function timecode(seconds, milliseconds = false) {
  const n = Math.max(0, Math.round(Number(seconds || 0) * 1000));
  const h = Math.floor(n / 3600000),
    m = Math.floor(n / 60000) % 60,
    s = Math.floor(n / 1000) % 60;
  const base = [h, m, s].map((v) => String(v).padStart(2, "0")).join(":");
  return milliseconds ? `${base},${String(n % 1000).padStart(3, "0")}` : base;
}
export function toSrt(project) {
  let cursor = 0,
    index = 1;
  const blocks = [];
  for (const scene of project.scenes) {
    const end = cursor + Math.max(0, scene.end - scene.start);
    const text = scene.narration.trim();
    if (text && end > cursor)
      blocks.push(
        `${index++}\n${timecode(cursor, true)} --> ${timecode(end, true)}\n${text}`,
      );
    cursor = end;
  }
  return blocks.join("\n\n") + "\n";
}
export function validate(project) {
  const issues = [];
  if (!project.scenes.length)
    issues.push({
      severity: "info",
      message: "Import a video and create a storyboard to start.",
    });
  project.scenes.forEach((s, i) => {
    if (
      !Number.isFinite(s.start) ||
      !Number.isFinite(s.end) ||
      s.start < 0 ||
      s.end <= s.start
    )
      issues.push({
        severity: "error",
        scene: s.id,
        message: `Scene ${i + 1}: end time must be later than start time.`,
      });
    if (s.end > project.sourceDuration + 0.06)
      issues.push({
        severity: "error",
        scene: s.id,
        message: `Scene ${i + 1}: range exceeds the source video.`,
      });
    if (s.voiceDuration != null && s.voiceDuration > s.end - s.start + 0.05)
      issues.push({
        severity: "warning",
        scene: s.id,
        message: `Scene ${i + 1}: recorded voice exceeds the scene window.`,
      });
    if (s.voiceDirty)
      issues.push({
        severity: "warning",
        scene: s.id,
        message: `Scene ${i + 1}: narration was edited; the recorded voice has not been regenerated.`,
      });
  });
  return issues;
}
export function sanitizeProject(input) {
  if (!input || typeof input !== "object" || !Array.isArray(input.scenes))
    throw new Error("Choose a Nesto project JSON file.");
  if (input.scenes.length > 200)
    throw new Error("A project can contain up to 200 scenes.");
  // A reference project always refers to the bundled, measured source asset.
  const sourceDuration =
    input.sourceKind === "reference" ? 55.032 : Number(input.sourceDuration);
  if (
    !Number.isFinite(sourceDuration) ||
    sourceDuration <= 0 ||
    sourceDuration > 86400
  )
    throw new Error("The project has an invalid video duration.");
  const scenes = input.scenes.map((s, i) => {
    const start = Number(s.start),
      end = Number(s.end);
    if (
      !Number.isFinite(start) ||
      !Number.isFinite(end) ||
      start < 0 ||
      end <= start ||
      end > sourceDuration + 0.06
    )
      throw new Error(`Scene ${i + 1} has an invalid range.`);
    return {
      id: `scene-${i + 1}`,
      name: String(s.name || `Scene ${i + 1}`).slice(0, 80),
      role: ["HERO", "SUPPORT", "TRANSITION"].includes(s.role)
        ? s.role
        : "SUPPORT",
      start,
      end,
      narration: String(s.narration || "").slice(0, 4000),
      voiceDuration:
        Number.isFinite(s.voiceDuration) && s.voiceDuration >= 0
          ? s.voiceDuration
          : null,
      voiceDirty: Boolean(s.voiceDirty),
      effect: ["none", "slow_zoom", "ken_burns"].includes(s.effect)
        ? s.effect
        : "none",
    };
  });
  // Accept a known bundled asset or a local file to relink. Imported URLs,
  // credentials, filesystem paths, and arbitrary properties are not retained.
  return {
    version: VERSION,
    id: `project-${Date.now()}`,
    name: String(input.name || "Imported project").slice(0, 80),
    brief: String(input.brief || "").slice(0, 4000),
    sourceKind: input.sourceKind === "reference" ? "reference" : "local",
    sourceDuration,
    mediaKey: null,
    scenes,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    archived: false,
  };
}
export function exportProject(project) {
  const clean = sanitizeProject(project);
  delete clean.id;
  delete clean.mediaKey;
  delete clean.createdAt;
  delete clean.updatedAt;
  delete clean.archived;
  return { ...clean, format: "nesto-project", version: VERSION };
}
export function splitScene(scene, at) {
  if (at <= scene.start + 0.1 || at >= scene.end - 0.1)
    throw new Error(
      "Move the playhead inside the selected scene before splitting.",
    );
  return [
    {
      ...scene,
      end: at,
      voiceDuration: null,
      voiceDirty: Boolean(scene.narration),
    },
    {
      ...scene,
      id: `${scene.id}-split-${Date.now()}`,
      name: `${scene.name} · B`,
      start: at,
      narration: "",
      voiceDuration: null,
      voiceDirty: false,
    },
  ];
}
export function sceneAt(project, outputTime) {
  let cursor = 0;
  for (let index = 0; index < project.scenes.length; index++) {
    const scene = project.scenes[index],
      length = scene.end - scene.start;
    if (outputTime < cursor + length || index === project.scenes.length - 1)
      return {
        index,
        sourceTime: scene.start + clamp(outputTime - cursor, 0, length),
      };
    cursor += length;
  }
  return null;
}
