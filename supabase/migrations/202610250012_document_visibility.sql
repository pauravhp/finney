begin;
-- Expose only document provenance fields needed to review originals. Connector
-- secrets and broad source metadata are deliberately outside this projection.
alter function public.get_finance_snapshot(uuid,uuid) rename to get_finance_snapshot_v10;
revoke all on function public.get_finance_snapshot_v10(uuid,uuid) from public,anon,authenticated,service_role;
create function public.get_finance_snapshot(p_organization_id uuid,p_run_id uuid) returns jsonb
language plpgsql security definer set search_path=public,pg_temp as $$
declare result jsonb;
begin
 result:=get_finance_snapshot_v10(p_organization_id,p_run_id);
 return result||jsonb_build_object(
 'source_items',coalesce((select jsonb_agg(jsonb_build_object(
 'id',s.id,'external_id',s.external_id,'version',s.version,'source_type',s.source_type,
 'content_sha256',s.content_sha256,'artifact_path',s.artifact_path,
 'metadata',case when s.source_type='document' then jsonb_build_object(
 'filename',s.metadata->'filename','content_type',s.metadata->'content_type',
 'raw_artifact_path',s.metadata->'raw_artifact_path','extraction_status',s.metadata->'extraction_status',
 'extraction_reason',s.metadata->'extraction_reason','parent_source_ref',s.metadata->'parent_source_ref',
 'document_sha256',s.metadata->'document_sha256','evidence_state','reported') else '{}'::jsonb end)
 order by s.created_at) from source_items s where s.organization_id=p_organization_id and s.run_id=p_run_id),'[]'),
 'jobs',coalesce((select jsonb_agg(to_jsonb(j) order by j.created_at desc) from (
 select id,command_type,status,attempts,error_code,created_at,updated_at from jobs
 where organization_id=p_organization_id and run_id=p_run_id order by created_at desc limit 50) j),'[]'));
end $$;
revoke all on function public.get_finance_snapshot(uuid,uuid) from public,anon,authenticated,service_role;
grant execute on function public.get_finance_snapshot(uuid,uuid) to authenticated,service_role;
commit;
