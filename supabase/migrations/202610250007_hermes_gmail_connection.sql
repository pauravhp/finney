-- Bind a verified mailbox grant and its public connection metadata atomically.
-- Only the trusted backend can call this; a director identity alone is not a grant.
begin;
create function public.connect_hermes_gmail(
 p_organization_id uuid, p_run_id uuid, p_director_user_id uuid,
 p_encrypted_token text, p_mailbox text, p_query text
) returns jsonb language plpgsql security definer set search_path=public,pg_temp as $$
declare connected_id uuid;
begin
 perform finance_require_service();
 perform 1 from demo_runs where organization_id=p_organization_id and id=p_run_id
   and status='active' and not is_demo and (expires_at is null or expires_at>now()) for update;
 if not found then raise exception 'active private event required' using errcode='42501'; end if;
 perform 1 from memberships where organization_id=p_organization_id and user_id=p_director_user_id
   and active and role='director' for update;
 if not found then raise exception 'current director required' using errcode='42501'; end if;
 if p_encrypted_token is null or length(p_encrypted_token)<40
   or p_mailbox is null or length(p_mailbox)>320 or p_mailbox !~ '^[^[:space:]@]+@[^[:space:]@]+$'
   or p_query is null or p_query !~ '^label:[[:alnum:]_./-]+$'
 then raise exception 'valid mailbox grant and finance label required' using errcode='22023'; end if;
 insert into connector_secrets(organization_id,run_id,provider,encrypted_token)
 values(p_organization_id,p_run_id,'gmail',p_encrypted_token)
 on conflict(organization_id,run_id,provider) do update
 set encrypted_token=excluded.encrypted_token,updated_at=clock_timestamp();
 insert into connections(organization_id,run_id,provider,status,data)
 values(p_organization_id,p_run_id,'gmail','connected',jsonb_build_object(
   'auth_backend','hermes','connected_by',p_director_user_id,'mailbox',p_mailbox,'query',p_query,
   'scopes',jsonb_build_array('gmail.readonly'),'history_id',null,'label_id',null,
   'mailbox_scope',null,'last_intake_count',0))
 on conflict(organization_id,run_id,provider) do update
 set status=excluded.status,data=excluded.data,updated_at=clock_timestamp()
 returning id into connected_id;
 perform finance_audit(p_organization_id,p_run_id,'gmail_connected',jsonb_build_object(
   'connection_id',connected_id,'connected_by',p_director_user_id,'auth_backend','hermes'));
 return jsonb_build_object('status','connected','connection_id',connected_id);
end $$;
revoke all on function public.connect_hermes_gmail(uuid,uuid,uuid,text,text,text) from public,anon,authenticated;
grant execute on function public.connect_hermes_gmail(uuid,uuid,uuid,text,text,text) to service_role;
commit;
