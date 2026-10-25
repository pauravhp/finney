-- Permit diagnosis of a provenance-bound failed actor without changing financial
-- review validity, reservations, attempt limits, frozen pairs or promotion gates.
-- v9 owns these guards; v12 and the current wrapper retain their outer budgets.
begin;
do $migration$
declare
 definition text;
 old_guard text := $old$t.event_type='actor_completed'$old$;
 new_guard text := $new$(t.event_type='actor_completed' or (
 t.event_type='actor_failed'
 and t.payload->>'actor_status'='failed'
 and t.payload->>'command_type'='review_case'
 and t.payload->'improvement_eligible'='true'::jsonb
 and t.payload->>'mutable_skill_name'='organizer-expenses'
 and not (t.payload ? 'output')
 and t.payload->'failure_observations'->>'contract'='finance-failure-observation-v1'
 and t.payload->'failure_observations'->'financial_output_valid'='false'::jsonb
 and t.payload->'failure_observations'->>'actor_status'='failed'
 and t.payload->'failure_observations'->>'reason' in (
 'invalid_finance_decision_schema','model_output_not_json_object',
 'model_output_ambiguous_json','model_output_multiple_json_objects',
 'model_output_incomplete_for_format_recovery','model_output_not_recoverable_without_new_content',
 'hermes_timeout','hermes_incomplete_outcome','hermes_truncated_output',
 'hermes_provider_or_runtime_failure','hermes_process_exited_without_result',
 'hermes_protocol_error','hermes_invalid_api_call_count',
 'opencode_structured_output_missing','opencode_truncated_output',
 'opencode_incomplete_outcome','opencode_tool_not_permitted',
 'opencode_provider_or_runtime_failure','evaluation_model_call_budget_exhausted')
 and (t.payload->'failure_observations'->>'reason'<>'evaluation_model_call_budget_exhausted'
 or (jsonb_typeof(t.payload->'failure_observations'->'api_calls')='number'
 and (t.payload->'failure_observations'->>'api_calls')::integer>0))
 and octet_length((t.payload->'failure_observations')::text)<=4000
 and t.payload->>'context_sha256' ~ '^[0-9a-f]{64}$'
 and t.payload->'runtime_context_artifact'->>'content_sha256' ~ '^[0-9a-f]{64}$'
 and t.payload->'diagnostic_artifact'->>'content_sha256' ~ '^[0-9a-f]{64}$'
 and starts_with(t.payload->'runtime_context_artifact'->>'artifact_path',p_organization_id::text||'/'||p_run_id::text||'/artifacts/')
 and starts_with(t.payload->'diagnostic_artifact'->>'artifact_path',p_organization_id::text||'/'||p_run_id::text||'/artifacts/')
 and t.payload->'inference_reservation'->'claimed'='true'::jsonb
 and exists(select 1 from jobs j join finance_inference_reservations i
 on i.organization_id=j.organization_id and i.run_id=j.run_id and i.reservation_id=j.id
 where j.organization_id=p_organization_id and j.run_id=p_run_id
 and j.id::text=t.payload->>'job_id' and j.command_type='review_case'
 and i.reservation_id::text=t.payload->'inference_reservation'->>'reservation_id'
 and i.max_model_calls=(t.payload->'inference_reservation'->>'max_model_calls')::integer)
 ))$new$;
begin
 select pg_get_functiondef('public.finance_kernel_call_v9(uuid,uuid,text,jsonb)'::regprocedure) into definition;
 -- Fail closed on unexpected upstream drift instead of replacing a different guard.
 if (length(definition)-length(replace(definition,old_guard,'')))/length(old_guard)<>1 then
  raise exception 'failed trace intake requires exactly one known v9 actor trace guard';
 end if;
 execute replace(definition,old_guard,new_guard);
end $migration$;
revoke all on function public.finance_kernel_call_v9(uuid,uuid,text,jsonb) from public,anon,authenticated,service_role;
commit;
