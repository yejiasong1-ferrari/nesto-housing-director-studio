-- Phase 9: unify SaaS job progress fields
-- Run in Supabase SQL Editor after 001_nesto_phase3.sql

alter table jobs add column if not exists kind text not null default 'create';
alter table jobs add column if not exists input_url text;
alter table jobs add column if not exists output_url text;

update jobs
set output_url = final_video
where output_url is null and final_video is not null;

create index if not exists idx_jobs_kind on jobs (kind);
