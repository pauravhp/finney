-- Trusted completion annotation. It cannot change money, sources or approvals.
-- Annotation changes case.version for CAS but not the financial run revision.
begin;
create function public.record_finance_case_review(
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
 or not exists(select 1 from jobs j where j.organization_id=p_organization_id and j.run_id=p_run_id and j.id=p_job_id and j.command_type='review_case' and j.payload->>'case_id'=p_case_id::text)
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
revoke all on function public.record_finance_case_review(uuid,uuid,uuid,integer,uuid[],uuid,uuid,jsonb,text) from public,anon,authenticated;
grant execute on function public.record_finance_case_review(uuid,uuid,uuid,integer,uuid[],uuid,uuid,jsonb,text) to service_role;
commit;
