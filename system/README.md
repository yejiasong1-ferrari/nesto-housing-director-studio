# system/

Nesto application packages live here:

| Path | Role |
|------|------|
| `ai_director/` | Public `generate_video()` API |
| `backend/` | FastAPI service + AI Director agents |
| `frontend/` | Next.js Studio UI |
| `supabase/` | DB migrations / setup notes |
| `tests/` | Pipeline smoke scripts |

Repo root still holds `.env`, `storage/`, and CLI runners (`run_*.py`).

## Run API

```bash
# from repo root
PYTHONPATH=system uvicorn backend.main:app --reload --port 8000
```

## Run frontend

```bash
cd system/frontend
npm run dev:studio
```

## Imports

Python code should put `system/` on `sys.path` (CLI scripts use `import repo_paths`).
