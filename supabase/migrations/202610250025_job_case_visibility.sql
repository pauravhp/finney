begin;
-- The UI can associate real queued/running/completed work with a case without
-- receiving the job payload, message, caller identity, result or lease secrets.
alter function public.get_finance_snapshot(uuid,uuid) rename to get_finance_snapshot_v24;
revoke all on function public.get_finance_snapshot_v24(uuid,uuid) from public,anon,authenticated,service_role;
create function public.get_finance_snapshot(p_organization_id uuid,p_run_id uuid) returns jsonb
language plpgsql security definer set search_path=public,pg_temp as $$
declare result jsonb;
begin
 -- Preserve the established organization/run authorization before any lookup.
 result:=get_finance_snapshot_v24(p_organization_id,p_run_id);
 return result||jsonb_build_object('jobs',coalesce((
  select jsonb_agg(to_jsonb(safe) order by safe.created_at desc,safe.id desc) from (
   select j.id,j.command_type,j.status,j.attempts,j.error_code,j.created_at,j.updated_at,c.id as case_id
   from jobs j left join cases c
    on c.organization_id=j.organization_id and c.run_id=j.run_id
    and j.command_type in ('review_case','director_message')
    and jsonb_typeof(j.payload->'case_id')='string'
    -- Match an existing UUID as text: malformed/untrusted payloads never cast.
    and c.id::text=lower(j.payload->>'case_id')
   where j.organization_id=p_organization_id and j.run_id=p_run_id
   order by j.created_at desc,j.id desc limit 50
  ) safe
 ),'[]'::jsonb));
end $$;
revoke all on function public.get_finance_snapshot(uuid,uuid) from public,anon,authenticated,service_role;
grant execute on function public.get_finance_snapshot(uuid,uuid) to authenticated,service_role;
commit;
