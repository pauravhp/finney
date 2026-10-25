-- Event directors choose one or two human payment approvals. Policy authority
-- stays outside actor/improver tools, and every proposal freezes its policy.
begin;
-- An upgrade must not strand an old-hash payment or reinterpret an external send.
-- Resolve outstanding payments before applying this migration; no remote action
-- is attempted by schema migration.
do $$ begin
 if exists(select 1 from public.payments where status in ('reserved','submitting','uncertain','submitted')) then
 raise exception 'unsettled payments prevent approval policy migration' using errcode='23514';
 end if;
end $$;
alter table public.demo_runs
 add column required_payment_approvals integer not null default 2 check(required_payment_approvals in (1,2)),
 add column approval_policy_version bigint not null default 1 check(approval_policy_version>0);
alter table public.action_proposals
 drop constraint action_proposals_required_approvals_check,
 add constraint action_proposals_required_approvals_check check(required_approvals in (1,2)),
 add column approval_policy_version bigint not null default 1 check(approval_policy_version>0);
-- Previous hashes did not bind the approval policy. Preserve evidence and require
-- new exact proposals, rather than reinterpret any old human approval.
update public.action_proposals set status='stale' where status='pending';

-- The service credential may perform ordinary run bookkeeping, but cannot
-- lower policy via direct table writes or initialize a run outside the default.
create function public.finance_guard_event_approval_policy() returns trigger
language plpgsql set search_path=public,pg_temp as $$
begin
 if tg_op='INSERT' then
 if new.required_payment_approvals<>2 or new.approval_policy_version<>1 then
 raise exception 'approval policy must be configured by authenticated director' using errcode='42501'; end if;
 elsif (new.required_payment_approvals,new.approval_policy_version) is distinct from (old.required_payment_approvals,old.approval_policy_version) then
 if coalesce(auth.role(),'')<>'authenticated' or auth.uid() is null then
 raise exception 'approval policy must be configured by authenticated director' using errcode='42501'; end if;
 perform finance_require_scope(old.organization_id,old.id,array['director']);
 if new.required_payment_approvals=old.required_payment_approvals or new.approval_policy_version<>old.approval_policy_version+1
 or new.revision<>old.revision+1 then
 raise exception 'approval policy version and revision must advance atomically' using errcode='23514'; end if;
 if exists(select 1 from payments where organization_id=old.organization_id and run_id=old.id
 and status in ('reserved','submitting','uncertain','submitted')) then
 raise exception 'unsettled payments prevent approval policy change' using errcode='23514'; end if;
 end if;
 return new;
end $$;
create trigger guard_event_approval_policy before insert or update on public.demo_runs
for each row execute function public.finance_guard_event_approval_policy();

create function public.finance_payment_action_hash(p_organization_id uuid,p_run_id uuid,p_action jsonb,p_run_revision bigint,p_required_approvals integer,p_policy_version bigint) returns text
language sql immutable set search_path=public,extensions,pg_temp as $$
 select encode(digest(jsonb_build_object('organization_id',p_organization_id,'run_id',p_run_id,
 'action',p_action,'run_revision',p_run_revision,'required_approvals',p_required_approvals,
 'approval_policy_version',p_policy_version)::text,'sha256'),'hex')
$$;
create function public.finance_proposal_policy_matches(p public.action_proposals,r public.demo_runs) returns boolean
language sql immutable set search_path=public,pg_temp as $$
 select p.organization_id=r.organization_id and p.run_id=r.id
 and p.required_approvals=r.required_payment_approvals and p.approval_policy_version=r.approval_policy_version
 and p.action_hash=finance_payment_action_hash(p.organization_id,p.run_id,p.action,p.run_revision,p.required_approvals,p.approval_policy_version)
$$;
create function public.finance_eligible_approval_count(p public.action_proposals) returns integer
language sql stable set search_path=public,pg_temp as $$
 select count(distinct a.user_id)::integer from approvals a join memberships m
 on m.organization_id=a.organization_id and m.user_id=a.user_id and m.active
 where a.proposal_id=p.id and a.organization_id=p.organization_id and a.run_id=p.run_id
 and a.action_hash=p.action_hash and a.decision='approve'
 and ((p.required_approvals=1 and m.role='director')
 or (p.required_approvals=2 and m.role in ('director','approver') and a.user_id is distinct from p.proposed_by))
$$;
create function public.finance_require_payment_authority(p public.action_proposals,r public.demo_runs) returns void
language plpgsql set search_path=public,pg_temp as $$
begin
 if not finance_proposal_policy_matches(p,r) or p.run_revision<>r.revision or p.expires_at<=now() then
 raise exception 'submission authority expired or changed: stale proposal or approval policy' using errcode='23514'; end if;
 if finance_eligible_approval_count(p)<r.required_payment_approvals
 or exists(select 1 from approvals where proposal_id=p.id and decision='reject') then
 raise exception 'current human approvals required by event policy' using errcode='42501'; end if;
end $$;

create function public.set_event_approval_policy(p_organization_id uuid,p_run_id uuid,p_required_approvals integer,p_expected_revision bigint) returns jsonb
language plpgsql security definer set search_path=public,pg_temp as $$
declare r demo_runs; previous integer;
begin
 if coalesce(auth.role(),'')<>'authenticated' or auth.uid() is null then
 raise exception 'authenticated director required' using errcode='42501'; end if;
 perform finance_require_scope(p_organization_id,p_run_id,array['director']);
 perform finance_lock_run(p_organization_id,p_run_id);
 perform finance_require_scope(p_organization_id,p_run_id,array['director']);
 select * into strict r from demo_runs where organization_id=p_organization_id and id=p_run_id;
 if p_required_approvals is null or p_required_approvals not in (1,2) then
 raise exception 'required payment approvals must be 1 or 2' using errcode='22023'; end if;
 if p_expected_revision is distinct from r.revision then
 raise exception 'approval policy revision changed' using errcode='40001'; end if;
 if p_required_approvals<>r.required_payment_approvals then
 if exists(select 1 from payments where organization_id=p_organization_id and run_id=p_run_id
 and status in ('reserved','submitting','uncertain','submitted')) then
 raise exception 'unsettled payments prevent approval policy change' using errcode='23514'; end if;
 previous:=r.required_payment_approvals;
 update demo_runs set required_payment_approvals=p_required_approvals,
 approval_policy_version=approval_policy_version+1,revision=revision+1,updated_at=now()
 where organization_id=p_organization_id and id=p_run_id returning * into r;
 update action_proposals set status='stale' where organization_id=p_organization_id and run_id=p_run_id and status='pending';
 perform finance_audit(p_organization_id,p_run_id,'approval_policy_changed',jsonb_build_object(
 'previous_required_approvals',previous,'required_payment_approvals',r.required_payment_approvals,
 'approval_policy_version',r.approval_policy_version,'revision',r.revision));
 end if;
 return jsonb_build_object('organization_id',p_organization_id,'run_id',p_run_id,
 'required_payment_approvals',r.required_payment_approvals,'approval_policy_version',r.approval_policy_version,'revision',r.revision);
end $$;


create or replace function public.finance_immutable_proposal() returns trigger language plpgsql set search_path=public,pg_temp as $$
begin
 if (new.action,new.action_hash,new.run_revision,new.proposed_by,new.required_approvals,new.approval_policy_version,new.expires_at,new.organization_id,new.run_id)
 is distinct from (old.action,old.action_hash,old.run_revision,old.proposed_by,old.required_approvals,old.approval_policy_version,old.expires_at,old.organization_id,old.run_id)
 then raise exception 'proposal action is immutable' using errcode='23514'; end if; return new;
end $$;

create or replace function public.get_finance_snapshot(p_organization_id uuid,p_run_id uuid) returns jsonb
language plpgsql security definer set search_path=public,pg_temp as $$
declare r demo_runs; cash numeric; committed numeric; receivable numeric; last_seen timestamptz; result jsonb;
begin
 if coalesce(auth.role(),'')<>'service_role' then perform finance_require_scope(p_organization_id,p_run_id); end if;
 select * into strict r from demo_runs where organization_id=p_organization_id and id=p_run_id;
 select coalesce(sum(amount_minor),0) into cash from ledger_entries where organization_id=p_organization_id and run_id=p_run_id and account='cash' and currency=r.currency;
 select coalesce(sum(amount_minor-settled_minor) filter(where direction='payable'),0),
 coalesce(sum(amount_minor-settled_minor) filter(where direction='receivable'),0) into committed,receivable from obligations
 where organization_id=p_organization_id and run_id=p_run_id and status in ('open','disputed') and currency=r.currency;
 select max(w.last_seen_at) into last_seen from worker_heartbeats w join jobs j on j.worker_id=w.worker_id where j.organization_id=p_organization_id and j.run_id=p_run_id;
 result:=jsonb_build_object(
 'organization',(select jsonb_build_object('id',id,'name',name) from organizations where id=p_organization_id),
 'run',jsonb_build_object('id',r.id,'name',r.name,'status',r.status,'currency',r.currency,'revision',r.revision,'required_payment_approvals',r.required_payment_approvals,'approval_policy_version',r.approval_policy_version),
 'position',jsonb_build_object('currency',r.currency,'cash_minor',case when r.cash_established then cash::text end,
 'committed_minor',committed::text,'receivable_minor',receivable::text,'available_minor',case when r.cash_established then (cash-committed)::text end,
 'evidence_status',r.cash_evidence_status,'reconciled_at',r.reconciled_at),
 'cases',coalesce((select jsonb_agg(to_jsonb(c)-'organization_id'-'run_id' order by c.updated_at desc) from cases c where c.organization_id=p_organization_id and c.run_id=p_run_id),'[]'),
 'approvals',coalesce((select jsonb_agg(jsonb_build_object('id',p.id,'action_hash',p.action_hash,'action',p.action,'status',
 case when p.status='pending' and (p.run_revision<>r.revision or not finance_proposal_policy_matches(p,r)) then 'stale' when p.status='pending' and p.expires_at<=now() then 'expired' else p.status end,
 'required_approvals',p.required_approvals,'approval_policy_version',p.approval_policy_version,'approval_count',case when finance_proposal_policy_matches(p,r) and p.run_revision=r.revision then finance_eligible_approval_count(p) else 0 end,
 'decisions',coalesce((select jsonb_agg(jsonb_build_object('user_id',a.user_id,'decision',a.decision,'created_at',a.created_at)) from approvals a where a.proposal_id=p.id),'[]'),
 'expires_at',p.expires_at,'created_at',p.created_at) order by p.created_at desc) from action_proposals p where p.organization_id=p_organization_id and p.run_id=p_run_id),'[]'),
 'activity',coalesce((select jsonb_agg(to_jsonb(a)-'organization_id'-'run_id'-'actor_id' order by a.id) from
 (select * from audit_events where organization_id=p_organization_id and run_id=p_run_id order by id desc limit 100) a),'[]'),
 'improvements',jsonb_build_object(
 'trace_events',coalesce((select jsonb_agg(jsonb_build_object('id',t.id,'event_type',t.event_type,'created_at',t.created_at,'payload',jsonb_build_object('output',jsonb_build_object(
 'issue_type',left(t.payload->'output'->>'issue_type',200),'trace_references',t.payload->'output'->'trace_references',
 'diagnosis',left(t.payload->'output'->>'diagnosis',10000),'desired_behavior',left(t.payload->'output'->>'desired_behavior',10000)))))
 from trace_events t where t.organization_id=p_organization_id and t.run_id=p_run_id and t.event_type in ('improvement_diagnosed','actor_completed')),'[]'),
 'skill_versions',coalesce((select jsonb_agg(to_jsonb(s)-'organization_id'-'run_id') from skill_versions s where s.organization_id=p_organization_id and s.run_id=p_run_id),'[]'),
 'eval_runs',coalesce((select jsonb_agg(to_jsonb(e)-'organization_id'-'run_id') from eval_runs e where e.organization_id=p_organization_id and e.run_id=p_run_id),'[]'),
 'eval_results',coalesce((select jsonb_agg(to_jsonb(e)-'organization_id'-'run_id') from eval_results e where e.organization_id=p_organization_id and e.run_id=p_run_id),'[]'),
 'promotions',coalesce((select jsonb_agg(to_jsonb(p)-'organization_id'-'run_id') from promotions p where p.organization_id=p_organization_id and p.run_id=p_run_id),'[]')),
 'connections',coalesce((select jsonb_agg(jsonb_build_object('id',c.id,'provider',c.provider,'status',c.status,'updated_at',c.updated_at)) from connections c where c.organization_id=p_organization_id and c.run_id=p_run_id),'[]'),
 'obligations',coalesce((select jsonb_agg(to_jsonb(o)||jsonb_build_object('amount_minor',o.amount_minor::text,'settled_minor',o.settled_minor::text)) from obligations o where o.organization_id=p_organization_id and o.run_id=p_run_id),'[]'),
 'source_items',coalesce((select jsonb_agg(jsonb_build_object('id',s.id,'external_id',s.external_id,'version',s.version,'source_type',s.source_type,'content_sha256',s.content_sha256,'artifact_path',s.artifact_path)) from source_items s where s.organization_id=p_organization_id and s.run_id=p_run_id),'[]'),
 'reports',coalesce((select jsonb_agg(to_jsonb(s)-'organization_id'-'run_id' order by s.created_at desc) from report_snapshots s where s.organization_id=p_organization_id and s.run_id=p_run_id),'[]'),
 'worker',jsonb_build_object('status',case when last_seen is null then 'unknown' when last_seen>now()-interval '90 seconds' then 'online' else 'offline' end,'last_seen_at',last_seen),
 'updated_at',now()); return result;
end $$;

create or replace function public.approve_finance_proposal(p_proposal_id uuid,p_expected_action_hash text,p_decision text) returns jsonb
language plpgsql security definer set search_path=public,pg_temp as $$
declare p action_proposals; r demo_runs; existing approvals; n integer;
begin
 if coalesce(auth.role(),'')<>'authenticated' or auth.uid() is null then
 raise exception 'authenticated human required' using errcode='42501'; end if;
 select * into strict p from action_proposals where id=p_proposal_id;
 perform finance_require_scope(p.organization_id,p.run_id,array['director','approver']);
 perform finance_lock_run(p.organization_id,p.run_id);
 select * into p from action_proposals where id=p_proposal_id for update;
 perform finance_require_scope(p.organization_id,p.run_id,array['director','approver']);
 select * into r from demo_runs where id=p.run_id;
 if p.required_approvals=1 then
 perform finance_require_scope(p.organization_id,p.run_id,array['director']);
 elsif p.proposed_by=auth.uid() then
 raise exception 'proposer cannot approve own action' using errcode='42501'; end if;
 if p_decision is null or p_decision not in ('approve','reject') or p.action_hash is distinct from p_expected_action_hash then
 raise exception 'action hash or decision mismatch' using errcode='22023'; end if;
 -- Check freshness before idempotent decision reads: an old approval is evidence,
 -- never renewed authority after either policy or source context changes.
 if not finance_proposal_policy_matches(p,r) or p.run_revision<>r.revision or p.expires_at<=now() or p.status not in ('pending','rejected') then
 raise exception 'proposal expired, stale or not pending' using errcode='23514'; end if;
 select * into existing from approvals where proposal_id=p.id and user_id=auth.uid();
 if found then
 if existing.decision<>p_decision then raise exception 'decision is immutable' using errcode='23514'; end if;
 else
 if p.status<>'pending' then raise exception 'proposal expired, stale or not pending' using errcode='23514'; end if;
 insert into approvals(organization_id,run_id,proposal_id,user_id,action_hash,decision)
 values(p.organization_id,p.run_id,p.id,auth.uid(),p.action_hash,p_decision);
 if p_decision='reject' then update action_proposals set status='rejected' where id=p.id; end if;
 perform finance_audit(p.organization_id,p.run_id,'human_decision',jsonb_build_object('proposal_id',p.id,'decision',p_decision,
 'required_approvals',p.required_approvals,'approval_policy_version',p.approval_policy_version));
 end if;
 n:=finance_eligible_approval_count(p);
 return jsonb_build_object('proposal_id',p.id,'approval_count',n,'required_approvals',p.required_approvals,
 'approval_policy_version',p.approval_policy_version,'decision',p_decision);
end $$;

create or replace function public.finance_kernel_call(p_organization_id uuid,p_run_id uuid,p_operation text,p_arguments jsonb) returns jsonb
language plpgsql security definer set search_path=public,extensions,pg_temp as $$
declare r demo_runs; result jsonb; prior finance_operations; key text; request_hash text; row_id uuid; p action_proposals; pay payments;
 amount bigint; v_currency text; total numeric; reserved numeric; item jsonb; old_version integer; active_id uuid; eval eval_runs;
begin
 perform finance_require_service(); perform finance_lock_run(p_organization_id,p_run_id);
 select * into strict r from demo_runs where id=p_run_id and organization_id=p_organization_id;
 key:=p_arguments->>'idempotency_key'; request_hash:=encode(digest(p_operation||p_arguments::text,'sha256'),'hex');
 if p_operation not in ('get_case','list_due_work','get_obligations','get_active_skill','get_approval_status','get_payment_status','get_trace') then
 if key is null or length(key) not between 1 and 200 then raise exception 'idempotency key required' using errcode='22023'; end if;
 select * into prior from finance_operations where organization_id=p_organization_id and run_id=p_run_id and idempotency_key=key;
 if found then
 if prior.request_hash<>request_hash then raise exception 'idempotency key conflict' using errcode='23505'; end if;
 -- Historical results cannot grant new authority to reserve or send funds.
 if p_operation='reserve_approved_payment' then
 select * into strict p from action_proposals where organization_id=p_organization_id and run_id=p_run_id and id=(p_arguments->>'proposal_id')::uuid;
 if not finance_proposal_policy_matches(p,r) then raise exception 'stale proposal approval policy' using errcode='23514'; end if;
 select * into strict pay from payments where proposal_id=p.id;
 if pay.status='reserved' then perform finance_require_payment_authority(p,r); end if;
 elsif p_operation='transition_payment' and p_arguments->>'status'='submitting' then
 raise exception 'payment submission claim already consumed' using errcode='23514';
 end if;
 return prior.result;
 end if;
 end if;
 case p_operation
 when 'get_case' then
 select to_jsonb(c) into result from cases c where c.organization_id=p_organization_id and c.run_id=p_run_id and c.id=(p_arguments->>'case_id')::uuid;
 if result is null then raise exception 'case missing' using errcode='P0002'; end if;
 when 'list_due_work' then
 select coalesce(jsonb_agg(to_jsonb(c)),'[]') into result from cases c where c.organization_id=p_organization_id and c.run_id=p_run_id and c.status<>'closed';
 when 'get_obligations' then
 select coalesce(jsonb_agg(to_jsonb(o)||jsonb_build_object('amount_minor',o.amount_minor::text,'settled_minor',o.settled_minor::text)),'[]') into result from obligations o where o.organization_id=p_organization_id and o.run_id=p_run_id;
 when 'record_source' then
 insert into source_items(organization_id,run_id,external_id,version,source_type,content_sha256,artifact_path,metadata)
 values(p_organization_id,p_run_id,p_arguments->>'external_id',coalesce((p_arguments->>'version')::int,1),p_arguments->>'source_type',p_arguments->>'content_sha256',p_arguments->>'artifact_path',coalesce(p_arguments->'metadata','{}')) returning id into row_id;
 update cases c set status='needs_review',version=c.version+1,updated_at=now(),data=c.data||jsonb_build_object('change_impact',jsonb_build_object('source_id',row_id,'reason','source_revised'))
 where c.organization_id=p_organization_id and c.run_id=p_run_id and exists(
 select 1 from case_dependencies d join source_items s on s.id=d.source_id and s.organization_id=d.organization_id and s.run_id=d.run_id
 where d.case_id=c.id and s.external_id=p_arguments->>'external_id' and s.version<coalesce((p_arguments->>'version')::int,1));
 update demo_runs set revision=revision+1,updated_at=now() where id=p_run_id;
 result:=jsonb_build_object('id',row_id);
 when 'record_case' then
 row_id:=coalesce((p_arguments->>'id')::uuid,gen_random_uuid());
 select version into old_version from cases where id=row_id and organization_id=p_organization_id and run_id=p_run_id;
 if found and old_version<>coalesce((p_arguments->>'expected_version')::int,-1) then raise exception 'stale case version' using errcode='40001'; end if;
 insert into cases(id,organization_id,run_id,title,status,data) values(row_id,p_organization_id,p_run_id,p_arguments->>'title',coalesce(p_arguments->>'status','open'),coalesce(p_arguments->'data','{}'))
 on conflict(id) do update set title=excluded.title,status=excluded.status,data=excluded.data,version=cases.version+1,updated_at=now()
 where cases.organization_id=p_organization_id and cases.run_id=p_run_id;
 if not found then raise exception 'case scope denied' using errcode='42501'; end if;
 delete from case_dependencies where organization_id=p_organization_id and run_id=p_run_id and case_id=row_id;
 for item in select value from jsonb_array_elements(coalesce(p_arguments->'data'->'source_ids','[]')) loop
 insert into case_dependencies(organization_id,run_id,case_id,source_id,source_version)
 select p_organization_id,p_run_id,row_id,s.id,s.version from source_items s where s.organization_id=p_organization_id and s.run_id=p_run_id and s.id=(item#>>'{}')::uuid;
 if not found then raise exception 'case source outside scope' using errcode='42501'; end if;
 end loop;
 update demo_runs set revision=revision+1,updated_at=now() where id=p_run_id;
 result:=jsonb_build_object('id',row_id);
 when 'record_finding' then
 select version into old_version from cases where id=(p_arguments->>'case_id')::uuid and organization_id=p_organization_id and run_id=p_run_id;
 if old_version is null or old_version<>coalesce((p_arguments->>'expected_version')::int,-1) then raise exception 'stale or missing case' using errcode='40001'; end if;
 update cases set data=data||jsonb_build_object('finding',p_arguments->'finding'),version=version+1,updated_at=now() where id=(p_arguments->>'case_id')::uuid;
 update demo_runs set revision=revision+1,updated_at=now() where id=p_run_id;
 result:=jsonb_build_object('case_id',p_arguments->>'case_id','version',old_version+1);
 when 'propose_obligation_update' then
 row_id:=coalesce((p_arguments->>'id')::uuid,gen_random_uuid());
 amount:=(p_arguments->>'amount_minor')::bigint; v_currency:=p_arguments->>'currency';
 if v_currency is distinct from r.currency or amount is null or amount<0 then raise exception 'invalid currency or amount'; end if;
 select version into old_version from obligations where id=row_id and organization_id=p_organization_id and run_id=p_run_id;
 if found and old_version<>coalesce((p_arguments->>'expected_version')::int,-1) then raise exception 'stale obligation version' using errcode='40001'; end if;
 insert into obligations(id,organization_id,run_id,case_id,budget_line_id,title,direction,amount_minor,currency,due_date,evidence_status,source_refs)
 values(row_id,p_organization_id,p_run_id,(p_arguments->>'case_id')::uuid,(p_arguments->>'budget_line_id')::uuid,p_arguments->>'title',p_arguments->>'direction',amount,v_currency,(p_arguments->>'due_date')::date,coalesce(p_arguments->>'evidence_status','reported'),coalesce(p_arguments->'source_refs','[]'))
 on conflict(id) do update set amount_minor=excluded.amount_minor,title=excluded.title,due_date=excluded.due_date,source_refs=excluded.source_refs,version=obligations.version+1,updated_at=now()
 where obligations.organization_id=p_organization_id and obligations.run_id=p_run_id and obligations.settled_minor<=excluded.amount_minor;
 if not found then raise exception 'obligation scope or settled amount conflict'; end if;
 update demo_runs set revision=revision+1,updated_at=now() where id=p_run_id;
 result:=jsonb_build_object('id',row_id,'version',coalesce(old_version,0)+1);
 when 'post_ledger' then
 if jsonb_array_length(p_arguments->'entries')<2 then raise exception 'two postings required'; end if;
 if exists(select 1 from jsonb_array_elements(p_arguments->'entries') e group by e->>'currency' having sum((e->>'amount_minor')::numeric)<>0) then raise exception 'unbalanced journal' using errcode='23514'; end if;
 if exists(select 1 from jsonb_array_elements(p_arguments->'entries') e where e->>'currency'<>r.currency or (e->>'amount_minor')::bigint=0 or coalesce(e->>'account','')='') then raise exception 'invalid posting'; end if;
 insert into ledger_transactions(organization_id,run_id,description,idempotency_key) values(p_organization_id,p_run_id,p_arguments->>'description',key) returning id into row_id;
 insert into ledger_entries(organization_id,run_id,transaction_id,account,currency,amount_minor)
 select p_organization_id,p_run_id,row_id,e->>'account',e->>'currency',(e->>'amount_minor')::bigint from jsonb_array_elements(p_arguments->'entries') e;
 if coalesce((p_arguments->>'establish_opening')::boolean,false) then
 if r.cash_established then raise exception 'opening balance already established'; end if;
 if coalesce(p_arguments->>'evidence_status','') not in ('owner_attested','statement_confirmed','provider_confirmed') then raise exception 'opening evidence required'; end if;
 update demo_runs set cash_established=true,cash_evidence_status=p_arguments->>'evidence_status',reconciled_at=now() where id=p_run_id; end if;
 update demo_runs set revision=revision+1,updated_at=now() where id=p_run_id;
 result:=jsonb_build_object('id',row_id);
 when 'create_approval_request' then
 item:=finance_json_money_strings(p_arguments->'action'); amount:=(item->>'amount_minor')::bigint;
 if jsonb_typeof(item) is distinct from 'object' or not(item ?& array['type','amount_minor','currency','destination','asset','network','obligation_id','obligation_version'])
 or item->>'type' is distinct from 'payment' or amount is null or amount<=0 or item->>'currency' is distinct from r.currency
 or coalesce(item->>'destination','')='' or coalesce(item->>'asset','')='' or coalesce(item->>'network','') not in ('base-sepolia','eip155:84532')
 then raise exception 'exact testnet payment action required' using errcode='22023'; end if;
 if not exists(select 1 from obligations o where o.organization_id=p_organization_id and o.run_id=p_run_id and o.id=(item->>'obligation_id')::uuid and o.version=(item->>'obligation_version')::int and o.direction='payable' and o.status='open' and o.currency=r.currency and o.amount_minor-o.settled_minor>=amount) then raise exception 'current payable evidence required'; end if;
 insert into action_proposals(organization_id,run_id,action,action_hash,run_revision,proposed_by,required_approvals,approval_policy_version,expires_at,idempotency_key)
 values(p_organization_id,p_run_id,item,finance_payment_action_hash(p_organization_id,p_run_id,item,r.revision,r.required_payment_approvals,r.approval_policy_version),r.revision,(p_arguments->>'proposed_by')::uuid,r.required_payment_approvals,r.approval_policy_version,now()+interval '30 minutes',key) returning * into p;
 result:=to_jsonb(p);
 when 'get_approval_status' then
 select to_jsonb(a)||jsonb_build_object('approval_count',case when finance_proposal_policy_matches(a,r) and a.run_revision=r.revision then finance_eligible_approval_count(a) else 0 end) into result
 from action_proposals a where a.organization_id=p_organization_id and a.run_id=p_run_id and a.id=(p_arguments->>'proposal_id')::uuid;
 when 'reserve_approved_payment' then
 select * into strict p from action_proposals where organization_id=p_organization_id and run_id=p_run_id and id=(p_arguments->>'proposal_id')::uuid for update;
 select * into pay from payments where proposal_id=p.id;
 if not finance_proposal_policy_matches(p,r) then raise exception 'stale proposal approval policy' using errcode='23514'; end if;
 if found then
 if pay.status='reserved' then perform finance_require_payment_authority(p,r); end if;
 result:=to_jsonb(pay); else
 if p.status<>'pending' or p.expires_at<=now() or p.run_revision<>r.revision then raise exception 'stale or expired proposal' using errcode='23514'; end if;
 perform finance_require_payment_authority(p,r);
 amount:=(p.action->>'amount_minor')::bigint;
 if not r.cash_established then raise exception 'cash evidence missing'; end if;
 select coalesce(sum(amount_minor),0) into total from ledger_entries where organization_id=p_organization_id and run_id=p_run_id and account='cash' and currency=r.currency;
 select coalesce(sum(amount_minor),0) into reserved from payments where organization_id=p_organization_id and run_id=p_run_id and status in ('reserved','submitting','uncertain','submitted');
 if total-reserved<amount then raise exception 'insufficient unreserved cash' using errcode='23514'; end if;
 if exists(select 1 from payments x join action_proposals a on a.id=x.proposal_id where x.organization_id=p_organization_id and x.run_id=p_run_id and x.status<>'failed' and a.action->>'obligation_id'=p.action->>'obligation_id') then raise exception 'obligation already reserved'; end if;
 insert into payments(organization_id,run_id,proposal_id,amount_minor,currency) values(p_organization_id,p_run_id,p.id,amount,r.currency) returning * into pay;
 update action_proposals set status='reserved' where id=p.id; result:=to_jsonb(pay);
 end if;
 when 'transition_payment' then
 select * into strict pay from payments where organization_id=p_organization_id and run_id=p_run_id and id=(p_arguments->>'payment_id')::uuid for update;
 if not ((pay.status='reserved' and p_arguments->>'status'='submitting') or (pay.status='submitting' and p_arguments->>'status' in ('submitted','uncertain','failed')) or (pay.status='uncertain' and p_arguments->>'status' in ('submitted','failed')))
 then raise exception 'invalid payment state transition' using errcode='23514'; end if;
 if p_arguments->>'status'='submitting' then
 select * into p from action_proposals where id=pay.proposal_id;
 if p.status<>'reserved' then raise exception 'submission authority expired or changed' using errcode='23514'; end if;
 perform finance_require_payment_authority(p,r);
 end if;
 if p_arguments->>'status'='submitted' and coalesce(p_arguments->>'provider_reference','')='' then raise exception 'provider reference required'; end if;
 update payments set status=p_arguments->>'status',provider_reference=coalesce(p_arguments->>'provider_reference',provider_reference),updated_at=now() where id=pay.id returning * into pay;
 result:=to_jsonb(pay);
 when 'get_payment_status' then
 select to_jsonb(x) into result from payments x where x.organization_id=p_organization_id and x.run_id=p_run_id and x.id=(p_arguments->>'payment_id')::uuid;
 when 'get_trace' then
 select to_jsonb(t) into result from trace_events t where t.organization_id=p_organization_id and t.run_id=p_run_id and t.id=(p_arguments->>'trace_id')::uuid;
 when 'confirm_payment' then
 select * into strict pay from payments where organization_id=p_organization_id and run_id=p_run_id and id=(p_arguments->>'payment_id')::uuid for update;
 select * into p from action_proposals where id=pay.proposal_id;
 item:=p_arguments->'receipt';
 if jsonb_typeof(item) is distinct from 'object' or not(item ?& array['provider_reference','destination','asset','network','amount_minor','status'])
 or pay.status<>'submitted' or item->>'provider_reference' is distinct from pay.provider_reference or item->>'destination' is distinct from p.action->>'destination'
 or item->>'asset' is distinct from p.action->>'asset' or item->>'network' is distinct from p.action->>'network' or (item->>'amount_minor')::bigint is distinct from pay.amount_minor or item->>'status' is distinct from 'confirmed'
 or (p.action ? 'amount_base_units' and item->>'amount_base_units' is distinct from p.action->>'amount_base_units')
 then raise exception 'verified receipt mismatch' using errcode='23514'; end if;
 insert into ledger_transactions(organization_id,run_id,description,idempotency_key) values(p_organization_id,p_run_id,'Confirmed testnet payout','payment:'||pay.id) returning id into row_id;
 insert into ledger_entries(organization_id,run_id,transaction_id,account,currency,amount_minor) values
 (p_organization_id,p_run_id,row_id,'cash',pay.currency,-pay.amount_minor),(p_organization_id,p_run_id,row_id,'expense',pay.currency,pay.amount_minor);
 update obligations set settled_minor=settled_minor+pay.amount_minor,status=case when settled_minor+pay.amount_minor=amount_minor then 'settled' else status end,version=version+1,updated_at=now() where id=(p.action->>'obligation_id')::uuid and organization_id=p_organization_id and run_id=p_run_id;
 update payments set status='confirmed',receipt=item,updated_at=now() where id=pay.id;
 update action_proposals set status='executed' where id=p.id;
 update demo_runs set revision=revision+1,updated_at=now() where id=p_run_id;
 result:=jsonb_build_object('payment_id',pay.id,'status','confirmed','ledger_transaction_id',row_id);
 when 'record_trace' then
 insert into trace_events(organization_id,run_id,case_id,event_type,payload,idempotency_key) values(p_organization_id,p_run_id,(p_arguments->>'case_id')::uuid,p_arguments->>'event_type',p_arguments->'payload',key) returning id into row_id;
 result:=jsonb_build_object('id',row_id);
 when 'get_active_skill' then
 select to_jsonb(s) into result from skill_versions s where s.organization_id=p_organization_id and s.run_id=p_run_id and s.skill_name=p_arguments->>'skill_name' and s.is_active;
 when 'save_skill_version' then
 insert into skill_versions(organization_id,run_id,skill_name,version,artifact_path,content_sha256,parent_version_id,status,metadata)
 values(p_organization_id,p_run_id,p_arguments->>'skill_name',p_arguments->>'version',p_arguments->>'artifact_path',p_arguments->>'content_sha256',(p_arguments->>'parent_version_id')::uuid,coalesce(p_arguments->>'status','candidate'),coalesce(p_arguments->'metadata','{}')) returning id into row_id;
 select to_jsonb(s) into result from skill_versions s where id=row_id;
 when 'initialize_skill_baseline' then
 if p_arguments->>'skill_name'<>'organizer-expenses' then raise exception 'baseline skill outside permitted scope' using errcode='42501'; end if;
 if exists(select 1 from skill_versions where organization_id=p_organization_id and run_id=p_run_id and skill_name=p_arguments->>'skill_name' and is_active)
 then raise exception 'active baseline already initialized' using errcode='23514'; end if;
 update skill_versions set is_active=true,status='baseline' where organization_id=p_organization_id and run_id=p_run_id and id=(p_arguments->>'version_id')::uuid
 and skill_name=p_arguments->>'skill_name' and parent_version_id is null and status='baseline';
 if not found then raise exception 'bundled baseline required'; end if;
 result:=jsonb_build_object('id',p_arguments->>'version_id','status','baseline');
 when 'record_eval_run' then
 row_id:=coalesce((p_arguments->>'id')::uuid,gen_random_uuid());
 insert into eval_runs(id,organization_id,run_id,skill_name,baseline_version_id,candidate_version_id,status,metrics,artifact_path)
 values(row_id,p_organization_id,p_run_id,p_arguments->>'skill_name',(p_arguments->>'baseline_version_id')::uuid,(p_arguments->>'candidate_version_id')::uuid,p_arguments->>'status',coalesce(p_arguments->'metrics','{}'),p_arguments->>'artifact_path')
 on conflict(id) do update set status=excluded.status,metrics=excluded.metrics,artifact_path=excluded.artifact_path,updated_at=now() where eval_runs.organization_id=p_organization_id and eval_runs.run_id=p_run_id;
 if not found then raise exception 'evaluation scope denied'; end if; select to_jsonb(e) into result from eval_runs e where id=row_id;
 when 'record_eval_result' then
 insert into eval_results(organization_id,run_id,eval_run_id,case_key,variant,passed,hard_invariants_passed,metrics,details)
 values(p_organization_id,p_run_id,(p_arguments->>'eval_run_id')::uuid,p_arguments->>'case_key',p_arguments->>'variant',(p_arguments->>'passed')::boolean,(p_arguments->>'hard_invariants_passed')::boolean,coalesce(p_arguments->'metrics','{}'),coalesce(p_arguments->'details','{}')) returning id into row_id;
 result:=jsonb_build_object('id',row_id);
 when 'record_promotion' then
 insert into promotions(organization_id,run_id,skill_name,version_id,previous_version_id,eval_run_id,state,reason)
 values(p_organization_id,p_run_id,p_arguments->>'skill_name',(p_arguments->>'version_id')::uuid,(p_arguments->>'previous_version_id')::uuid,(p_arguments->>'eval_run_id')::uuid,p_arguments->>'state',p_arguments->>'reason') returning id into row_id;
 result:=jsonb_build_object('id',row_id);
 when 'set_active_skill_version' then
 if p_arguments->>'skill_name'<>'organizer-expenses' then raise exception 'skill outside permitted improvement scope' using errcode='42501'; end if;
 select id into active_id from skill_versions where organization_id=p_organization_id and run_id=p_run_id and skill_name=p_arguments->>'skill_name' and is_active;
 if active_id is distinct from (p_arguments->>'expected_active_version_id')::uuid then raise exception 'active skill changed' using errcode='40001'; end if;
 select * into strict eval from eval_runs where organization_id=p_organization_id and run_id=p_run_id and id=(p_arguments->>'eval_run_id')::uuid;
 if eval.status<>'passed' or eval.candidate_version_id<>(p_arguments->>'version_id')::uuid or eval.baseline_version_id is distinct from active_id
 or not exists(select 1 from eval_results where eval_run_id=eval.id and variant='candidate') or exists(select 1 from eval_results where eval_run_id=eval.id and variant='candidate' and (not hard_invariants_passed or (details->>'group'='regression' and not passed)))
 or coalesce((eval.metrics->>'gate_passed')::boolean,false) is not true then raise exception 'fixed evaluation gate not met' using errcode='23514'; end if;
 update skill_versions set is_active=false where id=active_id;
 update skill_versions set is_active=true,status='promoted' where organization_id=p_organization_id and run_id=p_run_id and id=(p_arguments->>'version_id')::uuid and skill_name=p_arguments->>'skill_name';
 if not found then raise exception 'skill missing'; end if;
 insert into promotions(organization_id,run_id,skill_name,version_id,previous_version_id,eval_run_id,state,reason)
 values(p_organization_id,p_run_id,p_arguments->>'skill_name',(p_arguments->>'version_id')::uuid,active_id,eval.id,'promoted',coalesce(p_arguments->>'reason','Fixed evaluation gate passed')) returning id into row_id;
 result:=jsonb_build_object('id',p_arguments->>'version_id','previous_version_id',active_id,'promotion_id',row_id);
 when 'rollback_skill_version' then
 if p_arguments->>'skill_name'<>'organizer-expenses' then raise exception 'skill outside permitted scope' using errcode='42501'; end if;
 select id into active_id from skill_versions where organization_id=p_organization_id and run_id=p_run_id and skill_name=p_arguments->>'skill_name' and is_active;
 if active_id is distinct from (p_arguments->>'expected_active_version_id')::uuid then raise exception 'active skill changed' using errcode='40001'; end if;
 if not exists(select 1 from promotions where organization_id=p_organization_id and run_id=p_run_id and id=(p_arguments->>'promotion_id')::uuid and version_id=active_id and previous_version_id=(p_arguments->>'version_id')::uuid and state='promoted')
 or coalesce(p_arguments->>'reason','')='' then raise exception 'recorded promotion and rollback reason required'; end if;
 update skill_versions set is_active=false,status='rolled_back' where id=active_id;
 update skill_versions set is_active=true where organization_id=p_organization_id and run_id=p_run_id and id=(p_arguments->>'version_id')::uuid and skill_name=p_arguments->>'skill_name';
 if not found then raise exception 'rollback version missing'; end if;
 insert into promotions(organization_id,run_id,skill_name,version_id,previous_version_id,state,reason) values(p_organization_id,p_run_id,p_arguments->>'skill_name',(p_arguments->>'version_id')::uuid,active_id,'rolled_back',p_arguments->>'reason');
 result:=jsonb_build_object('id',p_arguments->>'version_id','previous_version_id',active_id,'state','rolled_back');
 when 'record_report' then
 insert into report_snapshots(organization_id,run_id,cutoff,data,artifact_path) values(p_organization_id,p_run_id,(p_arguments->>'cutoff')::timestamptz,finance_json_money_strings(p_arguments->'data'),p_arguments->>'artifact_path') returning id into row_id;
 result:=jsonb_build_object('id',row_id);
 when 'set_connection_status' then
 insert into connections(organization_id,run_id,provider,status,data) values(p_organization_id,p_run_id,p_arguments->>'provider',p_arguments->>'status',coalesce(p_arguments->'data','{}'))
 on conflict(organization_id,run_id,provider) do update set status=excluded.status,data=connections.data||excluded.data,updated_at=now(); result:=jsonb_build_object('status',p_arguments->>'status');
 else raise exception 'unsupported finance operation: %',p_operation using errcode='22023';
 end case;
 if key is not null then
 insert into finance_operations(organization_id,run_id,idempotency_key,operation,request_hash,result) values(p_organization_id,p_run_id,key,p_operation,request_hash,coalesce(result,'null'));
 perform finance_audit(p_organization_id,p_run_id,p_operation,jsonb_build_object('record_id',coalesce(result->>'id',result->>'payment_id')));
 end if;
 return result;
end $$;


-- New helpers are private; browser authority is the single authenticated RPC.
revoke all on function public.finance_guard_event_approval_policy(),
 public.finance_payment_action_hash(uuid,uuid,jsonb,bigint,integer,bigint),
 public.finance_proposal_policy_matches(public.action_proposals,public.demo_runs),
 public.finance_eligible_approval_count(public.action_proposals),
 public.finance_require_payment_authority(public.action_proposals,public.demo_runs)
 from public,anon,authenticated;
grant execute on function public.finance_guard_event_approval_policy(),
 public.finance_payment_action_hash(uuid,uuid,jsonb,bigint,integer,bigint),
 public.finance_proposal_policy_matches(public.action_proposals,public.demo_runs),
 public.finance_eligible_approval_count(public.action_proposals),
 public.finance_require_payment_authority(public.action_proposals,public.demo_runs) to service_role;
revoke all on function public.set_event_approval_policy(uuid,uuid,integer,bigint) from public,anon,service_role;
grant execute on function public.set_event_approval_policy(uuid,uuid,integer,bigint) to authenticated;
commit;
