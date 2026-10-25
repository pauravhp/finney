-- Budget authority gates new sends. Existing remote effects must remain readable
-- and reconcilable after another obligation changes the current allocation.
-- Keep migration013's public kernel/owner-budget wrapper unchanged.
begin;
create or replace function public.finance_kernel_call_v12(p_organization_id uuid,p_run_id uuid,p_operation text,p_arguments jsonb) returns jsonb
language plpgsql security definer set search_path=public,pg_temp as $$
declare previous obligations;result jsonb;budget_id uuid;existing_effect boolean:=false;
begin
 perform finance_require_service();perform finance_lock_run(p_organization_id,p_run_id);
 if p_operation='propose_obligation_update' then
 select * into previous from obligations where organization_id=p_organization_id and run_id=p_run_id and id=(p_arguments->>'id')::uuid;
 if previous.id is not null and p_arguments->>'direction' is distinct from previous.direction then
 raise exception 'existing obligation direction is immutable' using errcode='23514';end if;
 if p_arguments ? 'budget_line_id' and p_arguments->'budget_line_id'<>'null'::jsonb then
 budget_id:=(p_arguments->>'budget_line_id')::uuid;
 if not exists(select 1 from budget_lines b join demo_runs r on r.organization_id=b.organization_id and r.id=b.run_id
 where b.organization_id=p_organization_id and b.run_id=p_run_id and b.id=budget_id and b.currency=r.currency) then
 raise exception 'budget line outside event run or currency' using errcode='23514';end if;
 end if;
 end if;
 if p_operation='reserve_approved_payment' then
 -- The locked, scoped durable payment is authority only to inspect/reconcile
 -- its existing effect. Reserved/new payments still require every send gate.
 select exists(select 1 from payments p where p.organization_id=p_organization_id and p.run_id=p_run_id
 and p.proposal_id=(p_arguments->>'proposal_id')::uuid and p.status in ('submitting','uncertain','submitted','confirmed')) into existing_effect;
 end if;
 if p_operation='create_approval_request' or (p_operation='reserve_approved_payment' and not existing_effect)
 or (p_operation='transition_payment' and p_arguments->>'status'='submitting') then
 perform finance_require_budget_capacity(p_organization_id,p_run_id);
 end if;
 -- v9 retains source provenance, demo isolation, approval-policy binding,
 -- idempotency, one-use submission claims and exact receipt verification.
 result:=finance_kernel_call_v9(p_organization_id,p_run_id,p_operation,p_arguments);
 if p_operation='propose_obligation_update' and p_arguments ? 'budget_line_id' and previous.id is not null then
 update obligations set budget_line_id=budget_id where id=previous.id and organization_id=p_organization_id and run_id=p_run_id
 and version=(result->>'version')::integer and version>previous.version;
 end if;
 return result;
end $$;
revoke all on function public.finance_kernel_call_v12(uuid,uuid,text,jsonb) from public,anon,authenticated,service_role;
commit;
