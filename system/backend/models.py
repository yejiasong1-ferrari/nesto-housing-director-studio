"""Nesto service-layer Pydantic models (API + store DTOs)."""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field

ProjectStatus = Literal[
    "created",
    "video_uploaded",
    "queued",
    "running",
    "processing",
    "completed",
    "error",
]

JobStatus = Literal["waiting", "running", "processing", "completed", "error", "cancelled"]
JobKind = Literal["create", "script_update", "audio_offset", "export"]


class User(BaseModel):
    user_id: str
    email: str


class Project(BaseModel):
    project_id: str
    user_id: Optional[str] = None
    beta_account_id: Optional[str] = None
    title: str = "Untitled"
    brief: str = ""
    language: str = "zh"
    status: ProjectStatus = "created"
    video_path: Optional[str] = None
    video_url: Optional[str] = None
    final_video: Optional[str] = None
    active_job_id: Optional[str] = None
    error: str = ""
    property_metadata: Dict[str, Any] = Field(default_factory=dict)


class Job(BaseModel):
    job_id: str
    project_id: str
    kind: JobKind = "create"
    status: JobStatus = "waiting"
    stage: str = ""
    progress: int = 0
    input_url: Optional[str] = None
    output_url: Optional[str] = None
    final_video: Optional[str] = None
    error: str = ""


class CreateUserBody(BaseModel):
    email: str = Field(..., description="用户邮箱", examples=["jack@example.com"])


class CreateProjectBody(BaseModel):
    """创建项目时提交的内容。"""

    brief: str = Field(
        "",
        description="导演意图，例如：多介绍采光、厨房和卫生间",
        examples=["Highlight natural light and modern kitchen"],
    )
    prompt: str = Field("", description="旧字段，等同 brief；可不填")
    language: str = Field(
        "zh",
        description="旁白语言：zh / en，也可用 Chinese / English",
        examples=["zh"],
    )
    title: str = Field("Untitled", description="项目标题")
    user_id: Optional[str] = Field(None, description="已有用户 ID（可选）")
    email: Optional[str] = Field(
        None,
        description="若提供邮箱且用户不存在，会自动创建用户并关联",
        examples=["jack@example.com"],
    )
    property_metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="可选房源附加信息",
    )


class CreateJobBody(BaseModel):
    project_id: str = Field(..., description="要生成成片的项目 ID", examples=["proj_abc123"])


class UserResponse(BaseModel):
    user_id: str
    email: str
    status: str = "created"


class ProjectResponse(BaseModel):
    project_id: str = Field(..., description="项目 ID，后续上传/生成都要用")
    status: str = Field(..., description="项目状态，如 created / video_uploaded / completed")
    message: str = ""
    job_id: Optional[str] = Field(None, description="若已开始生成，对应的任务 ID")
    language: Optional[str] = None
    user_id: Optional[str] = None
    beta_account_id: Optional[str] = None
    title: Optional[str] = None


class JobResponse(BaseModel):
    job_id: str = Field(..., description="任务 ID")
    project_id: str
    kind: str = Field("create", description="create / script_update / audio_offset / export")
    status: str = Field(..., description="waiting / running / completed / error")
    stage: str = Field("", description="当前阶段，如 Vision Analysis")
    progress: int = Field(0, description="进度 0–100")
    input_url: Optional[str] = Field(None, description="输入视频 r2:// 或本地路径")
    output_url: Optional[str] = Field(None, description="成片 r2:// 或本地路径")
    final_video: Optional[str] = Field(None, description="成片路径（兼容字段，等同 output_url）")
    error: str = Field("", description="失败时的错误信息")


class WorkerJobPayload(BaseModel):
    """Payload returned by ``GET /api/jobs/next`` for Mac / cloud Workers."""

    id: str = Field(..., description="Job ID")
    job_id: str
    project_id: str
    kind: str = "create"
    status: str
    stage: str = ""
    progress: int = 0
    video_url: Optional[str] = Field(None, description="R2 URI，如 r2://bucket/key")
    video_path: Optional[str] = Field(None, description="本地路径（若已有）")
    input_url: Optional[str] = None
    brief: str = ""
    language: str = "zh"
    user_id: Optional[str] = None
    title: str = ""
    workspace_slug: Optional[str] = Field(
        None,
        description="AI Director property workspace slug（export 等任务用）",
    )


class UpdateJobBody(BaseModel):
    job_id: str
    stage: Optional[str] = None
    progress: Optional[int] = None
    status: Optional[str] = Field(
        None,
        description="可选：running / processing→running / completed / error",
    )
    error: Optional[str] = None


class CompleteJobBody(BaseModel):
    job_id: str
    final_video: Optional[str] = Field(
        None,
        description="本地成片路径或 r2:// URI",
    )
    final_r2_uri: Optional[str] = Field(
        None,
        description="上传到 R2 后的 URI（优先写入 projects.final_video）",
    )
    workspace_slug: Optional[str] = Field(
        None,
        description="AI Director property workspace slug（完成后写入 project metadata）",
    )
    workspace_r2_prefix: Optional[str] = Field(
        None,
        description="Studio workspace R2 prefix（Railway 可从此 hydrate 编辑页）",
    )
    error: Optional[str] = Field(None, description="失败时填写；非空则标记 error")
