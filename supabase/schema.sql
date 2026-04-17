create extension if not exists pgcrypto;

create table if not exists jobs (
  id uuid primary key default gen_random_uuid(),
  status text not null default 'pending',
  pipeline_type text not null,
  payload jsonb not null default '{}'::jsonb,
  input_path text,
  input_uri text,
  output_path text,
  source_sha256 text not null,
  pid int,
  worker_id text,
  lease_expires_at timestamptz,
  cancel_requested boolean not null default false,
  attempt_count int not null default 0,
  progress int not null default 0,
  step_index int not null default 0,
  total_steps int not null default 0,
  current_step text,
  log text,
  error text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz,
  updated_at timestamptz not null default now()
);

create or replace function set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists jobs_set_updated_at on jobs;
create trigger jobs_set_updated_at
before update on jobs
for each row
execute function set_updated_at();

create or replace function claim_jobs(
  p_worker_id text,
  p_limit int,
  p_lease_seconds int
)
returns setof jobs
language plpgsql
as $$
declare
  v_now timestamptz := now();
begin
  return query
  with candidates as (
    select id
    from jobs
    where
      (status = 'pending' and cancel_requested = false)
      or (
        status = 'running'
        and cancel_requested = false
        and lease_expires_at is not null
        and lease_expires_at <= v_now
      )
    order by created_at
    limit p_limit
    for update skip locked
  ),
  claimed as (
    update jobs j
    set
      status = 'running',
      worker_id = p_worker_id,
      lease_expires_at = v_now + make_interval(secs => p_lease_seconds),
      attempt_count = j.attempt_count + 1,
      started_at = coalesce(j.started_at, v_now),
      updated_at = v_now
    from candidates
    where j.id = candidates.id
    returning j.*
  )
  select * from claimed;
end;
$$;

create or replace function release_stale_leases()
returns int
language plpgsql
as $$
declare
  released int := 0;
begin
  update jobs
  set
    status = case when cancel_requested then 'cancelled' else 'pending' end,
    worker_id = null,
    lease_expires_at = null,
    pid = null,
    finished_at = case when cancel_requested then now() else finished_at end,
    updated_at = now()
  where
    status = 'running'
    and lease_expires_at is not null
    and lease_expires_at <= now();

  get diagnostics released = row_count;
  return released;
end;
$$;

create or replace function request_cancel_job(p_job_id uuid)
returns setof jobs
language plpgsql
as $$
declare
  v_now timestamptz := now();
begin
  return query
  update jobs
  set
    cancel_requested = true,
    status = case
      when jobs.status = 'pending' then 'cancelled'
      else jobs.status
    end,
    finished_at = case
      when jobs.status = 'pending' then v_now
      else jobs.finished_at
    end,
    worker_id = case
      when jobs.status = 'pending' then null
      else jobs.worker_id
    end,
    lease_expires_at = case
      when jobs.status = 'pending' then null
      else jobs.lease_expires_at
    end,
    pid = case
      when jobs.status = 'pending' then null
      else jobs.pid
    end,
    updated_at = v_now
  where
    jobs.id = p_job_id
    and jobs.status not in ('done', 'failed', 'cancelled')
  returning jobs.*;

  if not found then
    return query
    select *
    from jobs
    where id = p_job_id
    limit 1;
  end if;
end;
$$;
