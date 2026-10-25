-- An explicit director attestation establishes cash, including a real zero.
-- This is not statement/provider confirmation and cannot run from agent inference.
begin;
create function public.establish_finance_opening_cash(
 p_organization_id uuid,p_run_id uuid,p_actor_id uuid,p_amount_minor bigint,p_currency text,
 p_as_of timestamptz,p_evidence_source_id uuid,p_idempotency_key text
) returns jsonb language plpgsql security definer set search_path=public,extensions,pg_temp as $$
declare r demo_runs; evidence source_items; prior finance_operations; fingerprint text; result jsonb;journal_uuid uuid;
begin
 perform finance_require_service();perform finance_lock_run(p_organization_id,p_run_id);
 select * into strict r from demo_runs where organization_id=p_organization_id and id=p_run_id;
 if p_actor_id is null or not exists(select 1 from memberships where organization_id=p_organization_id and user_id=p_actor_id and active and role='director')
 or (r.is_demo and r.owner_user_id is distinct from p_actor_id)
 then raise exception 'active scoped director attestation required' using errcode='42501';end if;
 if p_amount_minor is null or p_amount_minor<0 or p_currency is distinct from r.currency or p_as_of is null or p_as_of>now()
 or p_idempotency_key is null or length(p_idempotency_key) not between 1 and 200
 then raise exception 'explicit nonnegative cash, currency, cutoff and idempotency key required' using errcode='22023';end if;
 fingerprint:=encode(digest('establish_opening_cash'||jsonb_build_object('actor_id',p_actor_id,'amount_minor',p_amount_minor::text,'currency',p_currency,
 'as_of_epoch',extract(epoch from p_as_of),'evidence_source_id',p_evidence_source_id)::text,'sha256'),'hex');
 select * into prior from finance_operations where organization_id=p_organization_id and run_id=p_run_id and idempotency_key=p_idempotency_key;
 if found then
 if prior.operation<>'establish_opening_cash' or prior.request_hash<>fingerprint then raise exception 'idempotency key conflict' using errcode='23505';end if;
 return prior.result;
 end if;
 if r.cash_established then raise exception 'opening cash already established; use reviewed reconciliation' using errcode='23514';end if;
 select * into strict evidence from source_items where organization_id=p_organization_id and run_id=p_run_id and id=p_evidence_source_id;
 if evidence.source_type<>'owner_attestation' or evidence.metadata->>'evidence_status' is distinct from 'owner_attested'
 or evidence.metadata->>'attested_by' is distinct from p_actor_id::text
 or coalesce(evidence.metadata->>'amount_minor','') !~ '^[0-9]+$'
 or (evidence.metadata->>'amount_minor')::numeric is distinct from p_amount_minor::numeric
 or evidence.metadata->>'currency' is distinct from p_currency
 or (evidence.metadata->>'as_of')::timestamptz is distinct from p_as_of
 then raise exception 'immutable source does not attest this exact opening snapshot' using errcode='23514';end if;
 if p_amount_minor>0 then
 insert into ledger_transactions(organization_id,run_id,description,idempotency_key)
 values(p_organization_id,p_run_id,'Director-attested opening cash','opening:'||p_idempotency_key) returning id into journal_uuid;
 insert into ledger_entries(organization_id,run_id,transaction_id,account,currency,amount_minor) values
 (p_organization_id,p_run_id,journal_uuid,'cash',p_currency,p_amount_minor),
 (p_organization_id,p_run_id,journal_uuid,'opening_equity',p_currency,-p_amount_minor);
 end if;
 update demo_runs set cash_established=true,cash_evidence_status='owner_attested',reconciled_at=p_as_of,revision=revision+1,updated_at=now() where id=p_run_id;
 result:=jsonb_build_object('run_id',p_run_id,'amount_minor',p_amount_minor::text,'currency',p_currency,'as_of',p_as_of,
 'evidence_status','owner_attested','source_id',p_evidence_source_id,'ledger_transaction_id',journal_uuid);
 insert into finance_operations(organization_id,run_id,idempotency_key,operation,request_hash,result)
 values(p_organization_id,p_run_id,p_idempotency_key,'establish_opening_cash',fingerprint,result);
 perform finance_audit(p_organization_id,p_run_id,'opening_snapshot_established',jsonb_build_object('attested_by',p_actor_id,'source_id',p_evidence_source_id,
 'amount_minor',p_amount_minor::text,'currency',p_currency,'as_of',p_as_of,'evidence_status','owner_attested'));
 return result;
end $$;
revoke all on function public.establish_finance_opening_cash(uuid,uuid,uuid,bigint,text,timestamptz,uuid,text) from public,anon,authenticated;
grant execute on function public.establish_finance_opening_cash(uuid,uuid,uuid,bigint,text,timestamptz,uuid,text) to service_role;
commit;
