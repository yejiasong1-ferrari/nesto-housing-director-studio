# Phase 4 — Cloudflare R2 uploads

## Env (repo root `.env`)

```bash
R2_BUCKET=nesto-director
R2_ENDPOINT=https://<ACCOUNT_ID>.r2.cloudflarestorage.com
R2_ACCESS_KEY=...
R2_SECRET_KEY=...
```

Create the bucket **`nesto-director`** in Cloudflare Dashboard → R2 if HeadBucket returns 404.

## Flow

1. `POST /api/projects` → `project_id`
2. `POST /api/upload-url` `{ filename, project_id }` → `upload_url` + `key`
3. Browser / client: `PUT upload_url` with body = file bytes and matching `Content-Type`
4. `POST /api/upload-complete` `{ project_id, key }` → Supabase `video_url` + Job `waiting`

## Smoke (after bucket exists)

```bash
PYTHONPATH=system python3 - <<'PY'
from backend import r2
print(r2.health_check())
PY
```
