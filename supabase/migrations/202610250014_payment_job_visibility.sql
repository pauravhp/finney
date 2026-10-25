-- Whitelisted provider progress for actual eligible humans. No provider calls.
begin;

create function public.finance_payment_reader(p_org uuid,p_run uuid) returns boolean
language sql stable security definer set search_path=public,pg_temp as $$
 select auth.role()='authenticated' and exists(select 1 from demo_runs r join memberships m on m.organization_id=r.organization_id
 where r.organization_id=p_org and r.id=p_run and not r.is_demo and m.user_id=auth.uid() and m.active
 and (m.role='director' or (m.role='approver' and r.required_payment_approvals=2)))
$$;
create function public.finance_safe_wallet_approval_url(p_value text) returns text
language sql immutable set search_path=public,pg_temp as $$
 select case when length(p_value) between 9 and 4096
 and p_value ~ '^https://[A-Za-z0-9][A-Za-z0-9.-]*(:[0-9]{1,5})?([/?#][^[:space:][:cntrl:]]*)?$'
 then p_value else null end
$$;

-- Snapshot projection cannot be bypassed with a direct browser SELECT of the
-- raw worker result/receipt. The privileged worker keeps its existing grants.
revoke select on public.jobs,public.payments from authenticated;
grant select(id,organization_id,run_id,command_type,status,attempts,error_code,created_at,updated_at) on public.jobs to authenticated;
grant select(id,organization_id,run_id,proposal_id,amount_minor,currency,status,provider_reference,created_at,updated_at) on public.payments to authenticated;
alter policy scoped_read on public.payments using(public.finance_can_access(organization_id,run_id) and public.finance_payment_reader(organization_id,run_id));

alter function public.get_finance_snapshot(uuid,uuid) rename to get_finance_snapshot_v13;
revoke all on function public.get_finance_snapshot_v13(uuid,uuid) from public,anon,authenticated,service_role;
create function public.get_finance_snapshot(p_organization_id uuid,p_run_id uuid) returns jsonb
language plpgsql security definer set search_path=public,pg_temp as $$
declare result jsonb;r demo_runs;eligible boolean;
begin
 result:=get_finance_snapshot_v13(p_organization_id,p_run_id);
 eligible:=finance_payment_reader(p_organization_id,p_run_id);
 if not eligible then return result||jsonb_build_object('payment_jobs','[]'::jsonb,'payments','[]'::jsonb);end if;
 select * into strict r from demo_runs where organization_id=p_organization_id and id=p_run_id;
 return result||jsonb_build_object(
 'payment_jobs',coalesce((select jsonb_agg(to_jsonb(safe) order by safe.created_at desc,safe.id desc) from (
 select j.id,a.id as proposal_id,p.id as payment_id,j.status,j.created_at,j.updated_at,
 case when j.result->>'status' in ('completed','blocked','failed','pending_verification') then j.result->>'status' else null end as outcome_status,
 case when coalesce(j.result->>'reason',j.error_code) ~ '^[a-z][a-z0-9_]{0,119}$' then coalesce(j.result->>'reason',j.error_code) else null end as reason,
 case when p.provider_reference ~ '^0x[0-9a-fA-F]{64}$' or (p.provider_reference ~ '^wallet-request:[A-Za-z0-9_.:-]+$' and length(p.provider_reference)<=271) then p.provider_reference else null end as provider_reference
 from jobs j join action_proposals a on a.organization_id=j.organization_id and a.run_id=j.run_id
 and a.id::text=lower(j.payload->>'proposal_id')
 left join payments p on p.organization_id=a.organization_id and p.run_id=a.run_id and p.proposal_id=a.id
 where j.organization_id=p_organization_id and j.run_id=p_run_id and j.command_type='execute_payment'
 order by j.created_at desc,j.id desc limit 50) safe),'[]'::jsonb),
 'payments',coalesce((select jsonb_agg(jsonb_build_object('id',p.id,'proposal_id',a.id,'status',p.status,
 'provider_reference',case when p.provider_reference ~ '^0x[0-9a-fA-F]{64}$' or (p.provider_reference ~ '^wallet-request:[A-Za-z0-9_.:-]+$' and length(p.provider_reference)<=271) then p.provider_reference else null end,
 'can_reconcile',r.status='active' and (r.expires_at is null or r.expires_at>now()) and (p.status='submitted' or (p.status='uncertain' and p.provider_reference like 'wallet-request:%')),
 'approval_url',case when r.status='active' and (r.expires_at is null or r.expires_at>now()) and p.status='uncertain' and a.status='reserved'
 and finance_proposal_policy_matches(a,r) and a.run_revision=r.revision and a.expires_at>now()
 and finance_eligible_approval_count(a)>=r.required_payment_approvals and not exists(select 1 from approvals x where x.proposal_id=a.id and x.decision='reject')
 then (select finance_safe_wallet_approval_url(j.result->>'approval_url') from jobs j where j.organization_id=p_organization_id and j.run_id=p_run_id
 and j.command_type='execute_payment' and lower(j.payload->>'proposal_id')=a.id::text and lower(j.result->>'payment_id')=p.id::text
 and j.result->>'reason'='awaiting_coinbase_wallet_approval' and p.provider_reference='wallet-request:'||(j.result->>'request_id')
 and finance_safe_wallet_approval_url(j.result->>'approval_url') is not null order by j.created_at desc,j.id desc limit 1) else null end,
 'created_at',p.created_at,'updated_at',p.updated_at) order by p.created_at desc)
 from payments p join action_proposals a on a.organization_id=p.organization_id and a.run_id=p.run_id and a.id=p.proposal_id
 where p.organization_id=p_organization_id and p.run_id=p_run_id),'[]'::jsonb));
end $$;

revoke all on function public.finance_payment_reader(uuid,uuid),public.finance_safe_wallet_approval_url(text),public.get_finance_snapshot(uuid,uuid) from public,anon,authenticated,service_role;
grant execute on function public.finance_payment_reader(uuid,uuid) to authenticated;
grant execute on function public.get_finance_snapshot(uuid,uuid) to authenticated,service_role;
commit;
