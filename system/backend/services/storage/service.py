"""File storage service abstraction.

Manages project file storage including videos, audio,
rendered outputs, and temporary files.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class StorageConfig(BaseModel):
    """Storage service configuration."""

    base_path: Path = Path("./storage")
    projects_dir: str = "projects"
    temp_dir: str = "tmp"


class StorageService:
    """Service for managing project file storage.

    Provides a consistent interface for file operations across
    local filesystem and future cloud storage backends.
    """

    def __init__(self, config: StorageConfig | None = None) -> None:
        self.config = config or StorageConfig()
        self._ensure_directories()

    def _ensure_directories(self) -> None:
        """Create storage directories if they don't exist."""
        (self.config.base_path / self.config.projects_dir).mkdir(parents=True, exist_ok=True)
        (self.config.base_path / self.config.temp_dir).mkdir(parents=True, exist_ok=True)

    def get_project_dir(self, project_id: str) -> Path:
        """Get the storage directory for a project."""
        project_dir = self.config.base_path / self.config.projects_dir / project_id
        project_dir.mkdir(parents=True, exist_ok=True)
        return project_dir

    def get_video_path(self, project_id: str) -> Path:
        """Get the path where the source video is stored."""
        return self.get_project_dir(project_id) / "source_video.mov"

    def get_audio_dir(self, project_id: str) -> Path:
        """Get the directory for generated audio files."""
        audio_dir = self.get_project_dir(project_id) / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        return audio_dir

    def get_output_path(self, project_id: str) -> Path:
        """Get the path for the final rendered video."""
        return self.get_project_dir(project_id) / "output.mp4"

    def get_temp_dir(self) -> Path:
        """Get the temporary files directory."""
        temp_dir = self.config.base_path / self.config.temp_dir
        temp_dir.mkdir(parents=True, exist_ok=True)
        return temp_dir

    def cleanup_project(self, project_id: str) -> None:
        """Remove all files for a project."""
        project_dir = self.get_project_dir(project_id)
        if project_dir.exists():
            shutil.rmtree(project_dir)
            logger.info(f"Cleaned up project: {project_id}")

    def cleanup_temp(self) -> None:
        """Remove all temporary files."""
        temp_dir = self.get_temp_dir()
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
            temp_dir.mkdir(parents=True, exist_ok=True)
            logger.info("Cleaned up temporary files")
