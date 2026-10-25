begin;
-- Explicit owner action only. Normal guided entry continues to resume its run.
create function public.restart_finance_guided_demo(p_previous_run_id uuid) returns jsonb
language plpgsql security definer set search_path=public,pg_temp as $$
declare previous demo_runs; fresh jsonb; next_run uuid; seed uuid;
begin
 if auth.uid() is null or auth.role()<>'authenticated'
 or coalesce(nullif(current_setting('request.jwt.claims',true),'')::jsonb->>'is_anonymous','false')='true'
 then raise exception 'non-anonymous sign in required' using errcode='42501'; end if;
 perform pg_advisory_xact_lock(hashtextextended(auth.uid()::text,0));
 select * into previous from demo_runs where id=p_previous_run_id for update;
 if not found or not previous.is_demo or previous.owner_user_id is distinct from auth.uid()
 or previous.scenario->>'id' is distinct from 'finney-mid-event-v1'
 then raise exception 'guided demo owner required' using errcode='42501'; end if;
 if previous.status<>'active' then
 raise exception 'guided demo already archived' using errcode='55000'; end if;
 perform finance_require_scope(previous.organization_id,previous.id,array['director']);
 perform finance_lock_run(previous.organization_id,previous.id);
 -- Serialize with the lease worker. A worker that already holds a job row must
 -- finish its lease transaction before this check; a later lease skips our locks.
 perform 1 from jobs where organization_id=previous.organization_id and run_id=previous.id
 and status in ('queued','running') order by id for update;
 if exists(select 1 from jobs where organization_id=previous.organization_id and run_id=previous.id and status='running') then
 raise exception 'wait for running demo work before restarting' using errcode='55000'; end if;
 -- Existing reset creates exactly one fresh run; prior financial records,
 -- completed/failed work and shared owner/day inference allowances are retained.
 -- Only pending queued jobs are canceled, through that established operation.
 fresh:=create_finance_demo('Hack Harbor · five days to go',previous.id);
 next_run:=(fresh->>'run_id')::uuid;
 update demo_runs set scenario=jsonb_build_object('id','finney-mid-event-v1','title','Hack Harbor',
 'brief','180 attendees. Five days to go. A revised invoice, a personal-card purchase and a sponsor payment still pending.',
 'experience_version','finney-companion-v1','synthetic',true,'status','preparing','steps','[]'::jsonb)
 where id=next_run and organization_id=previous.organization_id;
 seed:=enqueue_finance_command(previous.organization_id,next_run,'intake',
 jsonb_build_object('source','demo_bundle','bundle_version','finney-mid-event-v1'),'guided-seed:'||next_run);
 perform finance_audit(previous.organization_id,next_run,'guided_practice_restarted',jsonb_build_object(
 'previous_run_id',previous.id,'seed_job_id',seed,'previous_records_retained',true));
 return fresh||jsonb_build_object('previous_run_id',previous.id,'seed_job_id',seed,'seed_status','queued',
 'experience_version','finney-companion-v1');
end $$;
revoke all on function public.restart_finance_guided_demo(uuid) from public,anon,authenticated,service_role;
grant execute on function public.restart_finance_guided_demo(uuid) to authenticated;
commit;
