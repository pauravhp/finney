-- Conversational replies are annotations, never parsed financial authority.
begin;

create function public.finance_director_consulted_refs(p_events jsonb) returns jsonb
language plpgsql immutable set search_path=public,pg_temp as $$
declare event jsonb;result jsonb;documents jsonb;document jsonb;refs jsonb:='[]';answer jsonb;
begin
 if jsonb_typeof(p_events) is distinct from 'array' then raise exception 'actual tool event list required' using errcode='23514';end if;
 for event in select value from jsonb_array_elements(p_events) loop
 if coalesce(event->>'name','') not in ('read_document','read_thread') then continue;end if;
 result:=event->'result';
 if jsonb_typeof(result) is distinct from 'object' or coalesce(result->>'status','') in ('failed','blocked','error')
 or (result ? 'error' and result->'error' not in ('null'::jsonb,'false'::jsonb,'""'::jsonb,'0'::jsonb)) or result->'success'='false'::jsonb then continue;end if;
 documents:=case when event->>'name'='read_document' then jsonb_build_array(result) else result->'documents' end;
 if jsonb_typeof(documents) is distinct from 'array' then raise exception 'actual thread document list required' using errcode='23514';end if;
 for document in select value from jsonb_array_elements(documents) loop
 if jsonb_typeof(document) is distinct from 'object' or coalesce(document->>'status','') in ('failed','blocked','error')
 or (document ? 'error' and document->'error' not in ('null'::jsonb,'false'::jsonb,'""'::jsonb,'0'::jsonb)) or document->'success'='false'::jsonb then continue;end if;
 if jsonb_typeof(document->'id') is distinct from 'string' or coalesce(document->>'id','') !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
 or jsonb_typeof(document->'version') is distinct from 'number' or coalesce(document->>'version','') !~ '^[1-9][0-9]*$'
 or (document->>'version')::numeric>2147483647 then raise exception 'actual versioned consulted source required' using errcode='23514';end if;
 if exists(select 1 from jsonb_array_elements(refs) x where x->>'id'=document->>'id' and x->>'version'<>document->>'version') then
 raise exception 'conflicting consulted source versions' using errcode='23514';end if;
 refs:=refs||jsonb_build_array(jsonb_build_object('id',document->>'id','version',(document->>'version')::integer));
 end loop;end loop;
 select coalesce(jsonb_agg(x.ref order by x.ref->>'id'),'[]') into answer from (select distinct value as ref from jsonb_array_elements(refs)) x;
 if jsonb_array_length(answer)>200 then raise exception 'consulted source limit exceeded' using errcode='23514';end if;
 return answer;
end $$;

create function public.record_finance_director_response(
 p_organization_id uuid,p_run_id uuid,p_case_id uuid,p_expected_version integer,p_expected_source_ids uuid[],
 p_trace_id uuid,p_job_id uuid,p_response jsonb,p_idempotency_key text
) returns jsonb language plpgsql security definer set search_path=public,extensions,pg_temp as $$
declare c cases;t trace_events;j jobs;r demo_runs;prior finance_operations;fingerprint text;result jsonb;
 actual jsonb;refs jsonb;declared jsonb;ids jsonb;declared_ids jsonb;entry jsonb;history jsonb;recorded_trace uuid;
begin
 perform finance_require_service();perform finance_lock_run(p_organization_id,p_run_id);
 select * into strict r from demo_runs where organization_id=p_organization_id and id=p_run_id;
 select * into strict j from jobs where organization_id=p_organization_id and run_id=p_run_id and id=p_job_id;
 if j.command_type<>'director_message' or j.payload->>'case_id' is distinct from p_case_id::text or j.status not in ('running','completed') then
 raise exception 'actual active director-message job required' using errcode='23514';end if;
 if j.requested_by is null or not exists(select 1 from memberships where organization_id=p_organization_id and user_id=j.requested_by and active and role in ('director','finance'))
 or (r.is_demo and r.owner_user_id is distinct from j.requested_by) then raise exception 'current event editor authority required' using errcode='42501';end if;
 if p_idempotency_key is distinct from 'director-response:'||p_job_id::text or p_expected_version is null or p_expected_version<1
 or p_expected_source_ids is null or cardinality(p_expected_source_ids)>200 or array_position(p_expected_source_ids,null) is not null
 or (select count(distinct x) from unnest(p_expected_source_ids) x)<>cardinality(p_expected_source_ids) then
 raise exception 'stable director response context required' using errcode='22023';end if;
 fingerprint:=encode(digest(jsonb_build_object('case_id',p_case_id,'expected_version',p_expected_version,'expected_source_ids',p_expected_source_ids,
 'trace_id',p_trace_id,'job_id',p_job_id,'response',p_response)::text,'sha256'),'hex');
 select * into prior from finance_operations where organization_id=p_organization_id and run_id=p_run_id and idempotency_key=p_idempotency_key;
 if found then
 if prior.operation<>'record_director_response' or prior.request_hash<>fingerprint then raise exception 'director response idempotency conflict' using errcode='23505';end if;return prior.result;
 end if;
 select * into strict c from cases where organization_id=p_organization_id and run_id=p_run_id and id=p_case_id for update;
 if c.version is distinct from p_expected_version or coalesce(c.data->'source_ids','[]') is distinct from to_jsonb(p_expected_source_ids) then
 raise exception 'director response case context changed' using errcode='40001';end if;
 if exists(select 1 from unnest(p_expected_source_ids) x where not exists(select 1 from source_items s where s.organization_id=p_organization_id and s.run_id=p_run_id and s.id=x)) then
 raise exception 'director response case source outside scope' using errcode='23514';end if;
 select * into strict t from trace_events where organization_id=p_organization_id and run_id=p_run_id and id=p_trace_id;
 if t.event_type<>'actor_completed' or t.payload->>'job_id' is distinct from p_job_id::text or coalesce(t.payload->>'skill_version','')=''
 or t.payload->'improvement_eligible' is distinct from 'false'::jsonb or t.payload->'evidence'->>'output_contract' is distinct from 'finance-director-response-v1' then
 raise exception 'actual scoped conversation trace required' using errcode='23514';end if;
 actual:=t.payload->'output';
 if jsonb_typeof(actual) is distinct from 'object' or actual-array['response_type','message','evidence_source_ids','consulted_source_refs']<>'{}'::jsonb
 or actual->>'response_type' is distinct from 'director_response' or jsonb_typeof(actual->'message') is distinct from 'string'
 or length(actual->>'message') not between 1 and 16000 or length(trim(actual->>'message'))=0
 or jsonb_typeof(actual->'evidence_source_ids') is distinct from 'array' or jsonb_typeof(actual->'consulted_source_refs') is distinct from 'array' then
 raise exception 'actual bounded director response required' using errcode='23514';end if;
 refs:=finance_director_consulted_refs(coalesce(t.payload->'tool_events','[]'));
 select coalesce(jsonb_agg(x->'id' order by x->>'id'),'[]') into ids from jsonb_array_elements(refs) x;
 if exists(select 1 from jsonb_array_elements(actual->'evidence_source_ids') x where jsonb_typeof(x) is distinct from 'string')
 or exists(select 1 from jsonb_array_elements(actual->'consulted_source_refs') x where jsonb_typeof(x) is distinct from 'object' or x-array['id','version']<>'{}'::jsonb) then
 raise exception 'actual consulted source representation invalid' using errcode='23514';end if;
 declared:=finance_director_consulted_refs(jsonb_build_array(jsonb_build_object('name','read_thread','result',jsonb_build_object('documents',actual->'consulted_source_refs'))));
 select coalesce(jsonb_agg(x order by x#>>'{}'),'[]') into declared_ids from jsonb_array_elements(actual->'evidence_source_ids') x;
 if declared is distinct from refs or jsonb_array_length(actual->'consulted_source_refs')<>jsonb_array_length(refs)
 or declared_ids is distinct from ids or jsonb_array_length(actual->'evidence_source_ids')<>jsonb_array_length(refs)
 or exists(select 1 from jsonb_array_elements(refs) x where not exists(select 1 from source_items s where s.organization_id=p_organization_id and s.run_id=p_run_id and s.id::text=x->>'id' and s.version::text=x->>'version')) then
 raise exception 'consulted sources must exactly match successful scoped versioned reads' using errcode='23514';end if;
 if jsonb_typeof(p_response) is distinct from 'object' or p_response-array['message','consulted_source_ids','consulted_source_refs','provenance']<>'{}'::jsonb
 or p_response->>'message' is distinct from actual->>'message' or p_response->'consulted_source_ids' is distinct from ids or p_response->'consulted_source_refs' is distinct from refs
 or jsonb_typeof(p_response->'provenance') is distinct from 'object' or (p_response->'provenance')-array['source_case_version','source_ids']<>'{}'::jsonb
 or p_response->'provenance'->'source_case_version' is distinct from to_jsonb(p_expected_version) or p_response->'provenance'->'source_ids' is distinct from to_jsonb(p_expected_source_ids) then
 raise exception 'director response must preserve actual output and context' using errcode='23514';end if;
 history:=coalesce(c.data->'director_responses','[]');
 if jsonb_typeof(history) is distinct from 'array' or exists(select 1 from jsonb_array_elements(history) x where x->>'job_id'=p_job_id::text) then
 raise exception 'director response history conflict' using errcode='23514';end if;
 entry:=jsonb_build_object('id',p_job_id,'job_id',p_job_id,'trace_id',t.id,'response_type','director_response','message',actual->>'message',
 'consulted_source_ids',ids,'consulted_source_refs',refs,'source_label','consulted','verification','unverified_agent_response','created_at',now(),
 'provenance',jsonb_build_object('job_id',p_job_id,'actor_trace_id',t.id,'skill_version_id',t.payload->>'skill_version','output_contract','finance-director-response-v1',
 'source_case_version',p_expected_version,'source_ids',to_jsonb(p_expected_source_ids),'requested_by',j.requested_by,
 'message_sha256',encode(digest(actual->>'message','sha256'),'hex')));
 update cases set data=data||jsonb_build_object('director_responses',history||jsonb_build_array(entry)),version=version+1,updated_at=now()
 where organization_id=p_organization_id and run_id=p_run_id and id=c.id;
 insert into trace_events(organization_id,run_id,case_id,event_type,payload,idempotency_key)
 values(p_organization_id,p_run_id,c.id,'director_response_persisted',jsonb_build_object('job_id',p_job_id,'actor_trace_id',t.id,'response_id',p_job_id,
 'case_id',c.id,'case_version',c.version+1,'output_contract','finance-director-response-v1','consulted_source_count',jsonb_array_length(refs)),
 'director-response-recorded:'||p_job_id) returning id into recorded_trace;
 result:=jsonb_build_object('status','persisted','case_id',c.id,'version',c.version+1,'case_status',c.status,'response_id',p_job_id,'response_trace_id',recorded_trace);
 insert into finance_operations(organization_id,run_id,idempotency_key,operation,request_hash,result)
 values(p_organization_id,p_run_id,p_idempotency_key,'record_director_response',fingerprint,result);
 perform finance_audit(p_organization_id,p_run_id,'director_response_persisted',jsonb_build_object('case_id',c.id,'actor_trace_id',t.id,'response_id',p_job_id));
 return result;
end $$;

revoke all on function public.finance_director_consulted_refs(jsonb),public.record_finance_director_response(uuid,uuid,uuid,integer,uuid[],uuid,uuid,jsonb,text) from public,anon,authenticated,service_role;
grant execute on function public.record_finance_director_response(uuid,uuid,uuid,integer,uuid[],uuid,uuid,jsonb,text) to service_role;
commit;
