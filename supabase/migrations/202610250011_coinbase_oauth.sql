-- Application-owned OAuth only. This neither creates a wallet nor sends funds.
begin;
alter table public.connector_secrets add column refresh_claim_id uuid,add column refresh_claimed_at timestamptz;

create function public.finance_require_coinbase_director(p_org uuid,p_run uuid,p_director uuid) returns void
language plpgsql security definer set search_path=public,pg_temp as $$
declare r demo_runs;
begin
 perform finance_require_service();perform finance_lock_run(p_org,p_run);
 select * into strict r from demo_runs where organization_id=p_org and id=p_run;
 if r.is_demo or p_director is null then raise exception 'private current director required for Coinbase authorization' using errcode='42501'; end if;
 perform 1 from memberships where organization_id=p_org and user_id=p_director and role='director' and active for update;
 if not found then raise exception 'private current director required for Coinbase authorization' using errcode='42501'; end if;
end $$;

create function public.connect_coinbase_wallet(p_organization_id uuid,p_run_id uuid,p_director_user_id uuid,p_pending_state_hash text,p_encrypted_token text) returns jsonb
language plpgsql security definer set search_path=public,pg_temp as $$
declare pending oauth_pending;
begin
 perform finance_require_coinbase_director(p_organization_id,p_run_id,p_director_user_id);
 if coalesce(p_pending_state_hash,'') !~ '^[0-9a-f]{64}$' or length(coalesce(p_encrypted_token,'')) not between 80 and 131072 then
 raise exception 'encrypted Coinbase authorization and pending receipt required' using errcode='22023'; end if;
 select * into pending from oauth_pending where state_hash=p_pending_state_hash and organization_id=p_organization_id and run_id=p_run_id
 and provider='coinbase_wallet_oauth' and user_id=p_director_user_id and redirect_uri='http://127.0.0.1:8768/oauth/coinbase/callback'
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

create function public.claim_coinbase_token_refresh(p_organization_id uuid,p_run_id uuid,p_director_user_id uuid,p_expected_updated_at timestamptz) returns jsonb
language plpgsql security definer set search_path=public,pg_temp as $$
declare claim uuid:=gen_random_uuid();
begin
 perform finance_require_coinbase_director(p_organization_id,p_run_id,p_director_user_id);
 if not exists(select 1 from connections where organization_id=p_organization_id and run_id=p_run_id and provider='coinbase_wallet'
 and status='connected' and data->>'connected_by'=p_director_user_id::text) then raise exception 'current Coinbase connection required' using errcode='42501'; end if;
 update connector_secrets set refresh_claim_id=claim,refresh_claimed_at=clock_timestamp()
 where organization_id=p_organization_id and run_id=p_run_id and provider='coinbase_wallet' and updated_at=p_expected_updated_at and refresh_claim_id is null;
 if not found then return jsonb_build_object('claimed',false,'reason','coinbase_refresh_already_claimed_or_connection_changed'); end if;
 return jsonb_build_object('claimed',true,'claim_id',claim);
end $$;

create function public.rotate_coinbase_wallet_token(p_organization_id uuid,p_run_id uuid,p_director_user_id uuid,p_expected_updated_at timestamptz,p_refresh_claim_id uuid,p_encrypted_token text) returns jsonb
language plpgsql security definer set search_path=public,pg_temp as $$
begin
 perform finance_require_coinbase_director(p_organization_id,p_run_id,p_director_user_id);
 if length(coalesce(p_encrypted_token,'')) not between 80 and 131072 or p_refresh_claim_id is null then raise exception 'claimed encrypted credential required' using errcode='22023'; end if;
 if not exists(select 1 from connections where organization_id=p_organization_id and run_id=p_run_id and provider='coinbase_wallet'
 and status='connected' and data->>'connected_by'=p_director_user_id::text) then raise exception 'current Coinbase connection required' using errcode='42501'; end if;
 update connector_secrets set encrypted_token=p_encrypted_token,updated_at=clock_timestamp(),refresh_claim_id=null,refresh_claimed_at=null
 where organization_id=p_organization_id and run_id=p_run_id and provider='coinbase_wallet' and updated_at=p_expected_updated_at and refresh_claim_id=p_refresh_claim_id;
 if not found then raise exception 'Coinbase connection changed; do not overwrite a new grant' using errcode='40001'; end if;
 perform finance_audit(p_organization_id,p_run_id,'coinbase_oauth_refreshed','{}');
 return jsonb_build_object('status','refreshed');
end $$;

revoke all on function public.finance_require_coinbase_director(uuid,uuid,uuid),public.connect_coinbase_wallet(uuid,uuid,uuid,text,text),
 public.claim_coinbase_token_refresh(uuid,uuid,uuid,timestamptz),public.rotate_coinbase_wallet_token(uuid,uuid,uuid,timestamptz,uuid,text) from public,anon,authenticated,service_role;
grant execute on function public.connect_coinbase_wallet(uuid,uuid,uuid,text,text),public.claim_coinbase_token_refresh(uuid,uuid,uuid,timestamptz),
 public.rotate_coinbase_wallet_token(uuid,uuid,uuid,timestamptz,uuid,text) to service_role;
commit;
