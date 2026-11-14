"""Nesto AI Director API — FastAPI entrypoint (Phase 2 service layer).

Run from repo root::

    uvicorn backend.main:app --reload --port 8000

Docs: http://127.0.0.1:8000/docs
Guide: http://127.0.0.1:8000/guide
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from backend.api.admin import router as admin_router
from backend.api.invite import router as invite_router
from backend.api.jobs import router as jobs_router
from backend.api.projects import router as projects_router
from backend.api.session_presence import router as session_router
from backend.api.studio import router as studio_router
from backend.api.upload import router as upload_router
from backend.api.users import router as users_router
from backend.database import db, init_db
from backend.paths import BACKEND_ROOT, REPO_ROOT
from backend.tools.property_workspace import STORAGE_ROOT

logger = logging.getLogger(__name__)

PROJECT_ROOT = REPO_ROOT
STORAGE_DIR = PROJECT_ROOT / "storage"
STATIC_DIR = BACKEND_ROOT / "static"


def _cors_origins() -> list[str]:
    """Local Studio + optional production frontends (comma-separated CORS_ORIGINS)."""
    defaults = [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
        "https://nesto.vercel.app",
        "https://nesto-housing-director.vercel.app",
    ]
    extra = (os.getenv("CORS_ORIGINS") or "").strip()
    if not extra:
        return defaults
    merged = defaults + [o.strip() for o in extra.split(",") if o.strip()]
    # preserve order, drop dupes
    seen: set[str] = set()
    out: list[str] = []
    for o in merged:
        if o not in seen:
            seen.add(o)
            out.append(o)
    return out

API_DESCRIPTION = """
**Nesto AI Director** — 房产带看视频的后端 API。

白话指南：[/guide](/guide)

---

### A. 生产上传（Cloudflare R2 · 推荐）

| 步骤 | 接口 | 说明 |
|:----:|------|------|
| 1 | `POST /api/projects` | 创建项目 |
| 2 | `POST /api/upload-url` | 获取 R2 预签名 PUT 地址 |
| 3 | 浏览器 `PUT` | 视频直传 Cloudflare R2 |
| 4 | `POST /api/upload-complete` | 写 Supabase + Job=`waiting` |
| 5 | Worker（下一步） | 拉 waiting job → `generate_video` |

### A2. 本地直传（开发用）

| 步骤 | 接口 | 说明 |
|:----:|------|------|
| 1–2 | `POST /api/upload` | 文件进本机 `storage/projects/` |
| 3 | `POST /api/jobs` | 本地视频立刻跑；仅 R2 则 `waiting` 等 Worker |

---

### B. Studio：改 Script / Audio 后重新出片

| 步骤 | 接口 | 说明 |
|:----:|------|------|
| 1 | `POST /api/studio/projects/{slug}/revise` | `script_update` 改旁白，或 `audio_offset` 改音频位置 |
| 2 | `GET /api/studio/jobs/{job_id}` | 等局部重生成完成 |
| 3 | `POST /api/studio/projects/{slug}/export` | **重新渲染成片**（应用上述修改） |
| 4 | `GET /api/studio/projects/{slug}` | 取 `video.final_url` |

> 只改 script/audio **不会**自动重渲整支视频；必须再调 **export**。

---

### 调试提示

展开接口 → **Try it out** → 填参数 → **Execute**。  
若按钮被挡住，向下滚动或刷新本页（已修复样式）。
"""

OPENAPI_TAGS = [
    {"name": "① 开始使用", "description": "健康检查与服务信息。"},
    {"name": "② 创建项目", "description": "服务层：用户 / 项目 CRUD。"},
    {
        "name": "③ 上传视频",
        "description": "R2 预签名上传（生产）或本地 multipart（开发）。",
    },
    {"name": "④ 生成视频", "description": "服务层：调用 generate_video，查询进度。"},
    {"name": "⑤ Studio · 项目", "description": "Studio：列表、详情、一键创建完整 pipeline。"},
    {
        "name": "⑥ Studio · 修改 Script / Audio",
        "description": "改旁白文案或音频偏移并局部重生成（TTS / timing）。改完后请调 export。",
    },
    {
        "name": "⑦ Studio · 导出与任务",
        "description": "重新导出成片、查询 / 取消 Studio job。",
    },
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Nesto AI Director API starting up")
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
    # Never block listen on DB. Railway /health is unreachable until this yields.
    try:
        mode = await asyncio.wait_for(asyncio.to_thread(init_db), timeout=8)
    except Exception as exc:  # noqa: BLE001 — boot must succeed for healthcheck
        logger.warning("init_db skipped during startup: %s", exc)
        mode = "deferred"
    logger.info("Nesto persistence mode: %s", mode)
    yield
    logger.info("Nesto AI Director API shutting down")


app = FastAPI(
    title="Nesto · AI 房产视频导演 API",
    description=API_DESCRIPTION,
    version="4.0.0-phase4",
    lifespan=lifespan,
    docs_url=None,  # custom /docs below
    redoc_url="/redoc",
    openapi_tags=OPENAPI_TAGS,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    # Preview deploys: https://nesto-xxx.vercel.app
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

app.include_router(invite_router)
app.include_router(session_router)
app.include_router(admin_router)
app.include_router(users_router)
app.include_router(projects_router)
app.include_router(upload_router)
app.include_router(jobs_router)
app.include_router(studio_router)

STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(STORAGE_ROOT)), name="media")
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/storage", StaticFiles(directory=str(STORAGE_DIR)), name="storage")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/docs", include_in_schema=False)
async def swagger_ui() -> HTMLResponse:
    """Custom Swagger UI with Nesto CSS (fixes clipped Execute buttons)."""
    html = get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title="Nesto API · Docs",
        swagger_favicon_url="/static/favicon.svg",
        swagger_css_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css",
        swagger_ui_parameters={
            "docExpansion": "list",
            "defaultModelsExpandDepth": -1,
            "defaultModelExpandDepth": 0,
            "filter": True,
            "tryItOutEnabled": True,
            "displayRequestDuration": True,
            "syntaxHighlight.theme": "agate",
            "persistAuthorization": False,
            "deepLinking": True,
        },
    )
    # Inject custom CSS after default Swagger CSS
    body = html.body.decode("utf-8") if isinstance(html.body, bytes) else str(html.body)
    inject = '<link rel="stylesheet" type="text/css" href="/static/docs.css">'
    if "</head>" in body and "/static/docs.css" not in body:
        body = body.replace("</head>", f"{inject}</head>", 1)
    return HTMLResponse(content=body)


@app.get(
    "/",
    tags=["① 开始使用"],
    summary="首页 · 服务是否在运行",
    description="打开根地址时返回一句确认信息。正常时应看到 `Nesto API running`。",
)
async def home() -> dict[str, str]:
    from backend import r2 as r2_mod

    return {
        "message": "Nesto API running",
        "guide": "/guide",
        "docs": "/docs",
        "service": "nesto-ai-director",
        "version": "4.0.0-phase4",
        "db": getattr(db, "mode", "memory"),
        "r2": "configured" if r2_mod.r2_configured() else "missing",
    }


@app.get(
    "/health",
    tags=["① 开始使用"],
    summary="健康检查",
    description="轻量存活检查（供 Railway）。加 `?deep=1` 才探测 R2。",
)
async def health(deep: bool = False) -> dict:
    from backend import r2 as r2_mod

    payload: dict = {
        "status": "ok",
        "service": "nesto-ai-director",
        "db": getattr(db, "mode", "memory"),
        "r2": {
            "configured": r2_mod.r2_configured(),
            # Default: do not call R2 — Railway healthchecks must stay fast.
            "checked": False,
        },
    }
    if deep:
        payload["r2"] = r2_mod.health_check()
        payload["r2"]["checked"] = True
    return payload


@app.get("/guide", include_in_schema=False, response_class=HTMLResponse)
async def guide() -> str:
    """Human-readable Chinese guide (easier than raw Swagger)."""
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Nesto API 使用指南</title>
  <style>
    :root {
      --ink: #162B49;
      --gold: #C8A96E;
      --teal: #3A9D9A;
      --bg: #FAF8F3;
      --line: #E8E1D5;
      --muted: #5c6b7a;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "PingFang SC", "Hiragino Sans GB", "Noto Sans SC", sans-serif;
      background: var(--bg);
      color: var(--ink);
      line-height: 1.6;
    }
    .wrap { max-width: 740px; margin: 0 auto; padding: 48px 24px 80px; }
    h1 { font-size: 1.75rem; margin: 0 0 8px; letter-spacing: -0.02em; }
    h2.section { font-size: 1.1rem; margin: 36px 0 14px; color: var(--ink); }
    .sub { color: var(--muted); margin: 0 0 28px; }
    .card {
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 18px 20px;
      margin-bottom: 12px;
    }
    .step { display: flex; gap: 14px; align-items: flex-start; }
    .num {
      flex: 0 0 32px; height: 32px; border-radius: 50%;
      background: var(--ink); color: #fff;
      display: grid; place-items: center; font-weight: 700; font-size: 0.9rem;
    }
    .num.teal { background: var(--teal); }
    .step h3 { margin: 2px 0 6px; font-size: 1.02rem; font-weight: 600; }
    .step p { margin: 0; color: var(--muted); font-size: 0.94rem; }
    code {
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      background: #f0ebe3; padding: 2px 6px; border-radius: 4px; font-size: 0.82rem;
      color: var(--ink);
    }
    .actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 28px; }
    a.btn {
      display: inline-block; text-decoration: none;
      padding: 10px 16px; border-radius: 8px; font-weight: 600; font-size: 0.95rem;
    }
    a.primary { background: var(--ink); color: #fff; }
    a.secondary { background: #fff; color: var(--ink); border: 1px solid var(--line); }
    .note {
      margin-top: 24px; padding: 14px 16px; border-left: 3px solid var(--gold);
      background: #fff; color: var(--muted); font-size: 0.9rem;
    }
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Nesto API 使用指南</h1>
    <p class="sub">两条主线：从零生成成片，或在 Studio 里改旁白 / 音频后再导出。</p>

    <h2 class="section">A · 从零生成</h2>
    <div class="card"><div class="step"><div class="num">1</div><div>
      <h3>创建项目</h3>
      <p><code>POST /api/projects</code> → 得到 <code>project_id</code></p>
    </div></div></div>
    <div class="card"><div class="step"><div class="num">2</div><div>
      <h3>上传视频</h3>
      <p>生产：<code>POST /api/upload-url</code> → PUT 到 R2 → <code>POST /api/upload-complete</code><br/>
      开发：<code>POST /api/upload</code> 本地直传</p>
    </div></div></div>
    <div class="card"><div class="step"><div class="num">3</div><div>
      <h3>开始生成</h3>
      <p><code>POST /api/jobs</code> → 得到 <code>job_id</code></p>
    </div></div></div>
    <div class="card"><div class="step"><div class="num">4</div><div>
      <h3>查进度</h3>
      <p><code>GET /api/jobs/{job_id}</code> → <code>completed</code> 后看 <code>final_video</code></p>
    </div></div></div>

    <h2 class="section">B · 改 Script / Audio 后重新出片</h2>
    <div class="card"><div class="step"><div class="num teal">1</div><div>
      <h3>修改旁白或音频位置</h3>
      <p><code>POST /api/studio/projects/{slug}/revise</code><br/>
      <code>script_update</code> 改文案并重录 TTS；<code>audio_offset</code> 改旁白起点</p>
    </div></div></div>
    <div class="card"><div class="step"><div class="num teal">2</div><div>
      <h3>等局部任务完成</h3>
      <p><code>GET /api/studio/jobs/{job_id}</code> 直到 <code>done</code></p>
    </div></div></div>
    <div class="card"><div class="step"><div class="num teal">3</div><div>
      <h3>重新导出成片（必须）</h3>
      <p><code>POST /api/studio/projects/{slug}/export</code> — 才会把修改烧进最终视频</p>
    </div></div></div>
    <div class="card"><div class="step"><div class="num teal">4</div><div>
      <h3>取新成片</h3>
      <p><code>GET /api/studio/projects/{slug}</code> → <code>video.final_url</code></p>
    </div></div></div>

    <div class="actions">
      <a class="btn primary" href="/docs">打开接口调试页</a>
      <a class="btn secondary" href="/redoc">阅读版文档</a>
      <a class="btn secondary" href="/health">健康检查</a>
    </div>

    <div class="note">
      <strong>重要：</strong>只调用 revise <em>不会</em>自动重渲整支视频。
      改完 script / audio 后一定要再调 <code>export</code>。
    </div>
  </div>
</body>
</html>
"""
