-- Incoming x402 sponsor/report payments: one receipt, one balanced posting,
-- globally across scopes. Testnet only; receipt verifier is a trusted service.
begin;
create table public.verified_onchain_receipts (
 network text not null check(network='eip155:84532'),transaction_hash text not null check(transaction_hash ~ '^0x[0-9a-f]{64}$'),
 log_index integer not null check(log_index>=0),organization_id uuid not null,run_id uuid not null,
 amount_minor bigint not null check(amount_minor>0),amount_base_units numeric(78,0) not null check(amount_base_units>0),
 token_address text not null,payer text not null,recipient text not null,receipt jsonb not null,
 ledger_transaction_id uuid not null,source_id uuid not null,created_at timestamptz not null default now(),
 primary key(network,transaction_hash,log_index),
 foreign key(organization_id,run_id) references public.demo_runs(organization_id,id),
 foreign key(organization_id,run_id,ledger_transaction_id) references public.ledger_transactions(organization_id,run_id,id),
 foreign key(organization_id,run_id,source_id) references public.source_items(organization_id,run_id,id)
);
alter table public.verified_onchain_receipts enable row level security;
revoke all on public.verified_onchain_receipts from public,anon,authenticated;
grant select,insert on public.verified_onchain_receipts to service_role;
create trigger immutable_onchain_receipts before update or delete on public.verified_onchain_receipts for each row execute function public.finance_immutable();

create function public.record_finance_income(p_organization_id uuid,p_run_id uuid,p_receipt jsonb,p_artifact_path text,p_content_sha256 text) returns jsonb
language plpgsql security definer set search_path=public,pg_temp as $$
declare prior verified_onchain_receipts; tx text; idx integer; amount bigint; base numeric; source_uuid uuid; journal_uuid uuid; receipt jsonb;
begin
 perform finance_require_service();perform finance_lock_run(p_organization_id,p_run_id);
 receipt:=finance_json_money_strings(p_receipt);
 tx:=lower(receipt->>'provider_reference');idx:=(receipt->>'log_index')::int;amount:=(receipt->>'amount_minor')::bigint;base:=(receipt->>'amount_base_units')::numeric;
 if jsonb_typeof(receipt) is distinct from 'object' or not(receipt ?& array['provider_reference','destination','sender','amount_minor','amount_base_units','asset','asset_decimals','token_address','network','status','verification','log_index'])
 or receipt->>'network' is distinct from 'eip155:84532' or receipt->>'asset' is distinct from 'USDC' or receipt->>'asset_decimals' is distinct from '6'
 or lower(receipt->>'token_address') is distinct from lower('0x036CbD53842c5426634e7929541eC2318f3dCF7e')
 or receipt->>'status' is distinct from 'confirmed' or receipt->>'verification' is distinct from 'independent_json_rpc_receipt'
 or amount is null or amount<=0 or base is distinct from amount::numeric*10000 or base>100000000
 or tx is null or tx !~ '^0x[0-9a-f]{64}$' or idx is null or idx<0
 or coalesce(receipt->>'sender','') !~ '^0x[0-9a-fA-F]{40}$' or coalesce(receipt->>'destination','') !~ '^0x[0-9a-fA-F]{40}$'
 or p_artifact_path is null or p_artifact_path not like p_organization_id::text||'/'||p_run_id::text||'/artifacts/%'
 or coalesce(p_content_sha256,'') !~ '^[0-9a-f]{64}$'
 then raise exception 'verified exact testnet USDC receipt required' using errcode='23514';end if;
 if not exists(select 1 from demo_runs where id=p_run_id and organization_id=p_organization_id and currency='USD') then raise exception 'USD run required';end if;
 select * into prior from verified_onchain_receipts where network='eip155:84532' and transaction_hash=tx and log_index=idx;
 if found then
 if prior.organization_id<>p_organization_id or prior.run_id<>p_run_id or prior.amount_base_units<>base or lower(prior.recipient)<>lower(receipt->>'destination') or lower(prior.payer)<>lower(receipt->>'sender')
 then raise exception 'receipt already attributed or conflicting' using errcode='23505';end if;
 return jsonb_build_object('source_id',prior.source_id,'ledger_transaction_id',prior.ledger_transaction_id,'duplicate',true);
 end if;
 insert into source_items(organization_id,run_id,external_id,version,source_type,content_sha256,artifact_path,metadata)
 values(p_organization_id,p_run_id,'x402:'||tx||':'||idx,1,'x402',p_content_sha256,p_artifact_path,jsonb_build_object('evidence_status','provider_confirmed','network','eip155:84532','transaction_hash',tx,'log_index',idx)) returning id into source_uuid;
 insert into ledger_transactions(organization_id,run_id,description,idempotency_key) values(p_organization_id,p_run_id,'Confirmed testnet x402 sponsor report payment','x402:'||tx||':'||idx) returning id into journal_uuid;
 insert into ledger_entries(organization_id,run_id,transaction_id,account,currency,amount_minor) values
 (p_organization_id,p_run_id,journal_uuid,'cash','USD',amount),(p_organization_id,p_run_id,journal_uuid,'sponsor_income','USD',-amount);
 insert into verified_onchain_receipts(network,transaction_hash,log_index,organization_id,run_id,amount_minor,amount_base_units,token_address,payer,recipient,receipt,ledger_transaction_id,source_id)
 values('eip155:84532',tx,idx,p_organization_id,p_run_id,amount,base,receipt->>'token_address',receipt->>'sender',receipt->>'destination',receipt,journal_uuid,source_uuid);
 update demo_runs set revision=revision+1,updated_at=now() where id=p_run_id;
 perform finance_audit(p_organization_id,p_run_id,'x402_income_confirmed',jsonb_build_object('transaction_hash',tx,'source_id',source_uuid,'amount_minor',amount::text));
 return jsonb_build_object('source_id',source_uuid,'ledger_transaction_id',journal_uuid,'duplicate',false);
end $$;
revoke all on function public.record_finance_income(uuid,uuid,jsonb,text,text) from public,anon,authenticated;
grant execute on function public.record_finance_income(uuid,uuid,jsonb,text,text) to service_role;
commit;
