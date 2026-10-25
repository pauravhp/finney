-- Provider capabilities, evidence provenance and bounded learning are enforced
-- outside mutable actor/improver instructions. No provider is enabled here.
begin;
alter table public.trace_events add constraint trace_events_scoped_id unique(organization_id,run_id,id);

create function public.finance_validate_source_refs(p_org uuid,p_run uuid,p_refs jsonb) returns void
language plpgsql security definer set search_path=public,pg_temp as $$
begin
 if jsonb_typeof(p_refs) is distinct from 'array' or jsonb_array_length(p_refs) not between 1 and 200 then
 raise exception 'current versioned source references required' using errcode='23514'; end if;
 if exists(select 1 from jsonb_array_elements(p_refs) x where jsonb_typeof(x) is distinct from 'object'
 or coalesce(x->>'id','') !~ '^[0-9a-fA-F-]{36}$' or coalesce(x->>'version','') !~ '^[1-9][0-9]*$') then
 raise exception 'invalid source references' using errcode='23514'; end if;
 if exists(select 1 from jsonb_array_elements(p_refs) x where not exists(
 select 1 from source_items s where s.organization_id=p_org and s.run_id=p_run and s.id::text=x->>'id'
 and s.version::text=x->>'version' and not exists(select 1 from source_items newer
 where newer.organization_id=p_org and newer.run_id=p_run and newer.external_id=s.external_id and newer.version>s.version))) then
 raise exception 'source reference missing, stale or outside run' using errcode='23514'; end if;
end $$;

create function public.attest_finance_obligation(p_organization_id uuid,p_run_id uuid,p_obligation_id uuid,p_expected_version integer,p_note text) returns jsonb
language plpgsql security definer set search_path=public,pg_temp as $$
declare o obligations;
begin
 if auth.role() is distinct from 'authenticated' or auth.uid() is null then
 raise exception 'authenticated director attestation required' using errcode='42501'; end if;
 perform finance_require_scope(p_organization_id,p_run_id,array['director']);
 perform finance_lock_run(p_organization_id,p_run_id);
 perform finance_require_scope(p_organization_id,p_run_id,array['director']);
 select * into strict o from obligations where organization_id=p_organization_id and run_id=p_run_id and id=p_obligation_id;
 if o.version is distinct from p_expected_version then raise exception 'stale obligation version' using errcode='40001'; end if;
 if length(trim(coalesce(p_note,''))) not between 3 and 4000 then raise exception 'explicit attestation note required' using errcode='22023'; end if;
 perform finance_validate_source_refs(p_organization_id,p_run_id,o.source_refs);
 if o.evidence_status in ('provider_confirmed','statement_reconciled') then
 raise exception 'independent confirmation cannot be replaced by attestation' using errcode='23514'; end if;
 update obligations set evidence_status='owner_attested',version=version+1,updated_at=now() where id=o.id returning * into o;
 update demo_runs set revision=revision+1,updated_at=now() where id=p_run_id;
 perform finance_audit(p_organization_id,p_run_id,'obligation_owner_attested',jsonb_build_object('obligation_id',o.id,'version',o.version,
 'attested_by',auth.uid(),'amount_minor',o.amount_minor::text,'currency',o.currency,'source_refs',o.source_refs,'note',p_note));
 return jsonb_build_object('id',o.id,'version',o.version,'evidence_status',o.evidence_status);
end $$;

create table public.finance_run_execution_limits (
 organization_id uuid not null,run_id uuid not null,model_call_limit integer not null default 120 check(model_call_limit between 1 and 10000),
 reserved_model_calls integer not null default 0 check(reserved_model_calls>=0),improvement_attempt_limit integer not null default 3 check(improvement_attempt_limit between 0 and 100),
 reserved_improvement_attempts integer not null default 0 check(reserved_improvement_attempts>=0),
 primary key(organization_id,run_id),foreign key(organization_id,run_id) references demo_runs(organization_id,id)
);
create table public.finance_inference_reservations (
 organization_id uuid not null,run_id uuid not null,reservation_id uuid not null,max_model_calls integer not null check(max_model_calls between 1 and 40),
 created_at timestamptz not null default now(),primary key(organization_id,run_id,reservation_id),
 foreign key(organization_id,run_id) references demo_runs(organization_id,id)
);
create table public.finance_improvement_attempts (
 id uuid primary key,organization_id uuid not null,run_id uuid not null,trace_id uuid not null,baseline_version_id uuid not null,
 suite_id text not null,suite_manifest_sha256 text not null check(suite_manifest_sha256 ~ '^[0-9a-f]{64}$'),evaluator_version text not null,case_manifest jsonb not null,
 max_model_calls integer not null check(max_model_calls between 1 and 40),status text not null default 'claimed' check(status in ('claimed','blocked','rejected','promoted')),
 model_calls_used integer,reason text,eval_run_id uuid,created_at timestamptz not null default now(),finished_at timestamptz,
 unique(organization_id,run_id,trace_id,baseline_version_id,suite_manifest_sha256,evaluator_version),unique(organization_id,run_id,id),
 foreign key(organization_id,run_id) references demo_runs(organization_id,id),foreign key(organization_id,run_id,trace_id) references trace_events(organization_id,run_id,id),
 foreign key(organization_id,run_id,baseline_version_id) references skill_versions(organization_id,run_id,id),
 foreign key(organization_id,run_id,eval_run_id) references eval_runs(organization_id,run_id,id)
);
create table public.finance_improvement_holdouts (
 organization_id uuid not null,run_id uuid not null,source_snapshot_hash text not null check(source_snapshot_hash ~ '^[0-9a-f]{64}$'),
 attempt_id uuid not null,suite_id text not null,consumed_at timestamptz not null default now(),primary key(organization_id,run_id,source_snapshot_hash),
 foreign key(organization_id,run_id,attempt_id) references finance_improvement_attempts(organization_id,run_id,id)
);
do $$ declare tab text; begin
 foreach tab in array array['finance_run_execution_limits','finance_inference_reservations','finance_improvement_attempts','finance_improvement_holdouts'] loop
 execute format('alter table public.%I enable row level security',tab);
 execute format('revoke all on public.%I from public,anon,authenticated,service_role',tab);
 execute format('grant select on public.%I to authenticated',tab);
 execute format('create policy scoped_read on public.%I for select to authenticated using(finance_can_access(organization_id,run_id))',tab);
 end loop;
end $$;

create function public.set_finance_execution_limits(p_organization_id uuid,p_run_id uuid,p_model_call_limit integer,p_improvement_attempt_limit integer) returns jsonb
language plpgsql security definer set search_path=public,pg_temp as $$
declare r demo_runs; limits finance_run_execution_limits;
begin
 if auth.role() is distinct from 'authenticated' or auth.uid() is null then raise exception 'authenticated director required' using errcode='42501'; end if;
 perform finance_require_scope(p_organization_id,p_run_id,array['director']);perform finance_lock_run(p_organization_id,p_run_id);
 select * into strict r from demo_runs where organization_id=p_organization_id and id=p_run_id;
 if r.is_demo then raise exception 'public demo budgets cannot be raised by visitors' using errcode='42501'; end if;
 if p_model_call_limit is null or p_model_call_limit not between 1 and 10000 or p_improvement_attempt_limit is null or p_improvement_attempt_limit not between 0 and 100 then
 raise exception 'invalid execution limits' using errcode='22023'; end if;
 insert into finance_run_execution_limits(organization_id,run_id,model_call_limit) values(p_organization_id,p_run_id,1000) on conflict do nothing;
 select * into limits from finance_run_execution_limits where organization_id=p_organization_id and run_id=p_run_id;
 if p_model_call_limit<limits.reserved_model_calls or p_improvement_attempt_limit<limits.reserved_improvement_attempts then
 raise exception 'limits cannot erase consumed reservations' using errcode='23514'; end if;
 update finance_run_execution_limits set model_call_limit=p_model_call_limit,improvement_attempt_limit=p_improvement_attempt_limit
 where organization_id=p_organization_id and run_id=p_run_id returning * into limits;
 perform finance_audit(p_organization_id,p_run_id,'execution_limits_changed',jsonb_build_object('model_call_limit',p_model_call_limit,'improvement_attempt_limit',p_improvement_attempt_limit));
 return to_jsonb(limits);
end $$;

-- Preserve v8's approval-policy implementation; its old entrypoint is no longer
-- executable by workers. All callers pass these new checks before delegation.
alter function public.finance_kernel_call(uuid,uuid,text,jsonb) rename to finance_kernel_call_v8;
revoke all on function public.finance_kernel_call_v8(uuid,uuid,text,jsonb) from public,anon,authenticated,service_role;
create function public.finance_kernel_call(p_organization_id uuid,p_run_id uuid,p_operation text,p_arguments jsonb) returns jsonb
language plpgsql security definer set search_path=public,extensions,pg_temp as $$
declare r demo_runs; result jsonb; limits finance_run_execution_limits; attempt finance_improvement_attempts; evaluation eval_runs; previous_obligation obligations;
 aid uuid; reservation uuid; calls integer; item jsonb; fingerprints jsonb; counts record; baseline_hash text; candidate_hash text;
begin
 perform finance_require_service();perform finance_lock_run(p_organization_id,p_run_id);
 select * into strict r from demo_runs where organization_id=p_organization_id and id=p_run_id;
 if r.is_demo and p_operation in ('create_approval_request','reserve_approved_payment','transition_payment','confirm_payment','assert_payment_run_authorized') then
 raise exception 'public demo cannot use payment provider capabilities' using errcode='42501'; end if;
 if p_operation='assert_payment_run_authorized' then
 if p_arguments->>'configured_organization_id' is distinct from p_organization_id::text or p_arguments->>'configured_run_id' is distinct from p_run_id::text
 or coalesce(p_arguments->>'sender','') !~ '^0x[0-9a-fA-F]{40}$' or lower(p_arguments->>'sender')='0x0000000000000000000000000000000000000000' then
 raise exception 'payment provider is not authorized for this event run' using errcode='42501'; end if;
 return jsonb_build_object('authorized',true,'organization_id',p_organization_id,'run_id',p_run_id,'sender',lower(p_arguments->>'sender'),'is_demo',false);
 end if;
 if p_operation='propose_obligation_update' then
 perform finance_validate_source_refs(p_organization_id,p_run_id,p_arguments->'source_refs');
 if coalesce(p_arguments->>'evidence_status','reported') not in ('expected','reported') then
 raise exception 'obligation confirmation requires trusted attestation or provider verification' using errcode='42501'; end if;
 select * into previous_obligation from obligations where organization_id=p_organization_id and run_id=p_run_id and id=(p_arguments->>'id')::uuid;
 end if;
 if p_operation in ('claim_improvement_attempt','reserve_run_inference') then
 insert into finance_run_execution_limits(organization_id,run_id,model_call_limit)
 values(p_organization_id,p_run_id,case when r.is_demo then 120 else 1000 end) on conflict do nothing;
 select * into strict limits from finance_run_execution_limits where organization_id=p_organization_id and run_id=p_run_id for update;
 calls:=(p_arguments->>'max_model_calls')::integer;
 if calls is null or calls not between 1 and 40 then raise exception 'model call reservation must be 1 to 40' using errcode='22023'; end if;
 if p_operation='reserve_run_inference' then
 reservation:=(p_arguments->>'reservation_id')::uuid;
 if reservation is null then raise exception 'reservation identity required' using errcode='22023'; end if;
 if exists(select 1 from finance_inference_reservations where organization_id=p_organization_id and run_id=p_run_id and reservation_id=reservation) then
 return jsonb_build_object('claimed',false,'reason','inference_reservation_already_consumed','reservation_id',reservation); end if;
 if limits.reserved_model_calls+calls>limits.model_call_limit then return jsonb_build_object('claimed',false,'reason','run_model_call_budget_exhausted','reservation_id',reservation); end if;
 insert into finance_inference_reservations values(p_organization_id,p_run_id,reservation,calls,now());
 update finance_run_execution_limits set reserved_model_calls=reserved_model_calls+calls where organization_id=p_organization_id and run_id=p_run_id;
 return jsonb_build_object('claimed',true,'reservation_id',reservation,'max_model_calls',calls);
 end if;
 aid:=(p_arguments->>'attempt_id')::uuid;
 if aid is null or length(coalesce(p_arguments->>'suite_id','')) not between 1 and 200 or length(coalesce(p_arguments->>'evaluator_version','')) not between 1 and 100
 or coalesce(p_arguments->>'suite_manifest_sha256','') !~ '^[0-9a-f]{64}$' then raise exception 'invalid improvement attempt manifest' using errcode='22023'; end if;
 fingerprints:=p_arguments->'case_manifest';
 if jsonb_typeof(fingerprints) is distinct from 'array' or jsonb_array_length(fingerprints) not between 3 and 100
 or exists(select 1 from jsonb_array_elements(fingerprints) x where length(coalesce(x->>'case_key','')) not between 1 and 200
 or coalesce(x->>'group','') not in ('validation','regression','transfer') or coalesce(x->>'source_snapshot_hash','') !~ '^[0-9a-f]{64}$')
 or (select count(distinct x->>'group') from jsonb_array_elements(fingerprints) x)<>3
 or (select count(distinct x->>'case_key') from jsonb_array_elements(fingerprints) x)<>jsonb_array_length(fingerprints)
 or (select count(distinct x->>'source_snapshot_hash') from jsonb_array_elements(fingerprints) x)<>jsonb_array_length(fingerprints) then
 raise exception 'complete distinct validation regression transfer manifest required' using errcode='22023'; end if;
 if exists(select 1 from finance_improvement_attempts a where a.id=aid or (a.organization_id=p_organization_id and a.run_id=p_run_id
 and a.trace_id=(p_arguments->>'trace_id')::uuid and a.baseline_version_id=(p_arguments->>'baseline_version_id')::uuid
 and a.suite_manifest_sha256=p_arguments->>'suite_manifest_sha256' and a.evaluator_version=p_arguments->>'evaluator_version')) then
 return jsonb_build_object('claimed',false,'reason','improvement_attempt_already_claimed','attempt_id',aid); end if;
 if not exists(select 1 from skill_versions s join trace_events t on t.organization_id=s.organization_id and t.run_id=s.run_id
 where s.organization_id=p_organization_id and s.run_id=p_run_id and s.id=(p_arguments->>'baseline_version_id')::uuid and s.is_active
 and s.skill_name='organizer-expenses' and t.id=(p_arguments->>'trace_id')::uuid and t.event_type='actor_completed' and t.payload->>'skill_version'=s.id::text) then
 raise exception 'current completed actor trace and active baseline required' using errcode='23514'; end if;
 if limits.reserved_improvement_attempts>=limits.improvement_attempt_limit then return jsonb_build_object('claimed',false,'reason','run_improvement_attempt_budget_exhausted','attempt_id',aid); end if;
 if limits.reserved_model_calls+calls>limits.model_call_limit then return jsonb_build_object('claimed',false,'reason','run_model_call_budget_exhausted','attempt_id',aid); end if;
 insert into finance_improvement_attempts(id,organization_id,run_id,trace_id,baseline_version_id,suite_id,suite_manifest_sha256,evaluator_version,case_manifest,max_model_calls)
 values(aid,p_organization_id,p_run_id,(p_arguments->>'trace_id')::uuid,(p_arguments->>'baseline_version_id')::uuid,p_arguments->>'suite_id',p_arguments->>'suite_manifest_sha256',p_arguments->>'evaluator_version',fingerprints,calls);
 update finance_run_execution_limits set reserved_model_calls=reserved_model_calls+calls,reserved_improvement_attempts=reserved_improvement_attempts+1 where organization_id=p_organization_id and run_id=p_run_id;
 return jsonb_build_object('claimed',true,'attempt_id',aid,'max_model_calls',calls);
 end if;
 if p_operation in ('claim_improvement_holdout','finish_improvement_attempt') then
 aid:=(p_arguments->>'attempt_id')::uuid;
 select * into strict attempt from finance_improvement_attempts where organization_id=p_organization_id and run_id=p_run_id and id=aid for update;
 if attempt.status<>'claimed' then return jsonb_build_object('claimed',false,'reason','improvement_attempt_finished','attempt_id',aid); end if;
 if p_operation='finish_improvement_attempt' then
 calls:=(p_arguments->>'model_calls_used')::integer;
 if p_arguments->>'status' not in ('blocked','rejected','promoted') or calls is null or calls not between 0 and attempt.max_model_calls
 or length(coalesce(p_arguments->>'reason','')) not between 1 and 4000 then raise exception 'invalid improvement completion receipt' using errcode='22023'; end if;
 update finance_improvement_attempts set status=p_arguments->>'status',model_calls_used=calls,reason=p_arguments->>'reason',
 eval_run_id=(p_arguments->>'eval_run_id')::uuid,finished_at=now() where id=aid;
 return jsonb_build_object('status',p_arguments->>'status','attempt_id',aid,'reserved_model_calls',attempt.max_model_calls);
 end if;
 fingerprints:=p_arguments->'transfer_fingerprints';
 if p_arguments->>'suite_id' is distinct from attempt.suite_id or jsonb_typeof(fingerprints) is distinct from 'array' or jsonb_array_length(fingerprints) not between 1 and 100
 or exists(select 1 from jsonb_array_elements_text(fingerprints) x where x !~ '^[0-9a-f]{64}$')
 or (select count(distinct x) from jsonb_array_elements_text(fingerprints) x)<>jsonb_array_length(fingerprints) then
 raise exception 'distinct untouched transfer fingerprints required' using errcode='22023'; end if;
 if (select jsonb_agg(x order by x) from jsonb_array_elements_text(fingerprints) x) is distinct from
 (select jsonb_agg(x->>'source_snapshot_hash' order by x->>'source_snapshot_hash') from jsonb_array_elements(attempt.case_manifest) x where x->>'group'='transfer') then
 raise exception 'holdout fingerprints must match frozen transfer manifest' using errcode='23514'; end if;
 if exists(select 1 from finance_improvement_holdouts h where h.organization_id=p_organization_id and h.run_id=p_run_id
 and h.source_snapshot_hash in (select jsonb_array_elements_text(fingerprints))) then
 return jsonb_build_object('claimed',false,'reason','transfer_holdout_already_consumed','attempt_id',aid); end if;
 insert into finance_improvement_holdouts(organization_id,run_id,source_snapshot_hash,attempt_id,suite_id)
 select p_organization_id,p_run_id,x,aid,attempt.suite_id from jsonb_array_elements_text(fingerprints) x;
 return jsonb_build_object('claimed',true,'attempt_id',aid);
 end if;
 if p_operation='set_active_skill_version' then
 -- A historical activation result cannot activate again. v8 handles exact
 -- idempotent replay after these independently checked result predicates.
 select * into strict evaluation from eval_runs where organization_id=p_organization_id and run_id=p_run_id and id=(p_arguments->>'eval_run_id')::uuid;
 select * into attempt from finance_improvement_attempts where organization_id=p_organization_id and run_id=p_run_id and id=(evaluation.metrics->>'attempt_id')::uuid;
 if not found or attempt.status not in ('claimed','promoted') or attempt.baseline_version_id is distinct from evaluation.baseline_version_id or attempt.suite_id is distinct from evaluation.metrics->>'suite_id'
 or attempt.suite_manifest_sha256 is distinct from evaluation.metrics->>'suite_manifest_sha256' or attempt.evaluator_version is distinct from evaluation.metrics->>'evaluator_version'
 or evaluation.metrics->>'gate_version' is distinct from 'finance-promotion-v3' or evaluation.status<>'passed' or evaluation.metrics->>'gate_passed' is distinct from 'true' then
 raise exception 'fixed evaluation gate requires a claimed matching manifest' using errcode='23514'; end if;
 select content_sha256 into baseline_hash from skill_versions where id=evaluation.baseline_version_id;
 select content_sha256 into candidate_hash from skill_versions where id=evaluation.candidate_version_id and parent_version_id=evaluation.baseline_version_id;
 if baseline_hash is null or candidate_hash is null or baseline_hash=candidate_hash then raise exception 'fixed evaluation gate rejects no-op candidate' using errcode='23514'; end if;
 if (select count(*) from eval_results where eval_run_id=evaluation.id)<>2*jsonb_array_length(attempt.case_manifest)
 or exists(select 1 from jsonb_array_elements(attempt.case_manifest) x where
 (select count(*) from eval_results e where e.eval_run_id=evaluation.id and e.case_key=x->>'case_key'
 and e.details->>'group'=x->>'group' and e.details->>'source_snapshot_hash'=x->>'source_snapshot_hash')<>2)
 or (select count(distinct details->>'group') from eval_results where eval_run_id=evaluation.id)<>3
 or exists(select 1 from eval_results e where e.eval_run_id=evaluation.id and (e.variant not in ('baseline','candidate')
 or coalesce(e.details->>'group','') not in ('validation','regression','transfer') or coalesce(e.details->>'source_snapshot_hash','') !~ '^[0-9a-f]{64}$'
 or e.details->>'suite_manifest_sha256' is distinct from attempt.suite_manifest_sha256 or e.details->>'evaluator_version' is distinct from attempt.evaluator_version
 or e.details->>'gate_version' is distinct from 'finance-promotion-v3' or coalesce(e.metrics->>'tool_calls','') !~ '^[0-9]{1,6}$'
 or (e.passed and not e.hard_invariants_passed)))
 or exists(select 1 from eval_results where eval_run_id=evaluation.id group by case_key having count(*)<>2 or count(distinct variant)<>2)
 or exists(select 1 from eval_results b join eval_results c on c.eval_run_id=b.eval_run_id and c.case_key=b.case_key and c.variant='candidate'
 where b.eval_run_id=evaluation.id and b.variant='baseline' and (b.details->>'group' is distinct from c.details->>'group'
 or b.details->>'source_snapshot_hash' is distinct from c.details->>'source_snapshot_hash' or (b.passed and not c.passed)))
 or exists(select 1 from eval_results c where c.eval_run_id=evaluation.id and c.variant='candidate' and (not c.hard_invariants_passed
 or (c.details->>'group' in ('regression','transfer') and not c.passed)))
 or exists(select 1 from eval_results e where e.eval_run_id=evaluation.id and e.details->>'group'='transfer' and not exists(
 select 1 from finance_improvement_holdouts h where h.organization_id=p_organization_id and h.run_id=p_run_id and h.attempt_id=attempt.id
 and h.source_snapshot_hash=e.details->>'source_snapshot_hash')) then
 raise exception 'fixed evaluation gate requires complete paired protected results and untouched transfer' using errcode='23514'; end if;
 select count(*) filter(where b.passed) as baseline_correct,count(*) filter(where c.passed) as candidate_correct,
 coalesce(sum((b.metrics->>'tool_calls')::integer) filter(where b.passed and c.passed),0) as baseline_tools,
 coalesce(sum((c.metrics->>'tool_calls')::integer) filter(where b.passed and c.passed),0) as candidate_tools into counts
 from eval_results b join eval_results c on c.eval_run_id=b.eval_run_id and c.case_key=b.case_key and c.variant='candidate'
 where b.eval_run_id=evaluation.id and b.variant='baseline';
 if not(counts.candidate_correct>counts.baseline_correct or (counts.candidate_correct=counts.baseline_correct and counts.candidate_tools<counts.baseline_tools)) then
 raise exception 'fixed evaluation gate requires independently measured improvement' using errcode='23514'; end if;
 end if;
 result:=finance_kernel_call_v8(p_organization_id,p_run_id,p_operation,p_arguments);
 if p_operation='propose_obligation_update' and previous_obligation.id is not null then
 update obligations o set evidence_status=coalesce(p_arguments->>'evidence_status','reported')
 where o.id=previous_obligation.id and o.version>previous_obligation.version
 and (o.amount_minor,o.title,o.due_date,o.source_refs) is distinct from
 (previous_obligation.amount_minor,previous_obligation.title,previous_obligation.due_date,previous_obligation.source_refs);
 end if;
 if p_operation='confirm_payment' then
 update obligations o set evidence_status='provider_confirmed' from payments pay join action_proposals p on p.id=pay.proposal_id
 where pay.organization_id=p_organization_id and pay.run_id=p_run_id and pay.id=(p_arguments->>'payment_id')::uuid and pay.status='confirmed'
 and o.organization_id=p_organization_id and o.run_id=p_run_id and o.id=(p.action->>'obligation_id')::uuid;
 end if;
 return result;
end $$;

alter function public.record_finance_income(uuid,uuid,jsonb,text,text) rename to record_finance_income_v2;
revoke all on function public.record_finance_income_v2(uuid,uuid,jsonb,text,text) from public,anon,authenticated,service_role;
create function public.record_finance_income(p_organization_id uuid,p_run_id uuid,p_receipt jsonb,p_artifact_path text,p_content_sha256 text) returns jsonb
language plpgsql security definer set search_path=public,pg_temp as $$
begin
 perform finance_require_service();perform finance_lock_run(p_organization_id,p_run_id);
 if exists(select 1 from demo_runs where organization_id=p_organization_id and id=p_run_id and is_demo) then
 raise exception 'public demo cannot use payment provider capabilities' using errcode='42501'; end if;
 return record_finance_income_v2(p_organization_id,p_run_id,p_receipt,p_artifact_path,p_content_sha256);
end $$;

revoke all on function public.finance_validate_source_refs(uuid,uuid,jsonb),public.finance_kernel_call(uuid,uuid,text,jsonb),
 public.attest_finance_obligation(uuid,uuid,uuid,integer,text),public.set_finance_execution_limits(uuid,uuid,integer,integer) from public,anon,authenticated,service_role;
grant execute on function public.finance_kernel_call(uuid,uuid,text,jsonb) to service_role;
revoke all on function public.record_finance_income(uuid,uuid,jsonb,text,text) from public,anon,authenticated,service_role;
grant execute on function public.record_finance_income(uuid,uuid,jsonb,text,text) to service_role;
grant execute on function public.attest_finance_obligation(uuid,uuid,uuid,integer,text),public.set_finance_execution_limits(uuid,uuid,integer,integer) to authenticated;
commit;
