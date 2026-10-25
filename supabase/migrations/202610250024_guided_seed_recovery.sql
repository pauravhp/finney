-- Explicit, bounded recovery for a scenario whose initial worker rejected the
-- seed. Preserve failed jobs and already-written records; never reset a run.
begin;
create function public.finance_guided_seed_state(p_organization_id uuid,p_run_id uuid) returns jsonb
language plpgsql security definer set search_path=public,pg_temp as $$
declare r demo_runs; latest jobs; attempts integer;
begin
 if coalesce(auth.role(),'')<>'service_role' then perform finance_require_scope(p_organization_id,p_run_id); end if;
 select * into strict r from demo_runs where organization_id=p_organization_id and id=p_run_id;
 if r.scenario->>'id' is distinct from 'finney-mid-event-v1' then return '{}'::jsonb; end if;
 select count(*) into attempts from jobs where organization_id=p_organization_id and run_id=p_run_id
 and command_type='intake' and payload=jsonb_build_object('source','demo_bundle','bundle_version','finney-mid-event-v1');
 -- Prefer an existing live seed even when older terminal history remains.
 select * into latest from jobs where organization_id=p_organization_id and run_id=p_run_id
 and command_type='intake' and payload=jsonb_build_object('source','demo_bundle','bundle_version','finney-mid-event-v1')
 order by (status in ('queued','running')) desc,created_at desc,id desc limit 1;
 return jsonb_build_object('seed_job_id',latest.id,
 'seed_status',case when r.scenario->>'status'='ready' then 'ready' else coalesce(latest.status,'not_queued') end,
 'seed_attempts',attempts,'seed_attempt_limit',3,
 'seed_retry_available',r.scenario->>'status'<>'ready' and attempts<3 and coalesce(latest.status,'not_queued') not in ('queued','running'),
 'seed_error_code',case when latest.status in ('failed','blocked') then latest.error_code else null end);
end $$;

create or replace function public.create_finance_guided_demo() returns jsonb
language plpgsql security definer set search_path=public,pg_temp as $$
declare r demo_runs; scope jsonb; seed_state jsonb; seed uuid; previous_seed uuid; next_attempt integer; seed_key text;
begin
 if auth.uid() is null or auth.role()<>'authenticated'
 or coalesce(nullif(current_setting('request.jwt.claims',true),'')::jsonb->>'is_anonymous','false')='true'
 then raise exception 'non-anonymous sign in required' using errcode='42501'; end if;
 perform pg_advisory_xact_lock(hashtextextended(auth.uid()::text,0));
 select * into r from demo_runs where owner_user_id=auth.uid() and is_demo and status='active'
 and (expires_at is null or expires_at>now()) and scenario->>'id'='finney-mid-event-v1' order by created_at desc limit 1;
 if not found then
 scope:=create_finance_demo('Hack Harbor · five days to go',null);
 update demo_runs set scenario=jsonb_build_object('id','finney-mid-event-v1','title','Hack Harbor',
 'brief','180 attendees. Five days to go. A revised invoice, a personal-card purchase and a sponsor payment still pending.',
 'synthetic',true,'status','preparing','steps','[]'::jsonb)
 where id=(scope->>'run_id')::uuid returning * into r;
 end if;
 perform finance_require_scope(r.organization_id,r.id,array['director']);
 -- Serialize against the worker's initializer as well as concurrent owner calls.
 perform finance_lock_run(r.organization_id,r.id);
 seed_state:=finance_guided_seed_state(r.organization_id,r.id);
 if seed_state->>'seed_status'<>'ready' and seed_state->>'seed_retry_available'='true' then
 next_attempt:=(seed_state->>'seed_attempts')::integer+1;
 previous_seed:=(seed_state->>'seed_job_id')::uuid;
 seed_key:='guided-seed:'||r.id||case when next_attempt=1 then '' else ':retry:'||next_attempt end;
 seed:=enqueue_finance_command(r.organization_id,r.id,'intake',
 jsonb_build_object('source','demo_bundle','bundle_version','finney-mid-event-v1'),seed_key);
 if next_attempt>1 then
 perform finance_audit(r.organization_id,r.id,'guided_seed_retry_requested',jsonb_build_object(
 'previous_job_id',previous_seed,'job_id',seed,'attempt',next_attempt,'attempt_limit',3,'records_reset',false));
 end if;
 seed_state:=finance_guided_seed_state(r.organization_id,r.id);
 end if;
 return jsonb_build_object('organization_id',r.organization_id,'run_id',r.id)||seed_state;
end $$;

alter function public.get_finance_snapshot(uuid,uuid) rename to get_finance_snapshot_v23;
revoke all on function public.get_finance_snapshot_v23(uuid,uuid) from public,anon,authenticated,service_role;
create function public.get_finance_snapshot(p_organization_id uuid,p_run_id uuid) returns jsonb
language plpgsql security definer set search_path=public,pg_temp as $$
declare result jsonb;
begin
 result:=get_finance_snapshot_v23(p_organization_id,p_run_id);
 if result->'run'->'scenario'->>'id'='finney-mid-event-v1' then
 result:=jsonb_set(result,'{run,scenario}',result->'run'->'scenario'||finance_guided_seed_state(p_organization_id,p_run_id));
 end if;
 return result;
end $$;
revoke all on function public.finance_guided_seed_state(uuid,uuid),public.create_finance_guided_demo(),public.get_finance_snapshot(uuid,uuid) from public,anon,authenticated,service_role;
grant execute on function public.create_finance_guided_demo() to authenticated;
grant execute on function public.get_finance_snapshot(uuid,uuid) to authenticated,service_role;
commit;
