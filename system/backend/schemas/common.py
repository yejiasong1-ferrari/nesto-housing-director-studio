"""Common schema base models for the AI Director system.

Every JSON communication between modules must include:
- version: schema version for forward compatibility
- project_id: unique project identifier
- agent_name: the agent that produced this data
- timestamp: when the data was produced
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class VersionedBaseModel(BaseModel):
    """Base model for all inter-module communication.

    Every agent output must include these metadata fields for
    traceability, reproducibility, and version compatibility.
    """

    version: str = "1.0.0"
    project_id: str = ""
    agent_name: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = {"from_attributes": True}
