create extension if not exists pgcrypto;

create table if not exists jobs (
  id uuid primary key default gen_random_uuid(),
  status text not null default 'pending',
  pipeline_type text not null,
  priority int not null default 0,
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
  error_detail jsonb,
  metadata jsonb not null default '{}'::jsonb,
  terminal_notified boolean not null default false,
  webhook_attempts int not null default 0,
  last_webhook_error text,
  created_at timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz,
  updated_at timestamptz not null default now()
);

alter table jobs add column if not exists priority int not null default 0;
alter table jobs add column if not exists log text;
alter table jobs add column if not exists error_detail jsonb;
alter table jobs add column if not exists terminal_notified boolean not null default false;
alter table jobs add column if not exists webhook_attempts int not null default 0;
alter table jobs add column if not exists last_webhook_error text;
alter table jobs add column if not exists started_at timestamptz;
alter table jobs add column if not exists finished_at timestamptz;

create table if not exists job_secrets (
  job_id uuid not null references jobs(id) on delete cascade,
  path text not null,
  value text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (job_id, path)
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

drop trigger if exists job_secrets_set_updated_at on job_secrets;
create trigger job_secrets_set_updated_at
before update on job_secrets
for each row
execute function set_updated_at();

create index if not exists jobs_claim_lookup_idx
on jobs (status, cancel_requested, lease_expires_at, created_at);

create index if not exists jobs_worker_lookup_idx
on jobs (worker_id, status);

create index if not exists jobs_status_created_idx
on jobs (status, created_at desc);

create index if not exists jobs_priority_claim_idx
on jobs (priority desc, created_at asc)
where status = 'pending' and cancel_requested = false;

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
      status = 'pending'
      and cancel_requested = false
    order by priority desc, created_at asc
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

create or replace function release_stale_leases(p_max_attempts int default 3)
returns int
language plpgsql
as $$
declare
  released int := 0;
begin
  update jobs
  set
    status = case
      when cancel_requested then 'cancelled'
      when attempt_count >= p_max_attempts then 'failed'
      else 'pending'
    end,
    worker_id = null,
    lease_expires_at = null,
    pid = null,
    finished_at = case
      when cancel_requested or attempt_count >= p_max_attempts then now()
      else finished_at
    end,
    error = case
      when cancel_requested then coalesce(error, 'cancelled')
      when attempt_count >= p_max_attempts then coalesce(error, 'max attempts (' || p_max_attempts || ') exceeded')
      else error
    end,
    error_detail = case
      when attempt_count >= p_max_attempts and not cancel_requested then jsonb_build_object(
        'code', 'MAX_ATTEMPTS_EXCEEDED',
        'message', 'job exceeded ' || p_max_attempts || ' attempts',
        'retriable', false,
        'stage', 'execution'
      )
      else error_detail
    end,
    progress = case
      when cancel_requested or attempt_count >= p_max_attempts then progress
      else 0
    end,
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

create or replace function verify_jobs_schema_requirements(
  p_table_name text default 'jobs',
  p_required_trigger text default 'jobs_set_updated_at',
  p_required_rpcs text[] default array['claim_jobs', 'release_stale_leases', 'request_cancel_job'],
  p_required_columns text[] default array[
    'id',
    'status',
    'pipeline_type',
    'priority',
    'payload',
    'input_path',
    'input_uri',
    'output_path',
    'source_sha256',
    'pid',
    'worker_id',
    'lease_expires_at',
    'cancel_requested',
    'attempt_count',
    'progress',
    'step_index',
    'total_steps',
    'current_step',
    'log',
    'error',
    'error_detail',
    'metadata',
    'terminal_notified',
    'webhook_attempts',
    'last_webhook_error',
    'created_at',
    'started_at',
    'finished_at',
    'updated_at'
  ],
  p_required_indexes text[] default array[
    'jobs_claim_lookup_idx',
    'jobs_worker_lookup_idx',
    'jobs_status_created_idx',
    'jobs_priority_claim_idx'
  ]
)
returns jsonb
language plpgsql
stable
as $$
declare
  v_table_exists boolean;
  v_secret_table_exists boolean;
  v_trigger_exists boolean;
  v_missing_rpcs text[];
  v_missing_columns text[];
  v_missing_indexes text[];
begin
  select exists(
    select 1
    from information_schema.tables
    where table_schema = 'public'
      and table_name = p_table_name
  ) into v_table_exists;

  select exists(
    select 1
    from information_schema.tables
    where table_schema = 'public'
      and table_name = 'job_secrets'
  ) into v_secret_table_exists;

  select exists(
    select 1
    from pg_trigger t
    join pg_class c on c.oid = t.tgrelid
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public'
      and c.relname = p_table_name
      and t.tgname = p_required_trigger
      and not t.tgisinternal
  ) into v_trigger_exists;

  select coalesce(array_agg(required_fn), array[]::text[])
  from unnest(p_required_rpcs) as required_fn
  where not exists (
    select 1
    from pg_proc p
    join pg_namespace ns on ns.oid = p.pronamespace
    where ns.nspname = 'public'
      and p.proname = required_fn
  )
  into v_missing_rpcs;

  select coalesce(array_agg(required_column), array[]::text[])
  from unnest(p_required_columns) as required_column
  where not exists (
    select 1
    from information_schema.columns c
    where c.table_schema = 'public'
      and c.table_name = p_table_name
      and c.column_name = required_column
  )
  into v_missing_columns;

  select coalesce(array_agg(required_index), array[]::text[])
  from unnest(p_required_indexes) as required_index
  where not exists (
    select 1
    from pg_indexes i
    where i.schemaname = 'public'
      and i.tablename = p_table_name
      and i.indexname = required_index
  )
  into v_missing_indexes;

  return jsonb_build_object(
    'ok',
      v_table_exists
      and v_secret_table_exists
      and v_trigger_exists
      and coalesce(array_length(v_missing_rpcs, 1), 0) = 0
      and coalesce(array_length(v_missing_columns, 1), 0) = 0
      and coalesce(array_length(v_missing_indexes, 1), 0) = 0,
    'table_exists', v_table_exists,
    'secret_table_exists', v_secret_table_exists,
    'trigger_exists', v_trigger_exists,
    'missing_rpcs', to_jsonb(v_missing_rpcs),
    'missing_columns', to_jsonb(v_missing_columns),
    'missing_indexes', to_jsonb(v_missing_indexes)
  );
end;
$$;
