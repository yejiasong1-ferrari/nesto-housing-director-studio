-- Beta accounts: one invite code → one durable beta identity
-- Session cookie maps to beta_account_id; projects/history are isolated by it.

create extension if not exists "pgcrypto";

create table if not exists beta_accounts (
  id text primary key,
  invite_code_id text not null,
  invite_code varchar(32) not null,
  user_token varchar(255) unique not null,
  device_id varchar(255),
  created_at timestamptz not null default now(),
  expires_at timestamptz
);

create index if not exists idx_beta_accounts_invite_code_id
  on beta_accounts (invite_code_id);
create index if not exists idx_beta_accounts_invite_code
  on beta_accounts (invite_code);
create index if not exists idx_beta_accounts_user_token
  on beta_accounts (user_token);

alter table beta_sessions
  add column if not exists beta_account_id text;

create index if not exists idx_beta_sessions_account
  on beta_sessions (beta_account_id);

alter table projects
  add column if not exists beta_account_id text;

create index if not exists idx_projects_beta_account
  on projects (beta_account_id);

alter table beta_accounts enable row level security;

drop policy if exists "nesto_beta_accounts_all" on beta_accounts;
create policy "nesto_beta_accounts_all" on beta_accounts
  for all using (true) with check (true);
