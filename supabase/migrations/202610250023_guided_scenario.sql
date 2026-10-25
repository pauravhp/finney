-- Fixed synthetic opening conditions in a dedicated, owner-isolated demo run.
-- No human/provider approval, model findings or learning results are fabricated.
begin;
alter table public.demo_runs add column scenario jsonb;

create function public.create_finance_guided_demo() returns jsonb
language plpgsql security definer set search_path=public,pg_temp as $$
declare r demo_runs; scope jsonb; seed uuid;
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
 seed:=enqueue_finance_command(r.organization_id,r.id,'intake',
 jsonb_build_object('source','demo_bundle','bundle_version','finney-mid-event-v1'),'guided-seed:'||r.id);
 return jsonb_build_object('organization_id',r.organization_id,'run_id',r.id,'seed_job_id',seed,
 'seed_status',case when r.scenario->>'status'='ready' then 'ready' else 'queued' end);
end $$;

create function public.assert_finance_guided_owner(p_organization_id uuid,p_run_id uuid,p_actor_id uuid) returns jsonb
language plpgsql security definer set search_path=public,pg_temp as $$
declare r demo_runs;
begin
 perform assert_finance_demo_owner(p_organization_id,p_run_id,p_actor_id);
 select * into strict r from demo_runs where organization_id=p_organization_id and id=p_run_id;
 if r.scenario->>'id' is distinct from 'finney-mid-event-v1' or r.currency<>'USD' then
 raise exception 'dedicated guided scenario required' using errcode='42501'; end if;
 return r.scenario;
end $$;

create function public.initialize_finance_guided_scenario(p_organization_id uuid,p_run_id uuid,p_actor_id uuid) returns jsonb
language plpgsql security definer set search_path=public,pg_temp as $$
declare scenario_state jsonb; s source_items; c cases; line uuid; journal uuid; item record; steps jsonb:='[]';
begin
 scenario_state:=assert_finance_guided_owner(p_organization_id,p_run_id,p_actor_id);
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
 if (select count(*) from source_items where run_id=p_run_id)<>6 or (select count(*) from cases where run_id=p_run_id)<>6 then
 raise exception 'complete isolated initial evidence required' using errcode='23514'; end if;
 for item in select * from (values
('guided_demo:finney-mid-event-v1:opening','947b01f0b3bfa8c1fc55c4ecb7a4d16cd72941b95116f175bf0eb9bbf696cc35'),
('guided_demo:finney-mid-event-v1:venue','1871ccc34ec9d04c642f2d706943c9a972e70e65e72642aa25de7d86d8f21d47'),
('guided_demo:finney-mid-event-v1:catering','2d844fa91dbb74c3310073570db5fcc397e687b46ee7a1b2034699117e63e9c3'),
('guided_demo:finney-mid-event-v1:av','4da8c7a145d41e4ac9568844d19fe162e4467874cb1fa061f787e5b7716c7340'),
('guided_demo:finney-mid-event-v1:organizer','217a87a2c867fe9c7fc4b5b2308699f21c86176f82d2c9667c30571cbd0e3b1f'),
('guided_demo:finney-mid-event-v1:sponsor','f3b811c36939413723217c626881750d6065c54332c0cf491abfafd12f22c2ba')
 ) expected(external_id,sha) loop
 select * into strict s from source_items where organization_id=p_organization_id and run_id=p_run_id and external_id=item.external_id and version=1;
 if s.source_type<>'guided_demo' or s.content_sha256<>item.sha or s.artifact_path is null then
 raise exception 'guided evidence mismatch' using errcode='23514'; end if;
 end loop;
 insert into ledger_transactions(organization_id,run_id,description,idempotency_key)
 values(p_organization_id,p_run_id,'Synthetic scenario opening balance; not bank-confirmed','guided-opening:finney-mid-event-v1') returning id into journal;
 insert into ledger_entries(organization_id,run_id,transaction_id,account,currency,amount_minor) values
 (p_organization_id,p_run_id,journal,'cash','USD',780000),(p_organization_id,p_run_id,journal,'scenario_opening_equity','USD',-780000);
 for item in select * from (values('Venue',300000),('Food',250000),('AV',80000),('Contingency',150000)) b(name,amount) loop
 insert into budget_lines(organization_id,run_id,name,currency,allocated_minor) values(p_organization_id,p_run_id,item.name,'USD',item.amount);
 end loop;
 for item in select * from (values
 ('venue','Harbor Hall · venue balance','payable',200000,'Venue','2026-10-29'),
 ('catering','Juniper Kitchen · catering deposit','payable',120000,'Food','2026-10-28'),
 ('av','Harbor AV · equipment rental','payable',48000,'AV','2026-10-28'),
 ('sponsor','North Star Labs · sponsorship','receivable',250000,null,'2026-11-01')
 ) o(key,title,direction,amount,budget,due) loop
 select * into strict s from source_items where run_id=p_run_id and external_id='guided_demo:finney-mid-event-v1:'||item.key and version=1;
 select * into strict c from cases where run_id=p_run_id and data->>'source_external_id'=s.external_id;
 select id into line from budget_lines where run_id=p_run_id and name=item.budget;
 insert into obligations(organization_id,run_id,case_id,budget_line_id,title,direction,amount_minor,currency,due_date,evidence_status,source_refs)
 values(p_organization_id,p_run_id,c.id,line,item.title,item.direction,item.amount,'USD',item.due::date,'reported',jsonb_build_array(jsonb_build_object('id',s.id,'version',1)));
 end loop;
 -- Cases carry provenance rather than invented findings/completed reviews.
 update cases set data=data||jsonb_build_object('synthetic',true,'scenario_id','finney-mid-event-v1','initial_condition',true)
 where run_id=p_run_id;
 select * into strict c from cases where run_id=p_run_id and data->>'source_external_id'='guided_demo:finney-mid-event-v1:av';
 steps:=jsonb_build_array(
 jsonb_build_object('id','catch','title','Catch the changed invoice','case_id',c.id,'prompt','Review the revised Harbor AV invoice against our existing commitment. What changed, and what should we owe? Check for duplicate obligations before updating the same commitment.'),
 jsonb_build_object('id','decide','title','Make the call','case_id',c.id,'prompt','Propose raising our AV budget from $800 to $1,000. Leave the decision to me. If I reject it, keep the existing budget and explain our options.'),
 jsonb_build_object('id','report','title','See where we stand','case_id',(select id from cases where run_id=p_run_id and data->>'source_external_id'='guided_demo:finney-mid-event-v1:organizer'),'prompt','Review Mira’s purchase and duplicate receipt. Record only the supported remaining obligation, distinguish the sponsor pledge from cash, and summarize our event position.'));
 update demo_runs set cash_established=true,cash_evidence_status='synthetic_scenario',reconciled_at=null,revision=revision+1,
 scenario=scenario||jsonb_build_object('status','initialized','steps',steps,'opening_cash_minor','780000','initial_committed_minor','368000','pending_sponsor_minor','250000')
 where id=p_run_id returning scenario into scenario_state;
 perform finance_audit(p_organization_id,p_run_id,'guided_scenario_initialized',jsonb_build_object('scenario_id','finney-mid-event-v1','synthetic',true,'financial_records','initial_conditions_only','opening_cash_minor','780000','provider_confirmed',false));
 return scenario_state;
end $$;

create function public.finish_finance_guided_scenario(p_organization_id uuid,p_run_id uuid,p_actor_id uuid) returns jsonb
language plpgsql security definer set search_path=public,pg_temp as $$
declare scenario_state jsonb;
begin
 scenario_state:=assert_finance_guided_owner(p_organization_id,p_run_id,p_actor_id);
 if scenario_state->>'status'='ready' then return scenario_state; end if;
 if scenario_state->>'status'<>'initialized' or not exists(select 1 from source_items where run_id=p_run_id
 and external_id='guided_demo:finney-mid-event-v1:av' and version=2 and content_sha256='d9f01fd14b0d7b66b35ff6abe22671ba1fe7ccaebd35930d5f77ba1f9076a4d4') then
 raise exception 'guided amendment missing' using errcode='23514'; end if;
 update demo_runs set scenario=scenario||jsonb_build_object('status','ready') where id=p_run_id returning scenario into scenario_state;
 perform finance_audit(p_organization_id,p_run_id,'guided_scenario_ready',jsonb_build_object('synthetic',true,'model_outputs_seeded',false));
 return scenario_state;
end $$;

alter function public.get_finance_snapshot(uuid,uuid) rename to get_finance_snapshot_v22;
revoke all on function public.get_finance_snapshot_v22(uuid,uuid) from public,anon,authenticated,service_role;
create function public.get_finance_snapshot(p_organization_id uuid,p_run_id uuid) returns jsonb
language plpgsql security definer set search_path=public,pg_temp as $$
declare result jsonb; scenario_state jsonb;
begin
 result:=get_finance_snapshot_v22(p_organization_id,p_run_id);
 select scenario into scenario_state from demo_runs where organization_id=p_organization_id and id=p_run_id;
 return jsonb_set(result,'{run}',result->'run'||jsonb_build_object('scenario',scenario_state));
end $$;
revoke all on function public.create_finance_guided_demo(),public.assert_finance_guided_owner(uuid,uuid,uuid),public.initialize_finance_guided_scenario(uuid,uuid,uuid),public.finish_finance_guided_scenario(uuid,uuid,uuid),public.get_finance_snapshot(uuid,uuid) from public,anon,authenticated,service_role;
grant execute on function public.create_finance_guided_demo() to authenticated;
grant execute on function public.assert_finance_guided_owner(uuid,uuid,uuid),public.initialize_finance_guided_scenario(uuid,uuid,uuid),public.finish_finance_guided_scenario(uuid,uuid,uuid) to service_role;
grant execute on function public.get_finance_snapshot(uuid,uuid) to authenticated,service_role;
commit;
