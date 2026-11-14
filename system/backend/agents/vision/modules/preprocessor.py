"""Module 1: Video Preprocessing.

Builds a complete video index: resolution, FPS, duration,
frame count, timestamp mapping. Uses OpenCV and FFmpeg.
Completely deterministic. No AI involved.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from backend.schemas.vision_schema import VideoIndex

logger = logging.getLogger(__name__)


class VideoPreprocessor:
    """Preprocesses video to build a technical index.

    No AI. Purely deterministic metadata extraction.
    """

    def __init__(self, frame_sample_rate: float = 1.0) -> None:
        """Initialize preprocessor.

        Args:
            frame_sample_rate: Sample one frame every N seconds for indexing.
        """
        self.frame_sample_rate = frame_sample_rate

    def build_index(self, video_path: str | Path) -> VideoIndex:
        """Extract complete video metadata using ffprobe and OpenCV.

        Args:
            video_path: Path to the walkthrough video.

        Returns:
            VideoIndex with all technical metadata.
        """
        video_path = Path(video_path)
        if not video_path.exists():
            raise FileNotFoundError(f"Video not found: {video_path}")

        # Try ffprobe first (most reliable)
        info = self._probe_with_ffprobe(video_path)

        return VideoIndex(
            file_path=str(video_path),
            duration=info.get("duration", 0.0),
            fps=info.get("fps", 0.0),
            width=info.get("width", 0),
            height=info.get("height", 0),
            codec=info.get("codec", ""),
            frame_count=info.get("frame_count", 0),
        )

    def _probe_with_ffprobe(self, video_path: Path) -> dict:
        """Extract metadata using ffprobe."""
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(video_path),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                logger.warning(f"ffprobe failed, falling back to OpenCV")
                return self._probe_with_opencv(video_path)

            data = json.loads(result.stdout)
            fmt = data.get("format", {})
            video_stream = None
            for stream in data.get("streams", []):
                if stream.get("codec_type") == "video":
                    video_stream = stream
                    break

            if not video_stream:
                return self._probe_with_opencv(video_path)

            # Parse FPS from fraction string like "120/1"
            fps = 0.0
            r_frame_rate = video_stream.get("r_frame_rate", "0/1")
            if "/" in r_frame_rate:
                num, den = r_frame_rate.split("/")
                if int(den) != 0:
                    fps = int(num) / int(den)

            return {
                "duration": float(fmt.get("duration", 0)),
                "fps": fps,
                "width": int(video_stream.get("width", 0)),
                "height": int(video_stream.get("height", 0)),
                "codec": video_stream.get("codec_name", ""),
                "frame_count": int(fmt.get("nb_frames", 0)),
            }
        except (subprocess.TimeoutExpired, json.JSONDecodeError, ValueError) as e:
            logger.warning(f"ffprobe error: {e}, falling back to OpenCV")
            return self._probe_with_opencv(video_path)

    def _probe_with_opencv(self, video_path: Path) -> dict:
        """Fallback: extract metadata using OpenCV."""
        import cv2

        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise ValueError(f"Cannot open video: {video_path}")

        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        duration = frame_count / fps if fps > 0 else 0.0
        cap.release()

        return {
            "duration": duration,
            "fps": fps,
            "width": width,
            "height": height,
            "codec": "",
            "frame_count": frame_count,
        }

    def extract_frames_at_rate(
        self,
        video_path: str | Path,
        output_dir: str | Path,
        sample_fps: float = 1.0,
    ) -> list[dict]:
        """Extract frames at a given sample rate for indexing.

        Uses FFmpeg for extraction (more reliable than OpenCV for
        high-FPS videos like iPhone recordings).

        Args:
            video_path: Path to the video.
            output_dir: Directory to save extracted frames.
            sample_fps: Frames per second to extract (default: 1 fps).

        Returns:
            List of dicts with frame_path and timestamp.
        """
        video_path = Path(video_path)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Use FFmpeg for reliable frame extraction
        # This handles high-FPS iPhone videos that confuse OpenCV
        cmd = [
            "ffmpeg",
            "-i", str(video_path),
            "-vf", f"fps={sample_fps},scale='min(640,iw)':-1",
            "-q:v", "2",
            "-y",
            str(output_dir / "frame_%06d.jpg"),
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode != 0:
                logger.warning(f"FFmpeg extraction failed: {result.stderr[:200]}")
                return self._extract_frames_opencv(video_path, output_dir, sample_fps)
        except subprocess.TimeoutExpired:
            logger.warning("FFmpeg extraction timed out, falling back to OpenCV")
            return self._extract_frames_opencv(video_path, output_dir, sample_fps)

        # Parse the extracted frames and compute timestamps
        import cv2

        frames = []
        frame_files = sorted(output_dir.glob("frame_*.jpg"))

        # Get video FPS for timestamp calculation
        cap = cv2.VideoCapture(str(video_path))
        video_fps = cap.get(cv2.CAP_PROP_FPS) if cap.isOpened() else sample_fps
        cap.release()

        # Use ffprobe duration for accurate timestamps
        video_info = self._probe_with_ffprobe(video_path)
        duration = video_info.get("duration", 0.0)

        for i, filepath in enumerate(frame_files):
            timestamp = round(i / sample_fps, 2) if sample_fps > 0 else 0.0
            frames.append({
                "frame_path": str(filepath),
                "timestamp": timestamp,
                "frame_idx": i,
            })

        logger.info(f"Extracted {len(frames)} frames from {video_path.name} via FFmpeg")
        return frames

    def _extract_frames_opencv(
        self,
        video_path: Path,
        output_dir: Path,
        sample_fps: float,
    ) -> list[dict]:
        """Fallback: extract frames using OpenCV."""
        import cv2

        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise ValueError(f"Cannot open video: {video_path}")

        video_fps = cap.get(cv2.CAP_PROP_FPS)
        frame_interval = int(video_fps / sample_fps) if sample_fps > 0 else 1

        frames = []
        frame_idx = 0
        saved_count = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx % frame_interval == 0:
                timestamp = frame_idx / video_fps if video_fps > 0 else 0.0
                filename = f"frame_{frame_idx:06d}.jpg"
                filepath = output_dir / filename

                h, w = frame.shape[:2]
                if w > 640:
                    scale = 640 / w
                    frame = cv2.resize(frame, (640, int(h * scale)))

                cv2.imwrite(str(filepath), frame)
                frames.append({
                    "frame_path": str(filepath),
                    "timestamp": round(timestamp, 2),
                    "frame_idx": frame_idx,
                })
                saved_count += 1

            frame_idx += 1

        cap.release()
        logger.info(f"Extracted {saved_count} frames from {video_path.name} via OpenCV")
        return frames
