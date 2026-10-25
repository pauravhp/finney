begin;

create table public.budget_decisions (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null, run_id uuid not null,
 budget_line_id uuid not null, expected_version integer, name text not null,
 allocated_minor bigint not null check(allocated_minor>=0), currency text not null,
 rationale text not null, run_revision bigint not null,
 status text not null default 'pending' check(status in ('pending','approved','rejected','stale')),
 decided_by uuid references auth.users(id), decided_at timestamptz,
 idempotency_key text not null, request_hash text not null, created_at timestamptz not null default now(),
 unique(organization_id,run_id,idempotency_key),
 foreign key(organization_id,run_id) references public.demo_runs(organization_id,id)
);
alter table public.budget_decisions enable row level security;
create policy budget_decision_read on public.budget_decisions for select to authenticated
 using(public.finance_can_access(organization_id,run_id));
revoke all on public.budget_decisions from public,anon,authenticated,service_role;
grant select on public.budget_decisions to authenticated,service_role;

create function public.get_finance_budget(p_organization_id uuid,p_run_id uuid) returns jsonb
language plpgsql security definer set search_path=public,pg_temp as $$
declare selected_run demo_runs;
begin
 if coalesce(auth.role(),'')<>'service_role' then perform finance_require_scope(p_organization_id,p_run_id); end if;
 select * into strict selected_run from demo_runs where organization_id=p_organization_id and id=p_run_id;
 return jsonb_build_object('lines',coalesce((select jsonb_agg(jsonb_build_object(
 'id',b.id,'name',b.name,'currency',b.currency,'allocated_minor',b.allocated_minor::text,'version',b.version,
 'committed_minor',coalesce(o.committed,0)::text,'remaining_minor',(b.allocated_minor-coalesce(o.committed,0))::text))
 from budget_lines b left join lateral (select sum(amount_minor) committed from obligations o
 where o.organization_id=b.organization_id and o.run_id=b.run_id and o.budget_line_id=b.id
 and o.direction='payable' and o.status<>'cancelled') o on true
 where b.organization_id=p_organization_id and b.run_id=p_run_id),'[]'),
 'decisions',coalesce((select jsonb_agg(to_jsonb(d)||jsonb_build_object('allocated_minor',d.allocated_minor::text,
 'status',case when d.status='pending' and d.run_revision<>r.revision then 'stale' else d.status end) order by d.created_at desc)
 from budget_decisions d join demo_runs r on r.id=d.run_id
 where d.organization_id=p_organization_id and d.run_id=p_run_id),'[]'));
end $$;

create function public.propose_finance_budget(p_organization_id uuid,p_run_id uuid,p_arguments jsonb) returns jsonb
language plpgsql security definer set search_path=public,pg_temp as $$
declare r demo_runs; b budget_lines; d budget_decisions; line_id uuid; version integer; label text; amount bigint; fingerprint text;
begin
 if coalesce(auth.role(),'')<>'service_role' then perform finance_require_scope(p_organization_id,p_run_id,array['director','finance']); end if;
 perform finance_lock_run(p_organization_id,p_run_id);
 if jsonb_typeof(p_arguments) is distinct from 'object' or p_arguments - array['budget_line_id','expected_version','new_name','allocated_minor','rationale','idempotency_key'] <> '{}'::jsonb
 or coalesce(p_arguments->>'allocated_minor','')!~'^[0-9]+$'
 or jsonb_typeof(p_arguments->'rationale') is distinct from 'string' or length(trim(coalesce(p_arguments->>'rationale',''))) not between 1 and 2000
 or jsonb_typeof(p_arguments->'idempotency_key') is distinct from 'string'
 or length(coalesce(p_arguments->>'idempotency_key','')) not between 8 and 200
 then raise exception 'invalid budget proposal' using errcode='22023'; end if;
 if length(p_arguments->>'allocated_minor')>19 or (p_arguments->>'allocated_minor')::numeric>9000000000000000000 then
 raise exception 'budget amount exceeds supported exact range' using errcode='22023'; end if;
 if p_arguments ? 'new_name' and (jsonb_typeof(p_arguments->'new_name') is distinct from 'string' or length(trim(p_arguments->>'new_name')) not between 1 and 120) then
 raise exception 'budget name required' using errcode='22023'; end if;
 if p_arguments ? 'budget_line_id' and (jsonb_typeof(p_arguments->'budget_line_id') is distinct from 'string'
 or coalesce(p_arguments->>'budget_line_id','') !~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
 or jsonb_typeof(p_arguments->'expected_version') is distinct from 'number' or coalesce(p_arguments->>'expected_version','') !~ '^[1-9][0-9]{0,8}$') then
 raise exception 'budget line and exact positive version required' using errcode='22023'; end if;
 amount:=(p_arguments->>'allocated_minor')::bigint;
 fingerprint:=encode(extensions.digest(finance_json_money_strings(p_arguments)::text,'sha256'),'hex');
 select * into r from demo_runs where organization_id=p_organization_id and id=p_run_id;
 select * into d from budget_decisions where organization_id=p_organization_id and run_id=p_run_id and idempotency_key=p_arguments->>'idempotency_key';
 if found then
 if d.request_hash is distinct from fingerprint then raise exception 'budget idempotency conflict' using errcode='23505'; end if;
 return finance_json_money_strings(to_jsonb(d)); end if;
 if p_arguments ? 'budget_line_id' then
 select * into strict b from budget_lines where organization_id=p_organization_id and run_id=p_run_id and id=(p_arguments->>'budget_line_id')::uuid;
 if b.version is distinct from (p_arguments->>'expected_version')::integer then raise exception 'budget version changed' using errcode='40001'; end if;
 line_id:=b.id; version:=b.version; label:=coalesce(trim(p_arguments->>'new_name'),b.name);
 else
 if p_arguments ? 'expected_version' then raise exception 'new budget has no previous version' using errcode='22023'; end if;
 line_id:=gen_random_uuid(); label:=trim(p_arguments->>'new_name');
 end if;
 if label is null or length(label) not between 1 and 120 then raise exception 'budget name required' using errcode='22023'; end if;
 insert into budget_decisions(organization_id,run_id,budget_line_id,expected_version,name,allocated_minor,currency,rationale,run_revision,idempotency_key,request_hash)
 values(p_organization_id,p_run_id,line_id,version,label,amount,r.currency,p_arguments->>'rationale',r.revision,p_arguments->>'idempotency_key',fingerprint) returning * into d;
 perform finance_audit(p_organization_id,p_run_id,'budget_change_proposed',jsonb_build_object('decision_id',d.id,'name',label,'allocated_minor',amount::text));
 return finance_json_money_strings(to_jsonb(d));
end $$;

create function public.decide_finance_budget(p_organization_id uuid,p_run_id uuid,p_decision_id uuid,p_decision text) returns jsonb
language plpgsql security definer set search_path=public,pg_temp as $$
declare r demo_runs; d budget_decisions; spent numeric;
begin
 if auth.role() is distinct from 'authenticated' or auth.uid() is null then raise exception 'authenticated director required' using errcode='42501'; end if;
 perform finance_require_scope(p_organization_id,p_run_id,array['director']);
 perform finance_lock_run(p_organization_id,p_run_id);
 perform finance_require_scope(p_organization_id,p_run_id,array['director']);
 if p_decision is null or p_decision not in ('approve','reject') then raise exception 'invalid budget decision' using errcode='22023'; end if;
 select * into strict d from budget_decisions where organization_id=p_organization_id and run_id=p_run_id and id=p_decision_id for update;
 if d.status=(case when p_decision='approve' then 'approved' else 'rejected' end) then return finance_json_money_strings(to_jsonb(d)); end if;
 if d.status<>'pending' then raise exception 'budget decision is no longer pending' using errcode='40001'; end if;
 select * into r from demo_runs where organization_id=p_organization_id and id=p_run_id;
 if p_decision='approve' then
 if d.run_revision<>r.revision then raise exception 'event changed; review budget again' using errcode='40001'; end if;
 if exists(select 1 from payments where organization_id=p_organization_id and run_id=p_run_id and status in ('reserved','submitting','uncertain','submitted')) then
 raise exception 'payment in progress; budget cannot change' using errcode='40001'; end if;
 select coalesce(sum(amount_minor),0) into spent from obligations where organization_id=p_organization_id and run_id=p_run_id and budget_line_id=d.budget_line_id and direction='payable' and status<>'cancelled';
 if spent>d.allocated_minor then raise exception 'allocation below existing commitments' using errcode='22023'; end if;
 if d.expected_version is null then
 insert into budget_lines(id,organization_id,run_id,name,currency,allocated_minor) values(d.budget_line_id,p_organization_id,p_run_id,d.name,d.currency,d.allocated_minor);
 else
 update budget_lines set name=d.name,allocated_minor=d.allocated_minor,version=version+1 where organization_id=p_organization_id and run_id=p_run_id and id=d.budget_line_id and version=d.expected_version;
 if not found then raise exception 'budget version changed' using errcode='40001'; end if;
 end if;
 update demo_runs set revision=revision+1,updated_at=now() where organization_id=p_organization_id and id=p_run_id;
 update action_proposals set status='stale' where organization_id=p_organization_id and run_id=p_run_id and status='pending';
 end if;
 update budget_decisions set status=case when p_decision='approve' then 'approved' else 'rejected' end,decided_by=auth.uid(),decided_at=now() where id=d.id returning * into d;
 perform finance_audit(p_organization_id,p_run_id,'budget_change_'||d.status,jsonb_build_object('decision_id',d.id,'budget_line_id',d.budget_line_id));
 return finance_json_money_strings(to_jsonb(d));
end $$;

alter function public.get_finance_snapshot(uuid,uuid) rename to get_finance_snapshot_v9;
revoke all on function public.get_finance_snapshot_v9(uuid,uuid) from public,anon,authenticated,service_role;
create function public.get_finance_snapshot(p_organization_id uuid,p_run_id uuid) returns jsonb
language plpgsql security definer set search_path=public,pg_temp as $$
begin
 return get_finance_snapshot_v9(p_organization_id,p_run_id)||jsonb_build_object('budget',get_finance_budget(p_organization_id,p_run_id));
end $$;

-- Only this additional command is new; the previous RPC still validates every existing command.
alter table public.jobs add column request_payload jsonb;
alter function public.enqueue_finance_command(uuid,uuid,text,jsonb,text) rename to enqueue_finance_command_v9;
revoke all on function public.enqueue_finance_command_v9(uuid,uuid,text,jsonb,text) from public,anon,authenticated,service_role;
create function public.enqueue_finance_command(p_organization_id uuid,p_run_id uuid,p_command_type text,p_payload jsonb,p_idempotency_key text) returns uuid
language plpgsql security definer set search_path=public,pg_temp as $$
declare j jobs;
begin
 if p_command_type is distinct from 'director_message' then return enqueue_finance_command_v9(p_organization_id,p_run_id,p_command_type,p_payload,p_idempotency_key); end if;
 perform finance_require_scope(p_organization_id,p_run_id,array['director','finance']); perform finance_lock_run(p_organization_id,p_run_id);
 if jsonb_typeof(p_payload) is distinct from 'object' or p_payload-array['message','case_id']<>'{}'::jsonb or jsonb_typeof(p_payload->'message') is distinct from 'string'
 or length(trim(coalesce(p_payload->>'message',''))) not between 1 and 4000 or length(coalesce(p_idempotency_key,'')) not between 8 and 200 then raise exception 'invalid director message' using errcode='22023'; end if;
 if p_payload ? 'case_id' and (jsonb_typeof(p_payload->'case_id') is distinct from 'string' or coalesce(p_payload->>'case_id','') !~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$') then
 raise exception 'invalid director message case' using errcode='22023'; end if;
 if p_payload ? 'case_id' and not exists(select 1 from cases where organization_id=p_organization_id and run_id=p_run_id and id=(p_payload->>'case_id')::uuid) then raise exception 'case scope denied' using errcode='42501'; end if;
 select * into j from jobs where organization_id=p_organization_id and run_id=p_run_id and idempotency_key=p_idempotency_key;
 if found then if j.command_type<>p_command_type or coalesce(j.request_payload,j.payload)<>p_payload then raise exception 'idempotency conflict' using errcode='23505'; end if; return j.id; end if;
 insert into jobs(organization_id,run_id,command_type,payload,request_payload,requested_by,idempotency_key) values(p_organization_id,p_run_id,p_command_type,p_payload,p_payload,auth.uid(),p_idempotency_key) returning * into j;
 perform finance_audit(p_organization_id,p_run_id,'director_message_queued',jsonb_build_object('job_id',j.id)); return j.id;
end $$;

-- Budget revisions affect payment authority, independently of actor reasoning.
create function public.finance_require_budget_capacity(p_org uuid,p_run uuid) returns void
language plpgsql security definer set search_path=public,pg_temp as $$
begin
 if not exists(select 1 from budget_lines where organization_id=p_org and run_id=p_run) then return; end if;
 if exists(select 1 from obligations o left join budget_lines b on b.id=o.budget_line_id
 and b.organization_id=o.organization_id and b.run_id=o.run_id and b.currency=o.currency
 where o.organization_id=p_org and o.run_id=p_run and o.direction='payable' and o.status<>'cancelled'
 and o.amount_minor>0 and b.id is null) then
 raise exception 'assign every payable to a current event budget before payment' using errcode='23514'; end if;
 if exists(select 1 from budget_lines b join obligations o on o.organization_id=b.organization_id and o.run_id=b.run_id and o.budget_line_id=b.id
 where b.organization_id=p_org and b.run_id=p_run and o.direction='payable' and o.status<>'cancelled'
 group by b.id,b.allocated_minor having sum(o.amount_minor)>b.allocated_minor) then
 raise exception 'budget commitments exceed approved allocation' using errcode='23514'; end if;
end $$;

alter function public.finance_kernel_call(uuid,uuid,text,jsonb) rename to finance_kernel_call_v9;
revoke all on function public.finance_kernel_call_v9(uuid,uuid,text,jsonb) from public,anon,authenticated,service_role;
create function public.finance_kernel_call(p_organization_id uuid,p_run_id uuid,p_operation text,p_arguments jsonb) returns jsonb
language plpgsql security definer set search_path=public,pg_temp as $$
declare previous obligations; result jsonb; budget_id uuid;
begin
 perform finance_require_service();perform finance_lock_run(p_organization_id,p_run_id);
 if p_operation='propose_obligation_update' then
 select * into previous from obligations where organization_id=p_organization_id and run_id=p_run_id and id=(p_arguments->>'id')::uuid;
 if previous.id is not null and p_arguments->>'direction' is distinct from previous.direction then
 raise exception 'existing obligation direction is immutable' using errcode='23514'; end if;
 if p_arguments ? 'budget_line_id' and p_arguments->'budget_line_id'<>'null'::jsonb then
 budget_id:=(p_arguments->>'budget_line_id')::uuid;
 if not exists(select 1 from budget_lines b join demo_runs r on r.organization_id=b.organization_id and r.id=b.run_id
 where b.organization_id=p_organization_id and b.run_id=p_run_id and b.id=budget_id and b.currency=r.currency) then
 raise exception 'budget line outside event run or currency' using errcode='23514'; end if;
 end if;
 end if;
 if p_operation in ('create_approval_request','reserve_approved_payment') or (p_operation='transition_payment' and p_arguments->>'status'='submitting') then
 perform finance_require_budget_capacity(p_organization_id,p_run_id);
 end if;
 result:=finance_kernel_call_v9(p_organization_id,p_run_id,p_operation,p_arguments);
 if p_operation='propose_obligation_update' and p_arguments ? 'budget_line_id' and previous.id is not null then
 -- v8 applies monetary/source updates but historically ignored budget relinking.
 -- Apply it in the same locked transaction/version, never on a historical replay.
 update obligations set budget_line_id=budget_id where id=previous.id and organization_id=p_organization_id and run_id=p_run_id
 and version=(result->>'version')::integer and version>previous.version;
 end if;
 return result;
end $$;

-- Director messages retain the same exact trace/job/case persistence guards.
create or replace function public.record_finance_case_review(
 p_organization_id uuid,p_run_id uuid,p_case_id uuid,p_expected_version integer,p_expected_source_ids uuid[],
 p_trace_id uuid,p_job_id uuid,p_finding jsonb,p_idempotency_key text
) returns jsonb language plpgsql security definer set search_path=public,extensions,pg_temp as $$
declare c cases;t trace_events;prior finance_operations;fingerprint text;result jsonb;actual jsonb;finding jsonb;case_data jsonb;new_status text;review_trace uuid;
begin
 perform finance_require_service();perform finance_lock_run(p_organization_id,p_run_id);
 if p_idempotency_key is distinct from 'case-review:'||p_job_id::text then raise exception 'stable review job key required' using errcode='22023';end if;
 fingerprint:=encode(digest(jsonb_build_object('case_id',p_case_id,'expected_version',p_expected_version,'expected_source_ids',p_expected_source_ids,
 'trace_id',p_trace_id,'job_id',p_job_id,'finding',p_finding)::text,'sha256'),'hex');
 select * into prior from finance_operations where organization_id=p_organization_id and run_id=p_run_id and idempotency_key=p_idempotency_key;
 if found then
 if prior.operation<>'record_case_review' or prior.request_hash<>fingerprint then raise exception 'idempotency key conflict' using errcode='23505';end if;return prior.result;
 end if;
 select * into strict c from cases where organization_id=p_organization_id and run_id=p_run_id and id=p_case_id for update;
 if c.version is distinct from p_expected_version or coalesce(c.data->'source_ids','[]') is distinct from to_jsonb(p_expected_source_ids)
 then raise exception 'case context changed' using errcode='40001';end if;
 select * into strict t from trace_events where organization_id=p_organization_id and run_id=p_run_id and id=p_trace_id;
 if t.event_type<>'actor_completed' or t.payload->>'job_id' is distinct from p_job_id::text or coalesce(t.payload->>'skill_version','')=''
 or not exists(select 1 from jobs j where j.organization_id=p_organization_id and j.run_id=p_run_id and j.id=p_job_id and j.command_type in ('review_case','director_message') and j.payload->>'case_id'=p_case_id::text)
 then raise exception 'actual scoped actor trace and review job required' using errcode='23514';end if;
 actual:=t.payload->'output';
 if jsonb_typeof(actual) is distinct from 'object' or coalesce(actual->>'decision','') !~ '^[a-z][a-z0-9_]{0,79}$'
 or jsonb_typeof(actual->'evidence_source_ids') is distinct from 'array'
 or p_finding->>'decision' is distinct from actual->>'decision'
 or p_finding->'evidence_source_ids' is distinct from actual->'evidence_source_ids'
 or p_finding->'clarification' is distinct from coalesce(actual->'clarification','null')
 or p_finding->'proposed_action' is distinct from finance_json_money_strings(coalesce(actual->'proposed_action','null'))
 or p_finding->>'explanation' is distinct from actual->>'explanation'
 or p_finding->'blocking_requirements' is distinct from coalesce(actual->'blocking_requirements','[]')
 then raise exception 'prepared review does not match actual output' using errcode='23514';end if;
 if exists(select 1 from jsonb_array_elements_text(p_finding->'evidence_source_ids') x where not exists(
 select 1 from source_items s where s.organization_id=p_organization_id and s.run_id=p_run_id and s.id::text=x))
 or exists(select 1 from jsonb_array_elements(coalesce(p_finding->'proposed_action'->'evidence_refs','[]')) x where not exists(
 select 1 from source_items s where s.organization_id=p_organization_id and s.run_id=p_run_id and s.id::text=x->>'id' and s.version=(x->>'version')::int))
 then raise exception 'review citation outside scope or version' using errcode='23514';end if;
 finding:=p_finding||jsonb_build_object('kind','prepared_agent_review','verification','unverified_model_recommendation','effects_completed',false,
 'provenance',coalesce(p_finding->'provenance','{}')||jsonb_build_object('job_id',p_job_id,'actor_trace_id',t.id,'skill_version_id',t.payload->>'skill_version'));
 case_data:=c.data;
 if case_data ? 'finding' then case_data:=case_data||jsonb_build_object('superseded_findings',coalesce(case_data->'superseded_findings','[]')||jsonb_build_array(case_data->'finding'));end if;
 case_data:=case_data||jsonb_build_object('finding',finding);
 new_status:=case when c.status='closed' then 'closed' when coalesce(finding->>'clarification','')<>'' or jsonb_array_length(coalesce(finding->'blocking_requirements','[]'))>0 then 'awaiting_evidence' else 'needs_human_review' end;
 update cases set data=case_data,status=new_status,version=version+1,updated_at=now() where id=c.id and organization_id=p_organization_id and run_id=p_run_id;
 insert into trace_events(organization_id,run_id,case_id,event_type,payload,idempotency_key)
 values(p_organization_id,p_run_id,c.id,'case_review_persisted',jsonb_build_object('job_id',p_job_id,'actor_trace_id',t.id,'skill_version',t.payload->>'skill_version',
 'case_id',c.id,'case_version',c.version+1,'status',new_status,'verification','unverified_model_recommendation'),'case-review-recorded:'||p_job_id) returning id into review_trace;
 result:=jsonb_build_object('status','persisted','case_id',c.id,'version',c.version+1,'case_status',new_status,'review_trace_id',review_trace);
 insert into finance_operations(organization_id,run_id,idempotency_key,operation,request_hash,result)
 values(p_organization_id,p_run_id,p_idempotency_key,'record_case_review',fingerprint,result);
 perform finance_audit(p_organization_id,p_run_id,'case_review_persisted',jsonb_build_object('case_id',c.id,'actor_trace_id',t.id,'status',new_status));
 return result;
end $$;

-- Browser uploads may create originals only in their own active run's staging prefix.
create policy finance_owned_upload on storage.objects for insert to authenticated with check (
 bucket_id='finance-artifacts' and (storage.foldername(name))[3]='uploads'
 and name !~ '(^|/)[.]{1,2}(/|$)' and name !~ '//' and right(name,1)<>'/'
 and exists(select 1 from public.demo_runs r join public.memberships m on m.organization_id=r.organization_id
 where r.organization_id::text=(storage.foldername(storage.objects.name))[1] and r.id::text=(storage.foldername(storage.objects.name))[2]
 and r.status='active' and (r.expires_at is null or r.expires_at>now()) and m.user_id=(select auth.uid()) and m.active
 and m.role in ('director','finance') and (not r.is_demo or r.owner_user_id=(select auth.uid())))
);

revoke all on function public.get_finance_budget(uuid,uuid),public.propose_finance_budget(uuid,uuid,jsonb),public.decide_finance_budget(uuid,uuid,uuid,text),public.get_finance_snapshot(uuid,uuid),public.enqueue_finance_command(uuid,uuid,text,jsonb,text) from public,anon,authenticated,service_role;
grant execute on function public.get_finance_budget(uuid,uuid),public.propose_finance_budget(uuid,uuid,jsonb),public.get_finance_snapshot(uuid,uuid) to authenticated,service_role;
grant execute on function public.decide_finance_budget(uuid,uuid,uuid,text),public.enqueue_finance_command(uuid,uuid,text,jsonb,text) to authenticated;
revoke all on function public.finance_require_budget_capacity(uuid,uuid),public.finance_kernel_call(uuid,uuid,text,jsonb) from public,anon,authenticated,service_role;
grant execute on function public.finance_kernel_call(uuid,uuid,text,jsonb) to service_role;
commit;
