-- Trusted experiment consumption, independent of model selection/skill activation.
-- A corpus final-test partition may be consumed once per organization/run.
create table if not exists public.finance_learning_holdouts (
  organization_id uuid not null,
  run_id uuid not null,
  dataset_sha256 text not null check (dataset_sha256 ~ '^[0-9a-f]{64}$'),
  experiment_id uuid not null,
  candidate_sha256 text not null check (candidate_sha256 ~ '^[0-9a-f]{64}$'),
  consumed_at timestamptz not null default now(),
  primary key (organization_id, run_id, dataset_sha256),
  foreign key (organization_id,run_id) references public.demo_runs(organization_id,id)
);
alter table public.finance_learning_holdouts enable row level security;
revoke all on public.finance_learning_holdouts from public, anon, authenticated, service_role;

create or replace function public.claim_finance_learning_holdout(
  p_organization_id uuid, p_run_id uuid, p_experiment_id uuid,
  p_dataset_sha256 text, p_candidate_sha256 text
) returns jsonb language plpgsql security definer set search_path=public,pg_temp as $$
declare inserted integer;
begin
  if p_experiment_id is null or p_dataset_sha256 is null or p_candidate_sha256 is null
     or p_dataset_sha256 !~ '^[0-9a-f]{64}$' or p_candidate_sha256 !~ '^[0-9a-f]{64}$' then
    raise exception 'invalid experiment fingerprint' using errcode='22023';
  end if;
  if not exists(select 1 from public.demo_runs where organization_id=p_organization_id and id=p_run_id
      and status='active' and (expires_at is null or expires_at>now())) then
    raise exception 'active scoped run required' using errcode='42501';
  end if;
  insert into public.finance_learning_holdouts(organization_id,run_id,dataset_sha256,experiment_id,candidate_sha256)
  values(p_organization_id,p_run_id,p_dataset_sha256,p_experiment_id,p_candidate_sha256)
  on conflict do nothing;
  get diagnostics inserted=row_count;
  return jsonb_build_object('claimed',inserted=1,'experiment_id',p_experiment_id);
end;
$$;
revoke all on function public.claim_finance_learning_holdout(uuid,uuid,uuid,text,text) from public,anon,authenticated;
grant execute on function public.claim_finance_learning_holdout(uuid,uuid,uuid,text,text) to service_role;
