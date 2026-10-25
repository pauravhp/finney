-- Permit hosted HTTPS callback receipts; the service pins the exact registered URI.
-- Existing scope, single-use claim, director and private-run checks stay in force.
begin;
create or replace function public.connect_coinbase_wallet(p_organization_id uuid,p_run_id uuid,p_director_user_id uuid,p_pending_state_hash text,p_encrypted_token text) returns jsonb
language plpgsql security definer set search_path=public,pg_temp as $$
declare pending oauth_pending;
begin
 perform finance_require_coinbase_director(p_organization_id,p_run_id,p_director_user_id);
 if coalesce(p_pending_state_hash,'') !~ '^[0-9a-f]{64}$' or length(coalesce(p_encrypted_token,'')) not between 80 and 131072 then
 raise exception 'encrypted Coinbase authorization and pending receipt required' using errcode='22023'; end if;
 select * into pending from oauth_pending where state_hash=p_pending_state_hash and organization_id=p_organization_id and run_id=p_run_id
 and provider='coinbase_wallet_oauth' and user_id=p_director_user_id
 and (redirect_uri='http://127.0.0.1:8768/oauth/coinbase/callback'
      or redirect_uri ~ '^https://[a-z0-9]([a-z0-9.-]*[a-z0-9])?[.][a-z][a-z0-9-]*/oauth/coinbase/callback$')
 and expires_at='1970-01-01T00:00:00+00:00' and created_at>now()-interval '10 minutes' for update;
 if not found then raise exception 'claimed scoped Coinbase authorization required' using errcode='23514'; end if;
 insert into connector_secrets(organization_id,run_id,provider,encrypted_token,updated_at)
 values(p_organization_id,p_run_id,'coinbase_wallet',p_encrypted_token,clock_timestamp())
 on conflict(organization_id,run_id,provider) do update set encrypted_token=excluded.encrypted_token,updated_at=excluded.updated_at,refresh_claim_id=null,refresh_claimed_at=null;
 insert into connections(organization_id,run_id,provider,status,data,updated_at)
 values(p_organization_id,p_run_id,'coinbase_wallet','connected',jsonb_build_object('connected_by',p_director_user_id,'auth_backend','mcp_oauth',
 'issuer','https://wallet-mcp.coinbase.com','server_url','https://wallet-mcp.coinbase.com','scopes',jsonb_build_array('agent_wallet:transact','agent_wallet:escalate'),
 'wallet_identity_verified',false,'wallet_approval_required',true),clock_timestamp())
 on conflict(organization_id,run_id,provider) do update set status=excluded.status,data=excluded.data,updated_at=excluded.updated_at;
 delete from oauth_pending where state_hash=pending.state_hash;
 perform finance_audit(p_organization_id,p_run_id,'coinbase_oauth_connected',jsonb_build_object('connected_by',p_director_user_id,'wallet_identity_verified',false));
 return jsonb_build_object('status','connected','auth_backend','mcp_oauth','wallet_identity_verified',false);
end $$;

commit;
