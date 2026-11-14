-- Nesto Phase 3: product-state tables (not video blobs)
-- Run in Supabase Dashboard → SQL Editor → New query → Run

create table if not exists users (
  id text primary key,
  email text unique not null,
  created_at timestamptz not null default now()
);

create table if not exists projects (
  id text primary key,
  user_id text references users (id) on delete set null,
  title text not null default 'Untitled',
  brief text not null default '',
  language text not null default 'zh',
  status text not null default 'created',
  video_path text,
  video_url text,
  final_video text,
  active_job_id text,
  error text not null default '',
  property_metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists jobs (
  id text primary key,
  project_id text not null references projects (id) on delete cascade,
  stage text not null default '',
  progress integer not null default 0,
  status text not null default 'waiting',
  final_video text,
  error text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_projects_user_id on projects (user_id);
create index if not exists idx_projects_status on projects (status);
create index if not exists idx_jobs_project_id on jobs (project_id);
create index if not exists idx_jobs_status on jobs (status);

-- Phase 3 MVP: open policies (tighten when Auth lands)
alter table users enable row level security;
alter table projects enable row level security;
alter table jobs enable row level security;

drop policy if exists "nesto_users_all" on users;
create policy "nesto_users_all" on users for all using (true) with check (true);

drop policy if exists "nesto_projects_all" on projects;
create policy "nesto_projects_all" on projects for all using (true) with check (true);

drop policy if exists "nesto_jobs_all" on jobs;
create policy "nesto_jobs_all" on jobs for all using (true) with check (true);
