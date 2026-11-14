"""Property-scoped workspace paths for AI Director agent outputs.

Each property (identified by its source video) gets its own folder under
``storage/properties/<slug>/`` with subdirectories per agent:

    storage/properties/412-3rd-st-ne-washington-dc-20002/
        property.json
        vision/   vision_knowledge_base.json, results.json, frames/, keyframes/
        planner/  planner_output.json, planner_output_full.json
        script/   script_output.json (canonical = timeline-aligned after unify),
                  script_draft.json (optional pre-merge scene-level draft)
        timeline/ timeline_output.json, timeline_script.json (same narration as script_output)
        voice/    voice_plan.json, voice_execution.json
        audio/    synthesized segment audio files
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from backend.paths import REPO_ROOT

PROJECT_ROOT = REPO_ROOT
STORAGE_ROOT = PROJECT_ROOT / "storage" / "properties"

DEFAULT_VIDEO_PATH = PROJECT_ROOT / "412 3rd St NE, Washington, DC 20002.mov"


def slug_from_name(name: str) -> str:
    """Convert a video filename or address into a filesystem-safe slug."""
    slug = Path(name).stem if "." in name else name
    slug = slug.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-") or "unknown-property"


class PropertyWorkspace:
    """All agent I/O paths for one property listing."""

    def __init__(self, video_path: str | Path | None = None) -> None:
        self.video_path = Path(video_path or DEFAULT_VIDEO_PATH).resolve()
        self.slug = slug_from_name(self.video_path.name)
        self.root = STORAGE_ROOT / self.slug
        self.vision_dir = self.root / "vision"
        self.planner_dir = self.root / "planner"
        self.script_dir = self.root / "script"
        self.voice_dir = self.root / "voice"
        self.audio_dir = self.root / "audio"
        self.timeline_dir = self.root / "timeline"
        self.editing_dir = self.root / "editing"
        self.output_dir = self.root / "output"

    def ensure_dirs(self) -> None:
        """Create all property subdirectories."""
        for d in (
            self.root,
            self.vision_dir,
            self.planner_dir,
            self.script_dir,
            self.voice_dir,
            self.audio_dir,
            self.timeline_dir,
            self.editing_dir,
            self.output_dir,
            self.evaluation_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)
        self.vision_dir.joinpath("frames").mkdir(exist_ok=True)
        self.vision_dir.joinpath("keyframes").mkdir(exist_ok=True)

    @property
    def metadata_path(self) -> Path:
        return self.root / "property.json"

    @property
    def vkb_path(self) -> Path:
        return self.vision_dir / "vision_knowledge_base.json"

    @property
    def results_path(self) -> Path:
        return self.vision_dir / "results.json"

    @property
    def frames_dir(self) -> Path:
        return self.vision_dir / "frames"

    @property
    def keyframes_dir(self) -> Path:
        return self.vision_dir / "keyframes"

    @property
    def planner_output_path(self) -> Path:
        return self.planner_dir / "planner_output.json"

    @property
    def planner_output_full_path(self) -> Path:
        return self.planner_dir / "planner_output_full.json"

    @property
    def script_output_path(self) -> Path:
        """Canonical script — overwritten by timeline-aligned narration after unify."""
        return self.script_dir / "script_output.json"

    @property
    def script_draft_path(self) -> Path:
        """Pre-merge scene-level Script Agent draft (audit only)."""
        return self.script_dir / "script_draft.json"

    @property
    def voice_plan_path(self) -> Path:
        return self.voice_dir / "voice_plan.json"

    @property
    def voice_execution_path(self) -> Path:
        return self.voice_dir / "voice_execution.json"

    @property
    def timeline_output_path(self) -> Path:
        return self.timeline_dir / "timeline_output.json"

    @property
    def editing_plan_path(self) -> Path:
        return self.editing_dir / "editing_plan.json"

    @property
    def render_result_path(self) -> Path:
        return self.output_dir / "render_result.json"

    @property
    def final_video_path(self) -> Path:
        return self.output_dir / "final_video.mp4"

    @property
    def timeline_script_path(self) -> Path:
        """Timeline-aligned narration segments (one per timeline segment, merged groups re-narrated)."""
        return self.timeline_dir / "timeline_script.json"

    @property
    def evaluation_dir(self) -> Path:
        return self.root / "evaluation"

    @property
    def evaluation_result_path(self) -> Path:
        return self.evaluation_dir / "evaluation_result.json"

    @property
    def feedback_applied_path(self) -> Path:
        return self.evaluation_dir / "feedback_applied.json"

    @property
    def final_video_v2_path(self) -> Path:
        """Post-evaluation final cut."""
        return self.output_dir / "final_video_v2.mp4"

    def write_metadata(self, user_prompt: str = "", extra: dict | None = None) -> None:
        """Persist property metadata for traceability."""
        self.ensure_dirs()
        metadata = {
            "slug": self.slug,
            "video_path": str(self.video_path),
            "video_name": self.video_path.name,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "user_prompt": user_prompt,
            "paths": {
                "vision": str(self.vision_dir),
                "planner": str(self.planner_dir),
                "script": str(self.script_dir),
                "voice": str(self.voice_dir),
                "audio": str(self.audio_dir),
                "timeline": str(self.timeline_dir),
            },
        }
        if extra:
            metadata.update(extra)
        self.metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    def summary(self) -> str:
        return (
            f"Property: {self.slug}\n"
            f"  Video:   {self.video_path}\n"
            f"  Root:    {self.root}\n"
            f"  Vision:  {self.vkb_path}\n"
            f"  Planner: {self.planner_output_path}\n"
            f"  Script:  {self.script_output_path}\n"
            f"  Voice:   {self.voice_plan_path}\n"
            f"  Audio:   {self.audio_dir}\n"
            f"  Timeline:{self.timeline_output_path}"
        )


def resolve_workspace(video_path: str | Path | None = None) -> PropertyWorkspace:
    """Return a workspace for the given video, creating directories."""
    ws = PropertyWorkspace(video_path)
    ws.ensure_dirs()
    return ws


def resolve_workspace_by_slug(
    slug: str,
    video_path: str | Path | None = None,
) -> PropertyWorkspace:
    """Bind a workspace to ``storage/properties/<slug>/`` regardless of video filename.

    Needed when hydrated workspaces use ``source.mp4`` (slug would otherwise become
    ``source``) or when the API route slug is the source of truth.
    """
    root = STORAGE_ROOT / slug
    vp: Path | None = Path(video_path) if video_path else None
    if vp is None or not vp.exists():
        meta_path = root / "property.json"
        video_name = ""
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                video_name = str(meta.get("video_name") or "")
                meta_vp = meta.get("video_path")
                if meta_vp and Path(str(meta_vp)).exists():
                    vp = Path(str(meta_vp))
            except Exception:  # noqa: BLE001
                pass
        if vp is None or not vp.exists():
            for candidate in (
                root / video_name if video_name else None,
                root / "source.mp4",
                root / "output" / "final_video_v2.mp4",
            ):
                if candidate and candidate.exists():
                    vp = candidate
                    break
        if vp is None:
            vp = root / (video_name or "source.mp4")

    ws = PropertyWorkspace.__new__(PropertyWorkspace)
    ws.video_path = vp.resolve() if vp.exists() else vp
    ws.slug = slug
    ws.root = root
    ws.vision_dir = ws.root / "vision"
    ws.planner_dir = ws.root / "planner"
    ws.script_dir = ws.root / "script"
    ws.voice_dir = ws.root / "voice"
    ws.audio_dir = ws.root / "audio"
    ws.timeline_dir = ws.root / "timeline"
    ws.editing_dir = ws.root / "editing"
    ws.output_dir = ws.root / "output"
    ws.ensure_dirs()
    return ws
