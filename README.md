<p align="center"><img src="docs/assets/nesto-icon.png" width="72" alt="Nesto"></p>
<h1 align="center">Nesto Housing Director</h1>
<p align="center"><strong>An inspectable production system for real estate video.</strong></p>
<p align="center">Visual evidence → narrative decisions → measured speech → a finished video</p>
<p align="center"><a href="https://yejiasong1-ferrari.github.io/nesto-housing-director-studio/">Watch the system walkthrough</a> · <a href="docs/LOCAL_SETUP.md">Run the AI pipeline</a> · <a href="docs/SECURITY.md">Data boundaries</a></p>

Nesto coordinates **eight specialized agents** around a shared Project State to turn property walkthrough footage and a director brief into a narrated video. It brings visual analysis, storytelling, speech timing, editing and quality review into one workflow, with structured artifacts that a human can inspect and revise.

The system is designed for property agents and small production teams that need a consistent walkthrough narrative without manually rebuilding every script, speech window and edit decision.

## Recorded system walkthrough

[![Watch the Nesto system walkthrough](docs/assets/reference-poster.jpg)](https://yejiasong1-ferrari.github.io/nesto-housing-director-studio/)

**[Watch the video](https://yejiasong1-ferrari.github.io/nesto-housing-director-studio/)** · [Download the MP4](docs/assets/nesto-system-overview.mp4)

The playback page contains the recorded video, chapter navigation and recording information. Visitors can also play the preview directly in this README; architecture diagrams remain below. Video upload and processing are available only in a separately configured private deployment.

The recording introduces the workflow and includes an actual saved 55-second render. Speech is reconstructed from saved TTS files and recorded timing; background music is omitted. Playback does not rerun the AI pipeline. See [media provenance](docs/MEDIA_NOTES.md).

## System architecture

![Nesto system overview](docs/assets/system-overview.svg)

The **public playback page** presents the recorded output and its video information. The **private Next.js Studio** handles authenticated generation jobs, footage input and human review when deployed with the backend and worker.

The **FastAPI backend** owns the API contracts and shared project artifacts. A separate **worker** executes the generation workflow. **MoviePy/FFmpeg** apply deterministic media operations; model calls handle visual interpretation and language-heavy decisions.

## Eight-agent collaboration

![Eight-agent collaboration and bounded feedback](docs/assets/agent-workflow.svg)

1. **Vision** turns footage into a room/scene inventory and visual knowledge base.
2. **Planner** interprets the brief, prioritizes property highlights and arranges the narrative.
3. **Script** writes scene-grounded narration and checks style, coverage and duration budgets.
4. **Voice** plans delivery, rhythm and pronunciation; a separate TTS execution service synthesizes and measures speech.
5. **Timeline** checks budgets before TTS and reconciles final windows with measured speech afterward.
6. **Editing** specifies pacing, visual operations, subtitles and audio treatment as structured decisions.
7. **Rendering** executes the media plan and records output metadata and timing.
8. **Evaluation** reviews alignment, subtitles, timeline and technical quality, with bounded correction routing.

The shared state connects the scene evidence to the script, voice specification, edit plan and final render. Explicit timing constraints and correction limits make intermediate decisions inspectable rather than hiding the workflow behind one prompt.

## Data and credentials

![Public source, recorded presentation and private server data boundaries](docs/assets/data-boundaries.svg)

This curated public snapshot excludes the original development history, provider credentials, runtime workspaces, logs, uploaded customer data and private deployment configuration. `.env.example` contains placeholders only. Provider keys belong in **server environment variables**, never in frontend bundles or public project files.

Run `python tools/privacy_check.py` before publishing. It scans the working tree and reachable Git blobs without printing credential values. Optional local-only comparison against a private environment file is documented in [SECURITY.md](docs/SECURITY.md). A scan supplements human review; it is not a guarantee that arbitrary media or text contains no private information.

## Run locally

To preview the public video page, no package installation or API key is needed:

```bash
python -m http.server 8080 --directory docs
```

Open `http://localhost:8080`. This page only displays the recording and its video information. To run private AI generation, use Python 3.10+, Node.js 18.17+, FFmpeg and your own compatible model/TTS providers:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
PYTHONPATH=system uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Follow [LOCAL_SETUP.md](docs/LOCAL_SETUP.md) for the Next.js Studio, invite setup and worker. Review access controls, storage permissions and provider settings before processing private footage.

## Source map

```text
docs/                      Recorded walkthrough, project page and architecture diagrams
system/frontend/           Private Next.js Studio
system/backend/api/        FastAPI service endpoints
system/backend/agents/     Eight specialized agent modules
system/backend/workflow/   Orchestration and dependency handling
system/worker/             Generation worker
system/supabase/           Persistence schema and migrations
configs/                   Workflow configuration
tools/                     Publication scanner and diagram/media builders
```

## Validation

```bash
python tools/privacy_check.py
python -m pytest system/backend/agents/timeline/tests system/backend/agents/evaluation/tests -q
```

The public page is checked for video playback, chapter navigation and valid local assets. The existing timeline/evaluation suites contain **54 passing tests**. These checks do not certify an arbitrary provider deployment or the complete model-generation pipeline.

No open-source license has been selected for the project code. Third-party dependencies and reference footage retain their respective terms. Media provenance is documented separately.
