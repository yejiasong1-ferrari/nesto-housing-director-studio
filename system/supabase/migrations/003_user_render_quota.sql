-- User render quota: each full generate (create) or Studio re-export counts as 1.
-- Script / audio edits alone do NOT consume quota until export.

alter table users
  add column if not exists render_quota integer not null default 20;

alter table users
  add column if not exists renders_used integer not null default 0;
