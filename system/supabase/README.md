# Supabase (Phase 3)

Product state lives here: **users / projects / jobs**.  
Videos stay on disk (or later object storage) — not in Postgres.

## 1. Create tables

1. Open [Supabase Dashboard](https://supabase.com/dashboard) → your project  
2. **SQL Editor** → New query  
3. Paste and run [`migrations/001_nesto_phase3.sql`](./migrations/001_nesto_phase3.sql)

## 2. Backend connection

In repo root `.env`:

```bash
DATABASE_URL=<your-project-connection-string>
SUPABASE_URL=https://[ref].supabase.co
```

Get the URI from: **Project Settings → Database → Connection string**.

Then restart:

```bash
# from repo root
PYTHONPATH=system uvicorn backend.main:app --reload --port 8000
```

`GET /health` should show `"db": "supabase"`.

## 3. Frontend

`system/frontend/.env.local`:

```bash
NEXT_PUBLIC_SUPABASE_URL=https://[ref].supabase.co
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=sb_publishable_...
```

## 4. Smoke test

```bash
curl -X POST http://127.0.0.1:8000/api/users \
  -H 'Content-Type: application/json' \
  -d '{"email":"jack@example.com"}'

curl -X POST http://127.0.0.1:8000/api/projects \
  -H 'Content-Type: application/json' \
  -d '{"brief":"Highlight kitchen","language":"en","email":"jack@example.com","title":"Luxury House"}'
```

Then open **Table Editor** → `projects` / `jobs` / `users`.
