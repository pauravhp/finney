-- Synthetic seeding authority and public inference limits survive visitor resets.
-- No seed financial records, provider calls or approval policy changes occur here.
begin;

create table public.finance_demo_owner_limits (
 user_id uuid primary key references auth.users(id),model_call_limit integer not null default 120 check(model_call_limit between 1 and 10000),
 reserved_model_calls bigint not null default 0 check(reserved_model_calls>=0),
 created_at timestamptz not null default now(),updated_at timestamptz not null default now()
);
create table public.finance_demo_daily_limits (
 utc_day date primary key,model_call_limit integer not null default 600 check(model_call_limit between 1 and 100000),
 reserved_model_calls bigint not null default 0 check(reserved_model_calls>=0),
 updated_at timestamptz not null default now()
);
alter table public.finance_demo_owner_limits enable row level security;
alter table public.finance_demo_daily_limits enable row level security;
revoke all on public.finance_demo_owner_limits,public.finance_demo_daily_limits from public,anon,authenticated,service_role;
grant select on public.finance_demo_owner_limits to authenticated;
create policy owner_budget_read on public.finance_demo_owner_limits for select to authenticated using(user_id=(select auth.uid()));

-- Preserve prior public usage, including cancelled/expired runs. Existing usage
-- above a new cap stays recorded in full and blocks further claims; it is not
-- erased, clamped, refunded or renewed by this migration.
with usage as (
 select r.owner_user_id as owner_id,i.max_model_calls from finance_inference_reservations i
 join demo_runs r on r.organization_id=i.organization_id and r.id=i.run_id where r.is_demo
 union all
 select r.owner_user_id,a.max_model_calls from finance_improvement_attempts a
 join demo_runs r on r.organization_id=a.organization_id and r.id=a.run_id where r.is_demo
)
insert into finance_demo_owner_limits(user_id,reserved_model_calls)
select owner_id,sum(max_model_calls) from usage group by owner_id;
with usage as (
 select (i.created_at at time zone 'UTC')::date as utc_day,i.max_model_calls from finance_inference_reservations i
 join demo_runs r on r.organization_id=i.organization_id and r.id=i.run_id where r.is_demo
 union all
 select (a.created_at at time zone 'UTC')::date,a.max_model_calls from finance_improvement_attempts a
 join demo_runs r on r.organization_id=a.organization_id and r.id=a.run_id where r.is_demo
)
insert into finance_demo_daily_limits(utc_day,reserved_model_calls)
select utc_day,sum(max_model_calls) from usage group by utc_day;

create function public.assert_finance_demo_owner(p_organization_id uuid,p_run_id uuid,p_actor_id uuid) returns jsonb
language plpgsql security definer set search_path=public,pg_temp as $$
declare r demo_runs;
begin
 perform finance_require_service();perform finance_lock_run(p_organization_id,p_run_id);
 select * into strict r from demo_runs where organization_id=p_organization_id and id=p_run_id;
 if p_actor_id is null or not r.is_demo or r.owner_user_id is distinct from p_actor_id
 or not exists(select 1 from memberships where organization_id=p_organization_id and user_id=p_actor_id and active and role='director') then
 raise exception 'current active demo owner required' using errcode='42501';end if;
 return jsonb_build_object('authorized',true,'is_demo',true,'organization_id',p_organization_id,'run_id',p_run_id,'owner_user_id',r.owner_user_id);
end $$;

-- Keep the existing kernel, including immutable approval/evaluation and per-run
-- guards, behind this new outer reservation check. Old entrypoint is not callable.
alter function public.finance_kernel_call(uuid,uuid,text,jsonb) rename to finance_kernel_call_v12;
revoke all on function public.finance_kernel_call_v12(uuid,uuid,text,jsonb) from public,anon,authenticated,service_role;
create function public.finance_kernel_call(p_organization_id uuid,p_run_id uuid,p_operation text,p_arguments jsonb) returns jsonb
language plpgsql security definer set search_path=public,pg_temp as $$
declare r demo_runs;owner_limit finance_demo_owner_limits;daily_limit finance_demo_daily_limits;
 result jsonb;calls integer;today_utc date:=(now() at time zone 'UTC')::date;
begin
 perform finance_require_service();perform finance_lock_run(p_organization_id,p_run_id);
 select * into strict r from demo_runs where organization_id=p_organization_id and id=p_run_id;
 if not r.is_demo or p_operation not in ('reserve_run_inference','claim_improvement_attempt') then
 return finance_kernel_call_v12(p_organization_id,p_run_id,p_operation,p_arguments);end if;
 calls:=(p_arguments->>'max_model_calls')::integer;
 if calls is null or calls not between 1 and 40 then raise exception 'model call reservation must be 1 to 40' using errcode='22023';end if;
 insert into finance_demo_owner_limits(user_id) values(r.owner_user_id) on conflict do nothing;
 select * into strict owner_limit from finance_demo_owner_limits where user_id=r.owner_user_id for update;
 insert into finance_demo_daily_limits(utc_day) values(today_utc) on conflict do nothing;
 select * into strict daily_limit from finance_demo_daily_limits where utc_day=today_utc for update;
 if owner_limit.reserved_model_calls+calls>owner_limit.model_call_limit then
 return jsonb_build_object('claimed',false,'reason','demo_owner_lifetime_model_budget_exhausted');end if;
 if daily_limit.reserved_model_calls+calls>daily_limit.model_call_limit then
 return jsonb_build_object('claimed',false,'reason','demo_daily_model_budget_exhausted');end if;
 result:=finance_kernel_call_v12(p_organization_id,p_run_id,p_operation,p_arguments);
 -- A failed or duplicate inner claim never charges a second owner/global allowance.
 -- A successful reservation remains charged even after timeout, rejection or reset.
 if result->>'claimed'='true' then
 update finance_demo_owner_limits set reserved_model_calls=reserved_model_calls+calls,updated_at=now() where user_id=r.owner_user_id;
 update finance_demo_daily_limits set reserved_model_calls=reserved_model_calls+calls,updated_at=now() where utc_day=today_utc;
 end if;
 return result;
end $$;

revoke all on function public.assert_finance_demo_owner(uuid,uuid,uuid),public.finance_kernel_call(uuid,uuid,text,jsonb) from public,anon,authenticated,service_role;
grant execute on function public.assert_finance_demo_owner(uuid,uuid,uuid),public.finance_kernel_call(uuid,uuid,text,jsonb) to service_role;
commit;
