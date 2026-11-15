import test from "node:test";
import assert from "node:assert/strict";
import {
  sanitizeProject,
  exportProject,
  toSrt,
  splitScene,
  validate,
  sceneAt,
  duration,
} from "./workbench-core.mjs";
const fixture = () => ({
  name: "Test",
  sourceDuration: 20,
  sourceKind: "local",
  scenes: [
    { id: "a", name: "A", start: 10, end: 13, narration: "First" },
    { id: "b", name: "B", start: 0, end: 2, narration: "Second" },
  ],
});
test("project import retains edit fields and discards credentials, paths and remote media", () => {
  const p = sanitizeProject({
    ...fixture(),
    apiKey: "private-value",
    url: "https://untrusted.test/clip.mp4",
    mediaKey: "external-id",
    path: "/private/location",
    scenes: [{ ...fixture().scenes[0], token: "private-value" }],
  });
  const out = exportProject(p);
  assert.equal(p.mediaKey, null);
  assert.equal(out.scenes[0].name, "A");
  assert.equal(out.sourceKind, "local");
  assert.equal(JSON.stringify(out).includes("private-value"), false);
  assert.equal("url" in out, false);
  assert.equal("id" in out, false);
  assert.equal("mediaKey" in out, false);
});
test("invalid scene ranges and oversized projects are rejected", () => {
  for (const [start, end] of [
    [-1, 3],
    [3, 3],
    [6, 2],
    [0, 21],
    [NaN, 3],
  ])
    assert.throws(() =>
      sanitizeProject({ ...fixture(), scenes: [{ start, end }] }),
    );
  assert.throws(() =>
    sanitizeProject({
      ...fixture(),
      scenes: Array(201).fill(fixture().scenes[0]),
    }),
  );
});
test("SRT follows output order rather than source timestamps", () => {
  const p = sanitizeProject(fixture());
  assert.equal(
    toSrt(p),
    "1\n00:00:00,000 --> 00:00:03,000\nFirst\n\n2\n00:00:03,000 --> 00:00:05,000\nSecond\n",
  );
  assert.equal(duration(p), 5);
});
test("split preserves source coverage without duplicating recorded narration", () => {
  const s = { ...fixture().scenes[0], voiceDuration: 2.5 };
  const [a, b] = splitScene(s, 11);
  assert.equal(a.end, b.start);
  assert.equal(a.start, 10);
  assert.equal(b.end, 13);
  assert.equal(b.narration, "");
  assert.equal(a.voiceDirty, true);
  assert.equal(a.voiceDuration, null);
  assert.throws(() => splitScene(s, 10.01));
});
test("timeline validation reports overlong audio and edited voice honestly", () => {
  const p = sanitizeProject(fixture());
  p.scenes[0].voiceDuration = 4;
  p.scenes[1].voiceDirty = true;
  const issues = validate(p);
  assert.equal(issues.length, 2);
  assert.ok(issues[0].message.includes("exceeds"));
  assert.ok(issues[1].message.includes("not been regenerated"));
});
test("output seek resolves reordered source clips at boundaries", () => {
  const p = sanitizeProject(fixture());
  assert.deepEqual(sceneAt(p, 2), { index: 0, sourceTime: 12 });
  assert.deepEqual(sceneAt(p, 3), { index: 1, sourceTime: 0 });
  assert.deepEqual(sceneAt(p, 99), { index: 1, sourceTime: 2 });
});

test("reference imports cannot extend beyond the actual bundled video", () => {
  assert.throws(() =>
    sanitizeProject({
      ...fixture(),
      sourceKind: "reference",
      sourceDuration: 999,
      scenes: [{ start: 50, end: 99 }],
    }),
  );
});
