begin;
-- New default fictional practice. Prior runs, records and source contracts remain intact.
alter function public.create_finance_guided_demo() rename to create_finance_guided_demo_v26;
revoke all on function public.create_finance_guided_demo_v26() from public,anon,authenticated,service_role;
alter function public.initialize_finance_guided_scenario(uuid,uuid,uuid) rename to initialize_finance_guided_scenario_v26;
revoke all on function public.initialize_finance_guided_scenario_v26(uuid,uuid,uuid) from public,anon,authenticated,service_role;
alter function public.finish_finance_guided_scenario(uuid,uuid,uuid) rename to finish_finance_guided_scenario_v26;
revoke all on function public.finish_finance_guided_scenario_v26(uuid,uuid,uuid) from public,anon,authenticated,service_role;


create or replace function public.assert_finance_guided_owner(p_organization_id uuid,p_run_id uuid,p_actor_id uuid) returns jsonb
language plpgsql security definer set search_path=public,pg_temp as $$
declare r demo_runs;
begin
 perform assert_finance_demo_owner(p_organization_id,p_run_id,p_actor_id);
 select * into strict r from demo_runs where organization_id=p_organization_id and id=p_run_id;
 if coalesce(r.scenario->>'id','') not in ('finney-mid-event-v1','finney-photo-booth-v1') or r.currency<>'USD' then
 raise exception 'dedicated guided scenario required' using errcode='42501'; end if;
 return r.scenario;
end $$;

create or replace function public.finance_guided_seed_state(p_organization_id uuid,p_run_id uuid) returns jsonb
language plpgsql security definer set search_path=public,pg_temp as $$
declare r demo_runs; latest jobs; attempts integer;
begin
 if coalesce(auth.role(),'')<>'service_role' then perform finance_require_scope(p_organization_id,p_run_id); end if;
 select * into strict r from demo_runs where organization_id=p_organization_id and id=p_run_id;
 if coalesce(r.scenario->>'id','') not in ('finney-mid-event-v1','finney-photo-booth-v1') then return '{}'::jsonb; end if;
 select count(*) into attempts from jobs where organization_id=p_organization_id and run_id=p_run_id
 and command_type='intake' and payload=jsonb_build_object('source','demo_bundle','bundle_version',r.scenario->>'id');
 -- Prefer an existing live seed even when older terminal history remains.
 select * into latest from jobs where organization_id=p_organization_id and run_id=p_run_id
 and command_type='intake' and payload=jsonb_build_object('source','demo_bundle','bundle_version',r.scenario->>'id')
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
 and (expires_at is null or expires_at>now()) and scenario->>'id'='finney-photo-booth-v1' order by created_at desc limit 1;
 if not found then
 scope:=create_finance_demo('HarborHacks · five days to go',null);
 update demo_runs set scenario=jsonb_build_object('id','finney-photo-booth-v1','title','HarborHacks',
 'brief','200 attendees. Five days to go. The team is considering a photo booth.',
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
 jsonb_build_object('source','demo_bundle','bundle_version','finney-photo-booth-v1'),seed_key);
 if next_attempt>1 then
 perform finance_audit(r.organization_id,r.id,'guided_seed_retry_requested',jsonb_build_object(
 'previous_job_id',previous_seed,'job_id',seed,'attempt',next_attempt,'attempt_limit',3,'records_reset',false));
 end if;
 seed_state:=finance_guided_seed_state(r.organization_id,r.id);
 end if;
 return jsonb_build_object('organization_id',r.organization_id,'run_id',r.id)||seed_state;
end $$;

create or replace function public.restart_finance_guided_demo(p_previous_run_id uuid) returns jsonb
language plpgsql security definer set search_path=public,pg_temp as $$
declare previous demo_runs; fresh jsonb; next_run uuid; seed uuid;
begin
 if auth.uid() is null or auth.role()<>'authenticated'
 or coalesce(nullif(current_setting('request.jwt.claims',true),'')::jsonb->>'is_anonymous','false')='true'
 then raise exception 'non-anonymous sign in required' using errcode='42501'; end if;
 perform pg_advisory_xact_lock(hashtextextended(auth.uid()::text,0));
 select * into previous from demo_runs where id=p_previous_run_id for update;
 if not found or not previous.is_demo or previous.owner_user_id is distinct from auth.uid()
 or coalesce(previous.scenario->>'id','') not in ('finney-mid-event-v1','finney-photo-booth-v1')
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
 fresh:=create_finance_demo('HarborHacks · five days to go',previous.id);
 next_run:=(fresh->>'run_id')::uuid;
 update demo_runs set scenario=jsonb_build_object('id','finney-photo-booth-v1','title','HarborHacks',
 'brief','200 attendees. Five days to go. The team is considering a photo booth.',
 'experience_version','finney-photo-booth-v1','synthetic',true,'status','preparing','steps','[]'::jsonb)
 where id=next_run and organization_id=previous.organization_id;
 seed:=enqueue_finance_command(previous.organization_id,next_run,'intake',
 jsonb_build_object('source','demo_bundle','bundle_version','finney-photo-booth-v1'),'guided-seed:'||next_run);
 perform finance_audit(previous.organization_id,next_run,'guided_practice_restarted',jsonb_build_object(
 'previous_run_id',previous.id,'seed_job_id',seed,'previous_records_retained',true));
 return fresh||jsonb_build_object('previous_run_id',previous.id,'seed_job_id',seed,'seed_status','queued',
 'experience_version','finney-photo-booth-v1');
end $$;

create function public.initialize_finance_guided_scenario(p_organization_id uuid,p_run_id uuid,p_actor_id uuid) returns jsonb
language plpgsql security definer set search_path=public,pg_temp as $$
declare scenario_state jsonb; s source_items; c cases; line uuid; journal uuid; item record; steps jsonb:='[]';
begin
 scenario_state:=assert_finance_guided_owner(p_organization_id,p_run_id,p_actor_id);
 if scenario_state->>'id'='finney-mid-event-v1' then return initialize_finance_guided_scenario_v26(p_organization_id,p_run_id,p_actor_id); end if;
 if scenario_state->>'status' in ('initialized','ready') then return scenario_state; end if;
 if scenario_state->>'status'<>'preparing' then raise exception 'invalid guided scenario state'; end if;
 -- A designated fresh scenario is the only writable target. Never merge initial
 -- balances with actual records, resumed activity or another visitor's work.
 if exists(select 1 from ledger_transactions where run_id=p_run_id)
 or exists(select 1 from budget_lines where run_id=p_run_id)
 or exists(select 1 from obligations where run_id=p_run_id)
 or exists(select 1 from budget_decisions where run_id=p_run_id)
 or exists(select 1 from action_proposals where run_id=p_run_id)
 or exists(select 1 from payments where run_id=p_run_id)
 or exists(select 1 from demo_runs where id=p_run_id and cash_established)
 or exists(select 1 from cases where run_id=p_run_id and (version<>1 or status<>'open' or data ? 'finding'))
 then raise exception 'guided initialization requires untouched financial state' using errcode='23514'; end if;
 if (select count(*) from source_items where run_id=p_run_id)<>16 or (select count(*) from cases where run_id=p_run_id)<>16 then
 raise exception 'complete isolated initial evidence required' using errcode='23514'; end if;
 for item in select * from (values
('guided_demo:finney-photo-booth-v1:event','9f8624b63a96345a2b48a3f51d99850fda7b5d600194169355a29a59fa71b73e'),
('guided_demo:finney-photo-booth-v1:opening','f6336a9b4fcd30ede9a30bf3ba81f52dcc3aa39c4a054d794bbd16a750c49291'),
('guided_demo:finney-photo-booth-v1:venue','b13701822bb92e832d0e5316967603c0af4cac62cbbb1ffb54970d8d32334979'),
('guided_demo:finney-photo-booth-v1:catering','e85d76b77c93d66c480e1bec0e1414f26b13f67aabdd14901f4fb7d9a60b8788'),
('guided_demo:finney-photo-booth-v1:equipment','08eddc11820df14d870ef001029133604d9158291c46848726ad356e0407a097'),
('guided_demo:finney-photo-booth-v1:printing','03e36b65f4b0b2799b6ed7a114e8185ac5300841c027c1c86f86f8968681950d'),
('guided_demo:finney-photo-booth-v1:catering-thread','635d4492272a7727944f1b9ad7d804541cf7186c0f0f2367ca37979a04ba0a82'),
('guided_demo:finney-photo-booth-v1:catering-reminder','20512187b85247f88ef6d24af3221695dbe826c61dead6a4217ed440114431a6'),
('guided_demo:finney-photo-booth-v1:mira-receipt','6da6de74648b9f0fc83cce649f45cad54be5613046d1f21cf50db69f036f87a7'),
('guided_demo:finney-photo-booth-v1:mira-duplicate','9956da1f0ac83ec1d79ced9f93a141e09953ddc16eb1907520e797cf4b46c4e3'),
('guided_demo:finney-photo-booth-v1:mira-email','f31ef45cf3cc9e6adb56986652f6bfdab20bca912e0a56afac81560e006822a4'),
('guided_demo:finney-photo-booth-v1:sponsor-a','36dc0b3fa107aec17af8bc4412c24afa7bfb769b04919e955c7f16893c08801c'),
('guided_demo:finney-photo-booth-v1:sponsor-b','59e8a7ece8bd2dfd94e727b67745ff7da2a36363d90ac8c4ba2b3a5c48ca9526'),
('guided_demo:finney-photo-booth-v1:team-message','ad36720bd9667c388f774c353ca47b95f10b3fd814de810d7d8313541d765f61'),
('guided_demo:finney-photo-booth-v1:equipment-alternative','9f9efa96d61c02873db482c606b70da05d9ea17ecb86d8a162053fcf38e80ec6'),
('guided_demo:finney-photo-booth-v1:photo-booth','ed087e04e2e983113c9fccbb516d9560f349e77e2faa11722258f2ad68cd8753')
 ) expected(external_id,sha) loop
 select * into strict s from source_items where organization_id=p_organization_id and run_id=p_run_id and external_id=item.external_id and version=1;
 if s.source_type<>'guided_demo' or s.content_sha256<>item.sha or s.artifact_path is null then
 raise exception 'guided evidence mismatch' using errcode='23514'; end if;
 end loop;
 insert into ledger_transactions(organization_id,run_id,description,idempotency_key)
 values(p_organization_id,p_run_id,'Synthetic scenario opening balance; not bank-confirmed','guided-opening:finney-photo-booth-v1') returning id into journal;
 insert into ledger_entries(organization_id,run_id,transaction_id,account,currency,amount_minor) values
 (p_organization_id,p_run_id,journal,'cash','USD',620000),(p_organization_id,p_run_id,journal,'scenario_opening_equity','USD',-620000);
 for item in select * from (values('Venue',250000),('Catering',180000),('Equipment',90000),('Printing',30000),('Unallocated',70000)) b(name,amount) loop
 insert into budget_lines(organization_id,run_id,name,currency,allocated_minor) values(p_organization_id,p_run_id,item.name,'USD',item.amount);
 end loop;
 for item in select * from (values
 ('venue','Harbor Hall · venue balance','payable',250000,'Venue','2026-10-29'),
 ('catering','Juniper Kitchen · catering order','payable',180000,'Catering','2026-10-29'),
 ('equipment','Harbor Equipment · confirmed equipment','payable',90000,'Equipment','2026-10-29'),
 ('printing','Paper Harbor · printing order','payable',30000,'Printing','2026-10-29')
 ) o(key,title,direction,amount,budget,due) loop
 select * into strict s from source_items where run_id=p_run_id and external_id='guided_demo:finney-photo-booth-v1:'||item.key and version=1;
 select * into strict c from cases where run_id=p_run_id and data->>'source_external_id'=s.external_id;
 select id into line from budget_lines where run_id=p_run_id and name=item.budget;
 insert into obligations(organization_id,run_id,case_id,budget_line_id,title,direction,amount_minor,currency,due_date,evidence_status,source_refs)
 values(p_organization_id,p_run_id,c.id,line,item.title,item.direction,item.amount,'USD',item.due::date,'reported',jsonb_build_array(jsonb_build_object('id',s.id,'version',1)));
 end loop;
 -- Cases carry provenance rather than invented findings/completed reviews.
 update cases set data=data||jsonb_build_object('synthetic',true,'scenario_id','finney-photo-booth-v1','initial_condition',true)
 where run_id=p_run_id;
 select * into strict c from cases where run_id=p_run_id and data->>'source_external_id'='guided_demo:finney-photo-booth-v1:event';
 steps:=jsonb_build_array(jsonb_build_object('id','review','title','Can we afford the photo booth?','case_id',c.id,'prompt','The team thinks sponsorship covers the photo booth. Review the latest documents, resolve what you can, and tell me what we can actually commit to—and what needs my decision. Don’t commit to the purchase.'));
 update demo_runs set cash_established=true,cash_evidence_status='synthetic_scenario',reconciled_at=null,revision=revision+1,
 scenario=scenario||jsonb_build_object('status','initialized','steps',steps,'opening_cash_minor','620000','initial_committed_minor','550000')
 where id=p_run_id returning scenario into scenario_state;
 perform finance_audit(p_organization_id,p_run_id,'guided_scenario_initialized',jsonb_build_object('scenario_id','finney-photo-booth-v1','synthetic',true,'financial_records','initial_conditions_only','opening_cash_minor','620000','provider_confirmed',false));
 return scenario_state;
end $$;

create function public.finish_finance_guided_scenario(p_organization_id uuid,p_run_id uuid,p_actor_id uuid) returns jsonb
language plpgsql security definer set search_path=public,pg_temp as $$
declare scenario_state jsonb; current_ids jsonb; old_ids jsonb;
begin
 scenario_state:=assert_finance_guided_owner(p_organization_id,p_run_id,p_actor_id);
 if scenario_state->>'id'='finney-mid-event-v1' then return finish_finance_guided_scenario_v26(p_organization_id,p_run_id,p_actor_id); end if;
 if scenario_state->>'status'='ready' then return scenario_state; end if;
 if scenario_state->>'status'<>'initialized' or not exists(select 1 from source_items where organization_id=p_organization_id and run_id=p_run_id
 and external_id='guided_demo:finney-photo-booth-v1:catering' and version=2 and content_sha256='30c339985792bb2cd166ecae6dd268057cf2c875d132dfc3ca9faaf2e720bd27') then
 raise exception 'guided amendment missing' using errcode='23514'; end if;
 select jsonb_agg(s.id order by s.external_id) into current_ids from source_items s
 where s.organization_id=p_organization_id and s.run_id=p_run_id and not exists(select 1 from source_items newer
 where newer.organization_id=s.organization_id and newer.run_id=s.run_id and newer.external_id=s.external_id and newer.version>s.version);
 select jsonb_agg(id order by version) into old_ids from source_items where organization_id=p_organization_id and run_id=p_run_id
 and external_id='guided_demo:finney-photo-booth-v1:catering' and version<2;
 update cases set data=data||jsonb_build_object('source_ids',current_ids,'superseded_source_ids',old_ids,
 'workflow','budget cash vendor invoice organizer expenses reimburse sponsor report'),version=version+1,updated_at=now()
 where organization_id=p_organization_id and run_id=p_run_id and data->>'source_external_id'='guided_demo:finney-photo-booth-v1:event';
 update demo_runs set scenario=scenario||jsonb_build_object('status','ready') where id=p_run_id returning scenario into scenario_state;
 perform finance_audit(p_organization_id,p_run_id,'guided_scenario_ready',jsonb_build_object('synthetic',true,'model_outputs_seeded',false));
 return scenario_state;
end $$;

alter function public.get_finance_snapshot(uuid,uuid) rename to get_finance_snapshot_v26;
revoke all on function public.get_finance_snapshot_v26(uuid,uuid) from public,anon,authenticated,service_role;
create function public.get_finance_snapshot(p_organization_id uuid,p_run_id uuid) returns jsonb
language plpgsql security definer set search_path=public,pg_temp as $$
declare result jsonb;
begin
 result:=get_finance_snapshot_v26(p_organization_id,p_run_id);
 if result->'run'->'scenario'->>'id'='finney-photo-booth-v1' then
 result:=jsonb_set(result,'{run,scenario}',result->'run'->'scenario'||finance_guided_seed_state(p_organization_id,p_run_id)); end if;
 return result;
end $$;


revoke all on function public.assert_finance_guided_owner(uuid,uuid,uuid),public.initialize_finance_guided_scenario(uuid,uuid,uuid),public.finish_finance_guided_scenario(uuid,uuid,uuid),public.get_finance_snapshot(uuid,uuid) from public,anon,authenticated,service_role;
grant execute on function public.assert_finance_guided_owner(uuid,uuid,uuid),public.initialize_finance_guided_scenario(uuid,uuid,uuid),public.finish_finance_guided_scenario(uuid,uuid,uuid) to service_role;
grant execute on function public.get_finance_snapshot(uuid,uuid) to authenticated,service_role;
-- CREATE OR REPLACE retained owner-only grants on restart and seed-state.
revoke all on function public.create_finance_guided_demo() from public,anon,authenticated,service_role;
grant execute on function public.create_finance_guided_demo() to authenticated;
commit;
