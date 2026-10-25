-- Qualify the outer object name: demo_runs also has a name column.
-- Earlier migrations remain immutable; this corrects the applied read policy.
begin;
drop policy finance_artifact_read on storage.objects;
create policy finance_artifact_read on storage.objects for select to authenticated using(
 bucket_id='finance-artifacts' and exists(
 select 1 from public.demo_runs r where
 storage.objects.name like r.organization_id::text||'/'||r.id::text||'/%'
 and public.finance_can_access(r.organization_id,r.id)
 )
);
commit;
