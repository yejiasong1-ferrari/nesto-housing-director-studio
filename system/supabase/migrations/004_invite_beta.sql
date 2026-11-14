-- Beta invite codes + temporary sessions (3-hour access)
-- Run in Supabase Dashboard → SQL Editor if create_all is not enough

create extension if not exists "pgcrypto";

create table if not exists invite_codes (
  id text primary key,
  code varchar(32) unique not null,
  status varchar(20) not null default 'active',
  used_by varchar(255),
  device_id varchar(255),
  created_at timestamptz not null default now(),
  activated_at timestamptz,
  expires_at timestamptz
);

create index if not exists idx_invite_codes_code on invite_codes (code);
create index if not exists idx_invite_codes_status on invite_codes (status);

create table if not exists beta_sessions (
  id text primary key,
  invite_code varchar(32) not null,
  token varchar(255) unique not null,
  device_id varchar(255),
  created_at timestamptz not null default now(),
  expires_at timestamptz not null
);

create index if not exists idx_beta_sessions_token on beta_sessions (token);
create index if not exists idx_beta_sessions_expires on beta_sessions (expires_at);

alter table invite_codes enable row level security;
alter table beta_sessions enable row level security;

drop policy if exists "nesto_invite_codes_all" on invite_codes;
create policy "nesto_invite_codes_all" on invite_codes for all using (true) with check (true);

drop policy if exists "nesto_beta_sessions_all" on beta_sessions;
create policy "nesto_beta_sessions_all" on beta_sessions for all using (true) with check (true);
