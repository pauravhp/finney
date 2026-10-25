-- Diagnose a reserved OpenCode startup/runtime timeout, including zero actual
-- provider calls. Preserve every existing failed-trace provenance/output guard,
-- run/owner/day budget, attempt/holdout and financial/promotion validator.
begin;
do $migration$
declare
 definition text;
 old_codes text := $old$'opencode_structured_output_missing','opencode_truncated_output',$old$;
 new_codes text := $new$'opencode_structured_output_missing','opencode_truncated_output','opencode_timeout',$new$;
begin
 select pg_get_functiondef('public.finance_kernel_call_v9(uuid,uuid,text,jsonb)'::regprocedure) into definition;
 if (length(definition)-length(replace(definition,old_codes,'')))/length(old_codes)<>1
    or position('finance-failure-observation-v1' in definition)=0 then
  raise exception 'timeout intake requires exactly one known failed-trace reason guard';
 end if;
 execute replace(definition,old_codes,new_codes);
end $migration$;
revoke all on function public.finance_kernel_call_v9(uuid,uuid,text,jsonb) from public,anon,authenticated,service_role;
commit;
