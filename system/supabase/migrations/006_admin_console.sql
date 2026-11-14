-- Admin console: account lifecycle, session presence, read-only view-as

alter table beta_accounts
  add column if not exists status varchar(20) not null default 'active';

alter table beta_accounts
  add column if not exists revoked_at timestamptz;

create index if not exists idx_beta_accounts_status
  on beta_accounts (status);

alter table beta_sessions
  add column if not exists heartbeat_at timestamptz;

alter table beta_sessions
  add column if not exists current_page varchar(64);

alter table beta_sessions
  add column if not exists current_project varchar(64);

alter table beta_sessions
  add column if not exists current_stage varchar(64);

alter table beta_sessions
  add column if not exists user_agent text;

alter table beta_sessions
  add column if not exists client_ip varchar(64);

alter table beta_sessions
  add column if not exists read_only boolean not null default false;

create index if not exists idx_beta_sessions_heartbeat
  on beta_sessions (heartbeat_at);
