-- A separately selected bounded Harness2 search can reserve up to 96 calls.
-- Ordinary actors and legacy single-patch attempts retain their 40-call cap.
-- Run, visitor-lifetime, day, attempt, holdout, grade and activation guards stay intact.
begin;
alter table public.finance_improvement_attempts
 add column improvement_method text not null default 'single_patch'
 check(improvement_method in ('single_patch','harness2'));
alter table public.finance_improvement_attempts
 drop constraint finance_improvement_attempts_max_model_calls_check;
alter table public.finance_improvement_attempts
 add constraint finance_improvement_attempts_max_model_calls_check
 check(max_model_calls between 1 and 96
       and (max_model_calls<=40 or improvement_method='harness2'));

do $migration$
declare
 definition text;
 target regprocedure;
 old_guard text := $old$if calls is null or calls not between 1 and 40 then raise exception 'model call reservation must be 1 to 40' using errcode='22023';$old$;
 new_guard text := $new$if calls is null or calls < 1 or calls > (case
 when p_operation='claim_improvement_attempt' and p_arguments->>'improvement_method'='harness2' then 96 else 40 end)
 then raise exception 'model call reservation exceeds method limit' using errcode='22023'; end if;
 if p_operation='claim_improvement_attempt' and coalesce(p_arguments->>'improvement_method','single_patch') not in ('single_patch','harness2')
 then raise exception 'invalid improvement method' using errcode='22023';$new$;
 old_columns text := 'case_manifest,max_model_calls)';
 new_columns text := 'case_manifest,max_model_calls,improvement_method)';
 old_values text := $old$p_arguments->>'evaluator_version',fingerprints,calls);$old$;
 new_values text := $new$p_arguments->>'evaluator_version',fingerprints,calls,coalesce(p_arguments->>'improvement_method','single_patch'));$new$;
begin
 -- The inner v9 owns immutable attempt/source/grade/run controls. The public
 -- outer wrapper owns persistent demo-owner/day limits; both must admit the same cap.
 foreach target in array array[
 'public.finance_kernel_call_v9(uuid,uuid,text,jsonb)'::regprocedure,
 'public.finance_kernel_call(uuid,uuid,text,jsonb)'::regprocedure] loop
  select pg_get_functiondef(target) into definition;
  if (length(definition)-length(replace(definition,old_guard,'')))/length(old_guard)<>1 then
   raise exception 'online Harness2 requires one known reservation guard in %',target;
  end if;
  definition:=replace(definition,old_guard,new_guard);
  if target='public.finance_kernel_call_v9(uuid,uuid,text,jsonb)'::regprocedure then
   if (length(definition)-length(replace(definition,old_columns,'')))/length(old_columns)<>1
    or (length(definition)-length(replace(definition,old_values,'')))/length(old_values)<>1 then
    raise exception 'online Harness2 requires known inner attempt insert';
   end if;
   definition:=replace(replace(definition,old_columns,new_columns),old_values,new_values);
  end if;
  execute definition;
 end loop;
end $migration$;
revoke all on function public.finance_kernel_call_v9(uuid,uuid,text,jsonb) from public,anon,authenticated,service_role;
revoke all on function public.finance_kernel_call(uuid,uuid,text,jsonb) from public,anon,authenticated;
grant execute on function public.finance_kernel_call(uuid,uuid,text,jsonb) to service_role;
commit;
