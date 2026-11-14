# Run Nesto locally

## Prerequisites

- Python 3.10+ and Node.js 18.17+.
- FFmpeg on `PATH`.
- Your own compatible multimodal LLM and TTS provider credentials for generation.

## Backend

From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
PYTHONPATH=system uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Set `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`, and the TTS provider settings for the providers you use. Provider behavior and model compatibility can vary. The saved demo uses an existing local run rather than a fresh generation request.

Leaving `DATABASE_URL` empty enables the local in-memory store. For persistence, configure your own Supabase database and apply the migrations in `system/supabase/migrations/`.

API documentation: `http://127.0.0.1:8000/docs`.

## Studio

In another terminal:

```bash
cd system/frontend
npm ci
cp .env.example .env.local
npm run dev:studio
```

Open `http://127.0.0.1:3001`. The Studio uses an invite session. Set `INVITE_ADMIN_KEY` in the backend environment, then create an invite through `POST /api/invite/create` using the `X-Admin-Key` header. Enter the returned code in the local invite page.

## Worker

Generation jobs use a separate worker:

```bash
PYTHONPATH=system:system/worker python system/worker/worker.py
```

The backend and worker need matching provider and storage configuration. Optional cloud deployment also requires your own database, object-storage bucket, CORS configuration, and access controls.

## Media

Supply your own property footage. Runtime workspaces belong in `storage/`; they are ignored by Git. Background music is optional and must be supplied separately with appropriate usage rights.

The public demo build script accepts the original local workspace as an input and uses only its saved render and TTS timing. Run `npm install --prefix tools` to install the SVG title-card renderer, then see `python tools/build_demo.py --help`. Pass `--font` with a local TrueType font path on non-macOS systems.
