"""Normalize walkthrough videos for AI Vision (cost + upload friendly).

Turns arbitrary phone/camera uploads into a consistent AI Processing Version:
MP4 / H.264 / ≤1280×720 / ≤30fps / AAC — without upscaling small sources.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

MAX_DURATION_SEC = 5 * 60  # 5 minutes
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
MAX_WIDTH = 1280
MAX_HEIGHT = 720
TARGET_FPS = 30
AUDIO_BITRATE = "128k"


@dataclass
class VideoProbe:
    path: Path
    duration: float
    width: int
    height: int
    size_bytes: int
    video_codec: str
    audio_codec: str
    container: str

    @property
    def size_mb(self) -> float:
        return self.size_bytes / (1024 * 1024)


class VideoTooLongError(ValueError):
    """Raised when source duration exceeds the product limit."""


class VideoTooLargeError(ValueError):
    """Raised when source file exceeds the upload size limit."""


def _ffprobe_json(path: Path) -> dict[str, Any]:
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path}: {result.stderr[-400:]}")
    return json.loads(result.stdout or "{}")


def probe_video(path: Path) -> VideoProbe:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(str(path))
    data = _ffprobe_json(path)
    fmt = data.get("format") or {}
    duration = float(fmt.get("duration") or 0.0)
    size_bytes = int(fmt.get("size") or path.stat().st_size)
    container = str(fmt.get("format_name") or path.suffix.lstrip(".")).lower()

    width = height = 0
    video_codec = ""
    audio_codec = ""
    for stream in data.get("streams") or []:
        if stream.get("codec_type") == "video" and not width:
            width = int(stream.get("width") or 0)
            height = int(stream.get("height") or 0)
            video_codec = str(stream.get("codec_name") or "").lower()
        elif stream.get("codec_type") == "audio" and not audio_codec:
            audio_codec = str(stream.get("codec_name") or "").lower()

    return VideoProbe(
        path=path,
        duration=duration,
        width=width,
        height=height,
        size_bytes=size_bytes,
        video_codec=video_codec,
        audio_codec=audio_codec,
        container=container,
    )


def _choose_crf(size_bytes: int) -> int:
    if size_bytes > 50 * 1024 * 1024:
        return 26
    if size_bytes > 10 * 1024 * 1024:
        return 23
    return 23  # small files: light unify encode when needed


def _max_video_bitrate(duration: float) -> Optional[str]:
    """Duration-based bitrate ceiling (helps long walkthroughs stay small)."""
    if duration <= 0:
        return None
    if duration < 60:
        return "3M"
    if duration <= 180:
        return "2M"
    return "1500k"


def needs_normalize(probe: VideoProbe) -> bool:
    """Return True if source is not already a suitable AI Processing Version."""
    is_mp4 = "mp4" in probe.container or probe.path.suffix.lower() == ".mp4"
    is_h264 = probe.video_codec in ("h264", "avc1")
    fits_res = (
        probe.width > 0
        and probe.height > 0
        and probe.width <= MAX_WIDTH
        and probe.height <= MAX_HEIGHT
    )
    if (not is_mp4) or (not is_h264) or (not fits_res):
        return True
    # Already H.264 MP4 at ≤720p — only recompress very large files.
    if probe.size_bytes > 50 * 1024 * 1024:
        return True
    return False


def _scale_filter(width: int, height: int) -> Optional[str]:
    """Fit inside 1280×720 without upscaling (handles rotated phone video)."""
    if width <= 0 or height <= 0:
        return f"scale=min({MAX_WIDTH}\\,iw):-2,scale=-2:min({MAX_HEIGHT}\\,ih)"
    if width <= MAX_WIDTH and height <= MAX_HEIGHT:
        return None
    # Width cap then height cap — works for landscape and portrait after autorotate.
    return f"scale=min({MAX_WIDTH}\\,iw):-2,scale=-2:min({MAX_HEIGHT}\\,ih)"


def build_normalize_command(
    input_path: Path,
    output_path: Path,
    *,
    width: int,
    height: int,
    crf: int,
    maxrate: Optional[str] = None,
) -> list[str]:
    """FFmpeg command: H.264 MP4, ≤1280×720, 30fps, AAC — never upscale."""
    filters: list[str] = []
    scale = _scale_filter(width, height)
    if scale:
        filters.append(scale)
    vf = ",".join(filters) if filters else None

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        str(crf),
        "-pix_fmt",
        "yuv420p",
    ]
    if maxrate:
        cmd.extend(["-maxrate", maxrate, "-bufsize", maxrate])
    if vf:
        cmd.extend(["-vf", vf])
    cmd.extend(
        [
            "-r",
            str(TARGET_FPS),
            "-c:a",
            "aac",
            "-b:a",
            AUDIO_BITRATE,
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )
    return cmd


def normalize_for_ai(
    input_path: Path | str,
    output_path: Path | str | None = None,
    *,
    force: bool = False,
) -> Path:
    """Produce AI Processing Version next to the download (or at ``output_path``).

    Raises:
        VideoTooLongError: duration > 5 minutes
        VideoTooLargeError: file > 100MB
        RuntimeError: ffmpeg failure
    """
    src = Path(input_path).resolve()
    probe = probe_video(src)

    if probe.size_bytes > MAX_UPLOAD_BYTES:
        raise VideoTooLargeError(
            f"Video size must be less than 100MB (got {probe.size_mb:.1f}MB)"
        )
    if probe.duration > MAX_DURATION_SEC + 0.5:
        minutes = probe.duration / 60.0
        raise VideoTooLongError(
            f"Video must be 5 minutes or shorter (got {minutes:.1f} min)"
        )

    if output_path is None:
        out = src.with_name(f"{src.stem}_ai.mp4")
    else:
        out = Path(output_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    if not force and not needs_normalize(probe):
        if out.resolve() != src.resolve():
            shutil.copy2(src, out)
            logger.info(
                "AI normalize skip (already suitable): %s (%.1fMB %dx%d %s)",
                src.name,
                probe.size_mb,
                probe.width,
                probe.height,
                probe.video_codec,
            )
            return out
        logger.info(
            "AI normalize skip (already suitable): %s",
            src.name,
        )
        return src

    crf = _choose_crf(probe.size_bytes)
    maxrate = None
    if probe.size_bytes >= 10 * 1024 * 1024 or probe.duration > 60:
        maxrate = _max_video_bitrate(probe.duration)

    cmd = build_normalize_command(
        src,
        out,
        width=probe.width,
        height=probe.height,
        crf=crf,
        maxrate=maxrate,
    )
    logger.info(
        "AI normalize %s → %s (crf=%s maxrate=%s; src=%.1fMB %dx%d %s %.1fs)",
        src.name,
        out.name,
        crf,
        maxrate or "-",
        probe.size_mb,
        probe.width,
        probe.height,
        probe.video_codec or "?",
        probe.duration,
    )
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if result.returncode != 0 or not out.exists() or out.stat().st_size < 1000:
        err = (result.stderr or result.stdout or "")[-800:]
        raise RuntimeError(f"Video normalize failed: {err}")

    try:
        after = probe_video(out)
        logger.info(
            "AI normalize done: %.1fMB → %.1fMB (%dx%d)",
            probe.size_mb,
            after.size_mb,
            after.width,
            after.height,
        )
    except Exception:  # noqa: BLE001
        pass
    return out
