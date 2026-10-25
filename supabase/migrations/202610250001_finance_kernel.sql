-- Hosted Supabase migration. All financial writes are through bounded RPCs.
begin;
create extension if not exists pgcrypto with schema extensions;

create table public.organizations (
 id uuid primary key default gen_random_uuid(), name text not null, created_at timestamptz not null default now()
);
create table public.memberships (
 organization_id uuid not null references public.organizations(id), user_id uuid not null references auth.users(id),
 role text not null check(role in ('director','finance','approver','viewer')), active boolean not null default true,
 primary key(organization_id,user_id)
);
create table public.demo_runs (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null references public.organizations(id),
 name text not null, owner_user_id uuid references auth.users(id), is_demo boolean not null default false,
 status text not null default 'active' check(status in ('active','cancelled','expired','closed')),
 currency text not null default 'USD' check(currency ~ '^[A-Z0-9]{3,12}$'), revision bigint not null default 0,
 cash_established boolean not null default false, cash_evidence_status text not null default 'unknown',
 reconciled_at timestamptz, expires_at timestamptz, created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
 unique(organization_id,id), check(not is_demo or owner_user_id is not null)
);
create function public.finance_can_access(p_org uuid,p_run uuid) returns boolean
language sql stable security definer set search_path=public,pg_temp as $$
 select exists(select 1 from demo_runs r join memberships m on m.organization_id=r.organization_id
 where r.organization_id=p_org and r.id=p_run and m.user_id=auth.uid() and m.active
 and (not r.is_demo or r.owner_user_id=auth.uid()))
$$;
create function public.finance_is_member(p_org uuid) returns boolean language sql stable security definer set search_path=public,pg_temp as $$
 select exists(select 1 from memberships where organization_id=p_org and user_id=auth.uid() and active)
$$;
create function public.finance_require_scope(p_org uuid,p_run uuid,p_roles text[] default null) returns void
language plpgsql security definer set search_path=public,pg_temp as $$
begin
 if not finance_can_access(p_org,p_run) then raise exception 'scope denied' using errcode='42501'; end if;
 if p_roles is not null and not exists(select 1 from memberships where organization_id=p_org and user_id=auth.uid() and active and role=any(p_roles))
 then raise exception 'role denied' using errcode='42501'; end if;
end $$;
create function public.finance_require_service() returns void language plpgsql stable set search_path=public,pg_temp as $$
begin
 if coalesce(auth.role(),'') <> 'service_role' then raise exception 'worker credential required' using errcode='42501'; end if;
end $$;
create function public.finance_lock_run(p_org uuid,p_run uuid) returns void language plpgsql set search_path=public,pg_temp as $$
begin
 perform 1 from demo_runs where organization_id=p_org and id=p_run and status='active' and (expires_at is null or expires_at>now()) for update;
 if not found then raise exception 'inactive or missing run' using errcode='22023'; end if;
end $$;
create function public.finance_json_money_strings(p_value jsonb) returns jsonb
language plpgsql immutable set search_path=public,pg_temp as $$
declare item record; result jsonb;
begin
 if jsonb_typeof(p_value)='object' then
 result:='{}';
 for item in select key,value from jsonb_each(p_value) loop
 if item.key ~ '(_minor|_base_units)$' and item.value<>'null'::jsonb then
 if (item.value#>>'{}') !~ '^-?[0-9]+$' then raise exception 'money must use integer minor/base units' using errcode='22023'; end if;
 result:=result||jsonb_build_object(item.key,(item.value#>>'{}')::numeric::text);
 else result:=result||jsonb_build_object(item.key,finance_json_money_strings(item.value)); end if;
 end loop; return result;
 elsif jsonb_typeof(p_value)='array' then
 select coalesce(jsonb_agg(finance_json_money_strings(value)),'[]') into result from jsonb_array_elements(p_value); return result;
 end if; return p_value;
end $$;

create table public.connections (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null, run_id uuid not null,
 provider text not null, status text not null default 'unconfigured', data jsonb not null default '{}',
 updated_at timestamptz not null default now(), unique(organization_id,run_id,provider),
 foreign key(organization_id,run_id) references demo_runs(organization_id,id)
);
create table public.source_items (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null,run_id uuid not null,
 external_id text not null, version integer not null default 1 check(version>0), source_type text not null,
 content_sha256 text not null, artifact_path text, metadata jsonb not null default '{}', created_at timestamptz not null default now(),
 unique(organization_id,run_id,external_id,version),unique(organization_id,run_id,id),
 foreign key(organization_id,run_id) references demo_runs(organization_id,id)
);
create table public.documents (
 id uuid primary key default gen_random_uuid(), organization_id uuid not null,run_id uuid not null,
 source_id uuid,artifact_path text not null,content_sha256 text not null,content_type text not null,
 created_at timestamptz not null default now(),unique(organization_id,run_id,artifact_path),
 foreign key(organization_id,run_id) references demo_runs(organization_id,id),
 foreign key(organization_id,run_id,source_id) references source_items(organization_id,run_id,id)
);
create table public.cases (
 id uuid primary key default gen_random_uuid(),organization_id uuid not null,run_id uuid not null,
 title text not null,status text not null default 'open',version integer not null default 1,
 data jsonb not null default '{}',updated_at timestamptz not null default now(),
 unique(organization_id,run_id,id),foreign key(organization_id,run_id) references demo_runs(organization_id,id)
);
create table public.case_dependencies (
 organization_id uuid not null,run_id uuid not null,case_id uuid not null,source_id uuid not null,source_version integer not null,
 primary key(case_id,source_id), foreign key(organization_id,run_id,case_id) references cases(organization_id,run_id,id),
 foreign key(organization_id,run_id,source_id) references source_items(organization_id,run_id,id)
);
create table public.funds (
 id uuid primary key default gen_random_uuid(),organization_id uuid not null,run_id uuid not null,name text not null,
 currency text not null,restriction jsonb not null default '{}',unique(organization_id,run_id,id),
 foreign key(organization_id,run_id) references demo_runs(organization_id,id)
);
create table public.budget_lines (
 id uuid primary key default gen_random_uuid(),organization_id uuid not null,run_id uuid not null,name text not null,
 currency text not null,allocated_minor bigint not null check(allocated_minor>=0),version integer not null default 1,
 unique(organization_id,run_id,id),foreign key(organization_id,run_id) references demo_runs(organization_id,id)
);
create table public.obligations (
 id uuid primary key default gen_random_uuid(),organization_id uuid not null,run_id uuid not null,
 case_id uuid,budget_line_id uuid,title text not null,direction text not null check(direction in ('payable','receivable')),
 amount_minor bigint not null check(amount_minor>=0),settled_minor bigint not null default 0 check(settled_minor>=0 and settled_minor<=amount_minor),
 currency text not null,due_date date,status text not null default 'open' check(status in ('open','settled','cancelled','disputed')),
 evidence_status text not null default 'reported',source_refs jsonb not null default '[]',version integer not null default 1,
 updated_at timestamptz not null default now(),unique(organization_id,run_id,id),
 foreign key(organization_id,run_id) references demo_runs(organization_id,id),
 foreign key(organization_id,run_id,case_id) references cases(organization_id,run_id,id),
 foreign key(organization_id,run_id,budget_line_id) references budget_lines(organization_id,run_id,id)
);
create table public.action_proposals (
 id uuid primary key default gen_random_uuid(),organization_id uuid not null,run_id uuid not null,
 action jsonb not null,action_hash text not null,run_revision bigint not null,proposed_by uuid references auth.users(id),
 status text not null default 'pending' check(status in ('pending','rejected','reserved','executed','expired','stale')),
 required_approvals integer not null default 2 check(required_approvals=2),
 expires_at timestamptz not null,created_at timestamptz not null default now(), idempotency_key text not null,
 unique(organization_id,run_id,id),unique(organization_id,run_id,idempotency_key),
 foreign key(organization_id,run_id) references demo_runs(organization_id,id)
);
create table public.approvals (
 id uuid primary key default gen_random_uuid(),organization_id uuid not null,run_id uuid not null,proposal_id uuid not null,
 user_id uuid not null references auth.users(id),action_hash text not null,decision text not null check(decision in ('approve','reject')),
 created_at timestamptz not null default now(),unique(proposal_id,user_id),
 foreign key(organization_id,run_id,proposal_id) references action_proposals(organization_id,run_id,id)
);
create table public.payments (
 id uuid primary key default gen_random_uuid(),organization_id uuid not null,run_id uuid not null,proposal_id uuid not null,
 amount_minor bigint not null check(amount_minor>0),currency text not null,
 status text not null default 'reserved' check(status in ('reserved','submitting','uncertain','submitted','confirmed','failed')),
 provider_reference text,receipt jsonb,created_at timestamptz not null default now(),updated_at timestamptz not null default now(),
 unique(proposal_id),unique(organization_id,run_id,id),unique(provider_reference),
 foreign key(organization_id,run_id,proposal_id) references action_proposals(organization_id,run_id,id)
);
create table public.ledger_transactions (
 id uuid primary key default gen_random_uuid(),organization_id uuid not null,run_id uuid not null,
 description text not null,idempotency_key text not null,created_at timestamptz not null default now(),
 unique(organization_id,run_id,id),unique(organization_id,run_id,idempotency_key),
 foreign key(organization_id,run_id) references demo_runs(organization_id,id)
);
create table public.ledger_entries (
 id uuid primary key default gen_random_uuid(),organization_id uuid not null,run_id uuid not null,transaction_id uuid not null,
 account text not null,currency text not null,amount_minor bigint not null check(amount_minor<>0),
 foreign key(organization_id,run_id,transaction_id) references ledger_transactions(organization_id,run_id,id)
);
create table public.jobs (
 id uuid primary key default gen_random_uuid(),organization_id uuid not null,run_id uuid not null,
 command_type text not null,payload jsonb not null,requested_by uuid references auth.users(id),idempotency_key text not null,
 status text not null default 'queued' check(status in ('queued','running','completed','failed','blocked','cancelled')),
 attempts integer not null default 0,available_at timestamptz not null default now(),worker_id text,lease_token uuid,lease_expires_at timestamptz,
 result jsonb,error_code text,created_at timestamptz not null default now(),updated_at timestamptz not null default now(),
 unique(organization_id,run_id,idempotency_key),foreign key(organization_id,run_id) references demo_runs(organization_id,id)
);
create index jobs_leasable on jobs(status,available_at,created_at);
create table public.worker_heartbeats (worker_id text primary key,last_seen_at timestamptz not null default now());
create table public.audit_events (
 id bigint generated always as identity primary key,organization_id uuid not null,run_id uuid not null,event_type text not null,
 payload jsonb not null default '{}',actor_id uuid,created_at timestamptz not null default now(),
 foreign key(organization_id,run_id) references demo_runs(organization_id,id)
);
create table public.trace_events (
 id uuid primary key default gen_random_uuid(),organization_id uuid not null,run_id uuid not null,
 case_id uuid,event_type text not null,payload jsonb not null,created_at timestamptz not null default now(),
 idempotency_key text not null,unique(organization_id,run_id,idempotency_key),
 foreign key(organization_id,run_id) references demo_runs(organization_id,id),
 foreign key(organization_id,run_id,case_id) references cases(organization_id,run_id,id)
);
create table public.skill_versions (
 id uuid primary key default gen_random_uuid(),organization_id uuid not null,run_id uuid not null,skill_name text not null,version text not null,
 artifact_path text not null,content_sha256 text not null,parent_version_id uuid,status text not null default 'candidate',
 metadata jsonb not null default '{}',is_active boolean not null default false,created_at timestamptz not null default now(),
 unique(organization_id,run_id,id),unique(organization_id,run_id,skill_name,version),
 foreign key(organization_id,run_id) references demo_runs(organization_id,id),
 foreign key(organization_id,run_id,parent_version_id) references skill_versions(organization_id,run_id,id)
);
create unique index one_active_skill on skill_versions(organization_id,run_id,skill_name) where is_active;
create table public.eval_runs (
 id uuid primary key default gen_random_uuid(),organization_id uuid not null,run_id uuid not null,skill_name text not null,
 baseline_version_id uuid,candidate_version_id uuid,status text not null,metrics jsonb not null default '{}',artifact_path text,
 created_at timestamptz not null default now(),updated_at timestamptz not null default now(),unique(organization_id,run_id,id),
 foreign key(organization_id,run_id) references demo_runs(organization_id,id),
 foreign key(organization_id,run_id,baseline_version_id) references skill_versions(organization_id,run_id,id),
 foreign key(organization_id,run_id,candidate_version_id) references skill_versions(organization_id,run_id,id)
);
create table public.eval_results (
 id uuid primary key default gen_random_uuid(),organization_id uuid not null,run_id uuid not null,eval_run_id uuid not null,
 case_key text not null,variant text not null,passed boolean not null,hard_invariants_passed boolean not null,
 metrics jsonb not null default '{}',details jsonb not null default '{}',created_at timestamptz not null default now(),
 unique(eval_run_id,case_key,variant),foreign key(organization_id,run_id,eval_run_id) references eval_runs(organization_id,run_id,id)
);
create table public.promotions (
 id uuid primary key default gen_random_uuid(),organization_id uuid not null,run_id uuid not null,skill_name text not null,
 version_id uuid not null,previous_version_id uuid,eval_run_id uuid,state text not null,reason text not null,
 created_at timestamptz not null default now(),foreign key(organization_id,run_id) references demo_runs(organization_id,id),
 foreign key(organization_id,run_id,version_id) references skill_versions(organization_id,run_id,id),
 foreign key(organization_id,run_id,previous_version_id) references skill_versions(organization_id,run_id,id),
 foreign key(organization_id,run_id,eval_run_id) references eval_runs(organization_id,run_id,id)
);
create table public.report_snapshots (
 id uuid primary key default gen_random_uuid(),organization_id uuid not null,run_id uuid not null,cutoff timestamptz not null,
 data jsonb not null,artifact_path text,created_at timestamptz not null default now(),
 foreign key(organization_id,run_id) references demo_runs(organization_id,id)
);
create table public.finance_operations (
 organization_id uuid not null,run_id uuid not null,idempotency_key text not null,operation text not null,
 request_hash text not null,result jsonb not null,created_at timestamptz not null default now(),
 primary key(organization_id,run_id,idempotency_key),foreign key(organization_id,run_id) references demo_runs(organization_id,id)
);
create table public.connector_secrets (
 organization_id uuid not null,run_id uuid not null,provider text not null,encrypted_token text not null,
 updated_at timestamptz not null default now(),primary key(organization_id,run_id,provider),
 foreign key(organization_id,run_id) references demo_runs(organization_id,id)
);
create table public.oauth_pending (
 state_hash text primary key,organization_id uuid not null,run_id uuid not null,provider text not null,
 user_id uuid not null references auth.users(id),encrypted_verifier text,redirect_uri text not null,
 expires_at timestamptz not null,created_at timestamptz not null default now(),
 foreign key(organization_id,run_id) references demo_runs(organization_id,id)
);
alter table connector_secrets enable row level security;
alter table oauth_pending enable row level security;
revoke all on connector_secrets,oauth_pending from anon,authenticated;

-- Guard append-only evidence and journals even against accidental service updates.
create function public.finance_immutable() returns trigger language plpgsql set search_path=public,pg_temp as $$
begin raise exception 'immutable record; create a new version/reversal' using errcode='23514'; end $$;
create trigger immutable_sources before update or delete on source_items for each row execute function finance_immutable();
create trigger immutable_approvals before update or delete on approvals for each row execute function finance_immutable();
create trigger immutable_ledger_entries before update or delete on ledger_entries for each row execute function finance_immutable();
create trigger immutable_ledger_transactions before update or delete on ledger_transactions for each row execute function finance_immutable();
create trigger immutable_traces before update or delete on trace_events for each row execute function finance_immutable();
-- Deferred validation also covers accidental privileged inserts outside the RPC.
create function public.finance_balanced_journal() returns trigger language plpgsql set search_path=public,pg_temp as $$
begin
 if exists(select 1 from ledger_entries where transaction_id=new.transaction_id group by currency having sum(amount_minor::numeric)<>0)
 or (select count(*) from ledger_entries where transaction_id=new.transaction_id)<2
 then raise exception 'unbalanced journal' using errcode='23514'; end if; return null;
end $$;
create constraint trigger balanced_journal after insert on ledger_entries deferrable initially deferred for each row execute function finance_balanced_journal();
create function public.finance_immutable_proposal() returns trigger language plpgsql set search_path=public,pg_temp as $$
begin
 if (new.action,new.action_hash,new.run_revision,new.proposed_by,new.expires_at,new.organization_id,new.run_id)
 is distinct from (old.action,old.action_hash,old.run_revision,old.proposed_by,old.expires_at,old.organization_id,old.run_id)
 then raise exception 'proposal action is immutable' using errcode='23514'; end if; return new;
end $$;
create trigger immutable_proposal before update on action_proposals for each row execute function finance_immutable_proposal();

create function public.finance_audit(p_org uuid,p_run uuid,p_event text,p_payload jsonb default '{}') returns bigint
language plpgsql security definer set search_path=public,pg_temp as $$
declare cursor_id bigint;
begin
 insert into audit_events(organization_id,run_id,event_type,payload,actor_id) values(p_org,p_run,p_event,p_payload,auth.uid()) returning id into cursor_id;
 perform realtime.send(jsonb_build_object('organization_id',p_org,'run_id',p_run,'cursor',cursor_id),'state_changed','finance:'||p_org||':'||p_run,true);
 return cursor_id;
end $$;

create function public.get_finance_snapshot(p_organization_id uuid,p_run_id uuid) returns jsonb
language plpgsql security definer set search_path=public,pg_temp as $$
declare r demo_runs; cash numeric; committed numeric; receivable numeric; last_seen timestamptz; result jsonb;
begin
 if coalesce(auth.role(),'')<>'service_role' then perform finance_require_scope(p_organization_id,p_run_id); end if;
 select * into strict r from demo_runs where organization_id=p_organization_id and id=p_run_id;
 select coalesce(sum(amount_minor),0) into cash from ledger_entries where organization_id=p_organization_id and run_id=p_run_id and account='cash' and currency=r.currency;
 select coalesce(sum(amount_minor-settled_minor) filter(where direction='payable'),0),
 coalesce(sum(amount_minor-settled_minor) filter(where direction='receivable'),0) into committed,receivable from obligations
 where organization_id=p_organization_id and run_id=p_run_id and status in ('open','disputed') and currency=r.currency;
 select max(w.last_seen_at) into last_seen from worker_heartbeats w join jobs j on j.worker_id=w.worker_id where j.organization_id=p_organization_id and j.run_id=p_run_id;
 result:=jsonb_build_object(
 'organization',(select jsonb_build_object('id',id,'name',name) from organizations where id=p_organization_id),
 'run',jsonb_build_object('id',r.id,'name',r.name,'status',r.status,'currency',r.currency,'revision',r.revision),
 'position',jsonb_build_object('currency',r.currency,'cash_minor',case when r.cash_established then cash::text end,
 'committed_minor',committed::text,'receivable_minor',receivable::text,'available_minor',case when r.cash_established then (cash-committed)::text end,
 'evidence_status',r.cash_evidence_status,'reconciled_at',r.reconciled_at),
 'cases',coalesce((select jsonb_agg(to_jsonb(c)-'organization_id'-'run_id' order by c.updated_at desc) from cases c where c.organization_id=p_organization_id and c.run_id=p_run_id),'[]'),
 'approvals',coalesce((select jsonb_agg(jsonb_build_object('id',p.id,'action_hash',p.action_hash,'action',p.action,'status',
 case when p.status='pending' and p.run_revision<>r.revision then 'stale' when p.status='pending' and p.expires_at<=now() then 'expired' else p.status end,
 'required_approvals',p.required_approvals,'approval_count',(select count(*) from approvals a where a.proposal_id=p.id and a.decision='approve'),
 'decisions',coalesce((select jsonb_agg(jsonb_build_object('user_id',a.user_id,'decision',a.decision,'created_at',a.created_at)) from approvals a where a.proposal_id=p.id),'[]'),
 'expires_at',p.expires_at,'created_at',p.created_at) order by p.created_at desc) from action_proposals p where p.organization_id=p_organization_id and p.run_id=p_run_id),'[]'),
 'activity',coalesce((select jsonb_agg(to_jsonb(a)-'organization_id'-'run_id'-'actor_id' order by a.id) from
 (select * from audit_events where organization_id=p_organization_id and run_id=p_run_id order by id desc limit 100) a),'[]'),
 'improvements',jsonb_build_object(
 'trace_events',coalesce((select jsonb_agg(jsonb_build_object('id',t.id,'event_type',t.event_type,'created_at',t.created_at,'payload',jsonb_build_object('output',jsonb_build_object(
 'issue_type',left(t.payload->'output'->>'issue_type',200),'trace_references',t.payload->'output'->'trace_references',
 'diagnosis',left(t.payload->'output'->>'diagnosis',10000),'desired_behavior',left(t.payload->'output'->>'desired_behavior',10000)))))
 from trace_events t where t.organization_id=p_organization_id and t.run_id=p_run_id and t.event_type in ('improvement_diagnosed','actor_completed')),'[]'),
 'skill_versions',coalesce((select jsonb_agg(to_jsonb(s)-'organization_id'-'run_id') from skill_versions s where s.organization_id=p_organization_id and s.run_id=p_run_id),'[]'),
 'eval_runs',coalesce((select jsonb_agg(to_jsonb(e)-'organization_id'-'run_id') from eval_runs e where e.organization_id=p_organization_id and e.run_id=p_run_id),'[]'),
 'eval_results',coalesce((select jsonb_agg(to_jsonb(e)-'organization_id'-'run_id') from eval_results e where e.organization_id=p_organization_id and e.run_id=p_run_id),'[]'),
 'promotions',coalesce((select jsonb_agg(to_jsonb(p)-'organization_id'-'run_id') from promotions p where p.organization_id=p_organization_id and p.run_id=p_run_id),'[]')),
 'connections',coalesce((select jsonb_agg(jsonb_build_object('id',c.id,'provider',c.provider,'status',c.status,'updated_at',c.updated_at)) from connections c where c.organization_id=p_organization_id and c.run_id=p_run_id),'[]'),
 'obligations',coalesce((select jsonb_agg(to_jsonb(o)||jsonb_build_object('amount_minor',o.amount_minor::text,'settled_minor',o.settled_minor::text)) from obligations o where o.organization_id=p_organization_id and o.run_id=p_run_id),'[]'),
 'source_items',coalesce((select jsonb_agg(jsonb_build_object('id',s.id,'external_id',s.external_id,'version',s.version,'source_type',s.source_type,'content_sha256',s.content_sha256,'artifact_path',s.artifact_path)) from source_items s where s.organization_id=p_organization_id and s.run_id=p_run_id),'[]'),
 'reports',coalesce((select jsonb_agg(to_jsonb(s)-'organization_id'-'run_id' order by s.created_at desc) from report_snapshots s where s.organization_id=p_organization_id and s.run_id=p_run_id),'[]'),
 'worker',jsonb_build_object('status',case when last_seen is null then 'unknown' when last_seen>now()-interval '90 seconds' then 'online' else 'offline' end,'last_seen_at',last_seen),
 'updated_at',now()); return result;
end $$;

create function public.enqueue_finance_command(p_organization_id uuid,p_run_id uuid,p_command_type text,p_payload jsonb,p_idempotency_key text) returns uuid
language plpgsql security definer set search_path=public,pg_temp as $$
declare job jobs;
begin
 perform finance_require_scope(p_organization_id,p_run_id,array['director','finance','approver']);
 perform finance_lock_run(p_organization_id,p_run_id);
 if p_command_type is null or p_command_type not in ('intake','review_case','refresh_forecast','generate_report','evaluate_improvement','execute_payment')
 or p_idempotency_key is null or length(p_idempotency_key) not between 1 and 200 or jsonb_typeof(p_payload) is distinct from 'object' or pg_column_size(p_payload)>65536
 then raise exception 'invalid command' using errcode='22023'; end if;
 select * into job from jobs where organization_id=p_organization_id and run_id=p_run_id and idempotency_key=p_idempotency_key;
 if found then
 if job.command_type<>p_command_type or job.payload<>p_payload then raise exception 'idempotency key conflict' using errcode='23505'; end if; return job.id; end if;
 insert into jobs(organization_id,run_id,command_type,payload,requested_by,idempotency_key)
 values(p_organization_id,p_run_id,p_command_type,p_payload,auth.uid(),p_idempotency_key) returning * into job;
 perform finance_audit(p_organization_id,p_run_id,'command_queued',jsonb_build_object('job_id',job.id,'command_type',p_command_type)); return job.id;
end $$;

create function public.approve_finance_proposal(p_proposal_id uuid,p_expected_action_hash text,p_decision text) returns jsonb
language plpgsql security definer set search_path=public,pg_temp as $$
declare p action_proposals; r demo_runs; existing approvals; n integer;
begin
 select * into strict p from action_proposals where id=p_proposal_id;
 perform finance_require_scope(p.organization_id,p.run_id,array['director','approver']);
 perform finance_lock_run(p.organization_id,p.run_id);
 select * into p from action_proposals where id=p_proposal_id for update;
 select * into r from demo_runs where id=p.run_id;
 if p.proposed_by=auth.uid() then raise exception 'proposer cannot approve own action' using errcode='42501'; end if;
 if p_decision is null or p_decision not in ('approve','reject') or p.action_hash is distinct from p_expected_action_hash then raise exception 'action hash or decision mismatch' using errcode='22023'; end if;
 select * into existing from approvals where proposal_id=p.id and user_id=auth.uid();
 if found then
 if existing.decision<>p_decision then raise exception 'decision is immutable' using errcode='23514'; end if;
 else
 if p.status<>'pending' or p.expires_at<=now() or p.run_revision<>r.revision then raise exception 'proposal expired, stale or not pending' using errcode='23514'; end if;
 insert into approvals(organization_id,run_id,proposal_id,user_id,action_hash,decision) values(p.organization_id,p.run_id,p.id,auth.uid(),p.action_hash,p_decision);
 if p_decision='reject' then update action_proposals set status='rejected' where id=p.id; end if;
 perform finance_audit(p.organization_id,p.run_id,'human_decision',jsonb_build_object('proposal_id',p.id,'decision',p_decision));
 end if;
 select count(*) into n from approvals where proposal_id=p.id and decision='approve';
 return jsonb_build_object('proposal_id',p.id,'approval_count',n,'required_approvals',2,'decision',p_decision);
end $$;

create function public.create_finance_demo(p_name text default 'Finance demo',p_previous_run_id uuid default null) returns jsonb
language plpgsql security definer set search_path=public,pg_temp as $$
declare org uuid; new_run uuid; old_run demo_runs;
begin
 if auth.uid() is null then raise exception 'sign in required' using errcode='42501'; end if;
 perform pg_advisory_xact_lock(hashtextextended(auth.uid()::text,0));
 if p_previous_run_id is not null then
 select * into strict old_run from demo_runs where id=p_previous_run_id for update;
 if not old_run.is_demo or old_run.owner_user_id<>auth.uid() then raise exception 'demo owner required' using errcode='42501'; end if;
 org:=old_run.organization_id;
 update demo_runs set status='cancelled',updated_at=now() where id=old_run.id;
 update jobs set status='cancelled',lease_token=null,lease_expires_at=null where run_id=old_run.id and status in ('queued','running');
 perform finance_audit(org,old_run.id,'run_reset','{}');
 else
 select organization_id into org from memberships where user_id=auth.uid() and active and role='director' order by organization_id limit 1;
 if org is null then
 insert into organizations(name) values('Personal finance demo') returning id into org;
 insert into memberships(organization_id,user_id,role) values(org,auth.uid(),'director'); end if;
 end if;
 if (select count(*) from demo_runs where owner_user_id=auth.uid() and is_demo and status='active')>=3 then raise exception 'active demo limit reached'; end if;
 insert into demo_runs(organization_id,name,owner_user_id,is_demo,expires_at) values(org,left(p_name,100),auth.uid(),true,now()+interval '24 hours') returning id into new_run;
 perform finance_audit(org,new_run,'run_created',jsonb_build_object('is_demo',true));
 return jsonb_build_object('organization_id',org,'run_id',new_run);
end $$;

create function public.finance_worker_heartbeat(p_worker_id text) returns void language plpgsql security definer set search_path=public,pg_temp as $$
begin perform finance_require_service(); insert into worker_heartbeats(worker_id) values(p_worker_id) on conflict(worker_id) do update set last_seen_at=now(); end $$;
create function public.lease_finance_job(p_worker_id text,p_lease_seconds integer default 120) returns jsonb
language plpgsql security definer set search_path=public,pg_temp as $$
declare j jobs;
begin
 perform finance_require_service();
 if p_lease_seconds not between 10 and 600 or length(p_worker_id) not between 1 and 128 then raise exception 'invalid lease'; end if;
 perform finance_worker_heartbeat(p_worker_id);
 update jobs set status='failed',error_code='lease_retry_exhausted',lease_expires_at=null,updated_at=now()
 where status='running' and lease_expires_at<=now() and attempts>=5;
 select x.* into j from jobs x join demo_runs r on r.id=x.run_id and r.organization_id=x.organization_id
 where r.status='active' and (r.expires_at is null or r.expires_at>now()) and x.attempts<5
 and ((x.status='queued' and x.available_at<=now()) or (x.status='running' and x.lease_expires_at<=now()))
 -- A submitting payment is recovered by its durable provider state, never resubmitted blindly.
 order by x.created_at for update of x skip locked limit 1;
 if not found then return null; end if;
 update jobs set status='running',worker_id=p_worker_id,lease_token=gen_random_uuid(),lease_expires_at=now()+make_interval(secs=>p_lease_seconds),
 attempts=attempts+1,updated_at=now() where id=j.id returning * into j;
 perform finance_audit(j.organization_id,j.run_id,'job_started',jsonb_build_object('job_id',j.id,'attempts',j.attempts));
 return to_jsonb(j);
end $$;
create function public.finish_finance_job(p_job_id uuid,p_lease_token uuid,p_result jsonb) returns void
language plpgsql security definer set search_path=public,pg_temp as $$
declare j jobs;
begin perform finance_require_service();
 update jobs set status=case when p_result->>'status'='blocked' then 'blocked' else 'completed' end,result=p_result,lease_expires_at=null,updated_at=now()
 where id=p_job_id and lease_token=p_lease_token and status='running' and lease_expires_at>now() returning * into j;
 if not found then raise exception 'lease lost' using errcode='40001'; end if;
 perform finance_audit(j.organization_id,j.run_id,'job_finished',jsonb_build_object('job_id',j.id,'status',j.status));
end $$;
create function public.renew_finance_job(p_job_id uuid,p_lease_token uuid,p_lease_seconds integer default 120) returns void
language plpgsql security definer set search_path=public,pg_temp as $$
declare j jobs;
begin perform finance_require_service();
 if p_lease_seconds not between 10 and 600 then raise exception 'invalid lease'; end if;
 update jobs set lease_expires_at=now()+make_interval(secs=>p_lease_seconds),updated_at=now()
 where id=p_job_id and lease_token=p_lease_token and status='running' and lease_expires_at>now()
 and exists(select 1 from demo_runs r where r.id=jobs.run_id and r.organization_id=jobs.organization_id and r.status='active' and (r.expires_at is null or r.expires_at>now())) returning * into j;
 if not found then raise exception 'lease lost' using errcode='40001'; end if;
 perform finance_worker_heartbeat(j.worker_id);
end $$;
create function public.fail_finance_job(p_job_id uuid,p_lease_token uuid,p_error_code text,p_retryable boolean default false) returns void
language plpgsql security definer set search_path=public,pg_temp as $$
declare j jobs;
begin perform finance_require_service();
 update jobs set status=case when p_retryable and attempts<5 then 'queued' else 'failed' end,error_code=left(p_error_code,100),
 available_at=now()+make_interval(secs=>least(300,attempts*10)),lease_expires_at=null,updated_at=now()
 where id=p_job_id and lease_token=p_lease_token and status='running' and lease_expires_at>now() returning * into j;
 if not found then raise exception 'lease lost' using errcode='40001'; end if;
 perform finance_audit(j.organization_id,j.run_id,'job_failed',jsonb_build_object('job_id',j.id,'error_code',j.error_code));
end $$;

-- One scoped transactional worker entry point. Idempotency collisions are errors.
create function public.finance_kernel_call(p_organization_id uuid,p_run_id uuid,p_operation text,p_arguments jsonb) returns jsonb
language plpgsql security definer set search_path=public,extensions,pg_temp as $$
declare r demo_runs; result jsonb; prior finance_operations; key text; request_hash text; row_id uuid; p action_proposals; pay payments;
 amount bigint; v_currency text; total numeric; reserved numeric; item jsonb; old_version integer; active_id uuid; eval eval_runs;
begin
 perform finance_require_service(); perform finance_lock_run(p_organization_id,p_run_id);
 select * into strict r from demo_runs where id=p_run_id and organization_id=p_organization_id;
 key:=p_arguments->>'idempotency_key'; request_hash:=encode(digest(p_operation||p_arguments::text,'sha256'),'hex');
 if p_operation not in ('get_case','list_due_work','get_obligations','get_active_skill','get_approval_status','get_payment_status','get_trace') then
 if key is null or length(key) not between 1 and 200 then raise exception 'idempotency key required' using errcode='22023'; end if;
 select * into prior from finance_operations where organization_id=p_organization_id and run_id=p_run_id and idempotency_key=key;
 if found then if prior.request_hash<>request_hash then raise exception 'idempotency key conflict' using errcode='23505'; end if; return prior.result; end if;
 end if;
 case p_operation
 when 'get_case' then
 select to_jsonb(c) into result from cases c where c.organization_id=p_organization_id and c.run_id=p_run_id and c.id=(p_arguments->>'case_id')::uuid;
 if result is null then raise exception 'case missing' using errcode='P0002'; end if;
 when 'list_due_work' then
 select coalesce(jsonb_agg(to_jsonb(c)),'[]') into result from cases c where c.organization_id=p_organization_id and c.run_id=p_run_id and c.status<>'closed';
 when 'get_obligations' then
 select coalesce(jsonb_agg(to_jsonb(o)||jsonb_build_object('amount_minor',o.amount_minor::text,'settled_minor',o.settled_minor::text)),'[]') into result from obligations o where o.organization_id=p_organization_id and o.run_id=p_run_id;
 when 'record_source' then
 insert into source_items(organization_id,run_id,external_id,version,source_type,content_sha256,artifact_path,metadata)
 values(p_organization_id,p_run_id,p_arguments->>'external_id',coalesce((p_arguments->>'version')::int,1),p_arguments->>'source_type',p_arguments->>'content_sha256',p_arguments->>'artifact_path',coalesce(p_arguments->'metadata','{}')) returning id into row_id;
 update cases c set status='needs_review',version=c.version+1,updated_at=now(),data=c.data||jsonb_build_object('change_impact',jsonb_build_object('source_id',row_id,'reason','source_revised'))
 where c.organization_id=p_organization_id and c.run_id=p_run_id and exists(
 select 1 from case_dependencies d join source_items s on s.id=d.source_id and s.organization_id=d.organization_id and s.run_id=d.run_id
 where d.case_id=c.id and s.external_id=p_arguments->>'external_id' and s.version<coalesce((p_arguments->>'version')::int,1));
 update demo_runs set revision=revision+1,updated_at=now() where id=p_run_id;
 result:=jsonb_build_object('id',row_id);
 when 'record_case' then
 row_id:=coalesce((p_arguments->>'id')::uuid,gen_random_uuid());
 select version into old_version from cases where id=row_id and organization_id=p_organization_id and run_id=p_run_id;
 if found and old_version<>coalesce((p_arguments->>'expected_version')::int,-1) then raise exception 'stale case version' using errcode='40001'; end if;
 insert into cases(id,organization_id,run_id,title,status,data) values(row_id,p_organization_id,p_run_id,p_arguments->>'title',coalesce(p_arguments->>'status','open'),coalesce(p_arguments->'data','{}'))
 on conflict(id) do update set title=excluded.title,status=excluded.status,data=excluded.data,version=cases.version+1,updated_at=now()
 where cases.organization_id=p_organization_id and cases.run_id=p_run_id;
 if not found then raise exception 'case scope denied' using errcode='42501'; end if;
 delete from case_dependencies where organization_id=p_organization_id and run_id=p_run_id and case_id=row_id;
 for item in select value from jsonb_array_elements(coalesce(p_arguments->'data'->'source_ids','[]')) loop
 insert into case_dependencies(organization_id,run_id,case_id,source_id,source_version)
 select p_organization_id,p_run_id,row_id,s.id,s.version from source_items s where s.organization_id=p_organization_id and s.run_id=p_run_id and s.id=(item#>>'{}')::uuid;
 if not found then raise exception 'case source outside scope' using errcode='42501'; end if;
 end loop;
 update demo_runs set revision=revision+1,updated_at=now() where id=p_run_id;
 result:=jsonb_build_object('id',row_id);
 when 'record_finding' then
 select version into old_version from cases where id=(p_arguments->>'case_id')::uuid and organization_id=p_organization_id and run_id=p_run_id;
 if old_version is null or old_version<>coalesce((p_arguments->>'expected_version')::int,-1) then raise exception 'stale or missing case' using errcode='40001'; end if;
 update cases set data=data||jsonb_build_object('finding',p_arguments->'finding'),version=version+1,updated_at=now() where id=(p_arguments->>'case_id')::uuid;
 update demo_runs set revision=revision+1,updated_at=now() where id=p_run_id;
 result:=jsonb_build_object('case_id',p_arguments->>'case_id','version',old_version+1);
 when 'propose_obligation_update' then
 row_id:=coalesce((p_arguments->>'id')::uuid,gen_random_uuid());
 amount:=(p_arguments->>'amount_minor')::bigint; v_currency:=p_arguments->>'currency';
 if v_currency is distinct from r.currency or amount is null or amount<0 then raise exception 'invalid currency or amount'; end if;
 select version into old_version from obligations where id=row_id and organization_id=p_organization_id and run_id=p_run_id;
 if found and old_version<>coalesce((p_arguments->>'expected_version')::int,-1) then raise exception 'stale obligation version' using errcode='40001'; end if;
 insert into obligations(id,organization_id,run_id,case_id,budget_line_id,title,direction,amount_minor,currency,due_date,evidence_status,source_refs)
 values(row_id,p_organization_id,p_run_id,(p_arguments->>'case_id')::uuid,(p_arguments->>'budget_line_id')::uuid,p_arguments->>'title',p_arguments->>'direction',amount,v_currency,(p_arguments->>'due_date')::date,coalesce(p_arguments->>'evidence_status','reported'),coalesce(p_arguments->'source_refs','[]'))
 on conflict(id) do update set amount_minor=excluded.amount_minor,title=excluded.title,due_date=excluded.due_date,source_refs=excluded.source_refs,version=obligations.version+1,updated_at=now()
 where obligations.organization_id=p_organization_id and obligations.run_id=p_run_id and obligations.settled_minor<=excluded.amount_minor;
 if not found then raise exception 'obligation scope or settled amount conflict'; end if;
 update demo_runs set revision=revision+1,updated_at=now() where id=p_run_id;
 result:=jsonb_build_object('id',row_id,'version',coalesce(old_version,0)+1);
 when 'post_ledger' then
 if jsonb_array_length(p_arguments->'entries')<2 then raise exception 'two postings required'; end if;
 if exists(select 1 from jsonb_array_elements(p_arguments->'entries') e group by e->>'currency' having sum((e->>'amount_minor')::numeric)<>0) then raise exception 'unbalanced journal' using errcode='23514'; end if;
 if exists(select 1 from jsonb_array_elements(p_arguments->'entries') e where e->>'currency'<>r.currency or (e->>'amount_minor')::bigint=0 or coalesce(e->>'account','')='') then raise exception 'invalid posting'; end if;
 insert into ledger_transactions(organization_id,run_id,description,idempotency_key) values(p_organization_id,p_run_id,p_arguments->>'description',key) returning id into row_id;
 insert into ledger_entries(organization_id,run_id,transaction_id,account,currency,amount_minor)
 select p_organization_id,p_run_id,row_id,e->>'account',e->>'currency',(e->>'amount_minor')::bigint from jsonb_array_elements(p_arguments->'entries') e;
 if coalesce((p_arguments->>'establish_opening')::boolean,false) then
 if r.cash_established then raise exception 'opening balance already established'; end if;
 if coalesce(p_arguments->>'evidence_status','') not in ('owner_attested','statement_confirmed','provider_confirmed') then raise exception 'opening evidence required'; end if;
 update demo_runs set cash_established=true,cash_evidence_status=p_arguments->>'evidence_status',reconciled_at=now() where id=p_run_id; end if;
 update demo_runs set revision=revision+1,updated_at=now() where id=p_run_id;
 result:=jsonb_build_object('id',row_id);
 when 'create_approval_request' then
 item:=finance_json_money_strings(p_arguments->'action'); amount:=(item->>'amount_minor')::bigint;
 if jsonb_typeof(item) is distinct from 'object' or not(item ?& array['type','amount_minor','currency','destination','asset','network','obligation_id','obligation_version'])
 or item->>'type' is distinct from 'payment' or amount is null or amount<=0 or item->>'currency' is distinct from r.currency
 or coalesce(item->>'destination','')='' or coalesce(item->>'asset','')='' or coalesce(item->>'network','') not in ('base-sepolia','eip155:84532')
 then raise exception 'exact testnet payment action required' using errcode='22023'; end if;
 if not exists(select 1 from obligations o where o.organization_id=p_organization_id and o.run_id=p_run_id and o.id=(item->>'obligation_id')::uuid and o.version=(item->>'obligation_version')::int and o.direction='payable' and o.status='open' and o.currency=r.currency and o.amount_minor-o.settled_minor>=amount) then raise exception 'current payable evidence required'; end if;
 insert into action_proposals(organization_id,run_id,action,action_hash,run_revision,proposed_by,expires_at,idempotency_key)
 values(p_organization_id,p_run_id,item,encode(digest(item::text,'sha256'),'hex'),r.revision,(p_arguments->>'proposed_by')::uuid,now()+interval '30 minutes',key) returning * into p;
 result:=to_jsonb(p);
 when 'get_approval_status' then
 select to_jsonb(a)||jsonb_build_object('approval_count',(select count(*) from approvals x where x.proposal_id=a.id and x.decision='approve')) into result
 from action_proposals a where a.organization_id=p_organization_id and a.run_id=p_run_id and a.id=(p_arguments->>'proposal_id')::uuid;
 when 'reserve_approved_payment' then
 select * into strict p from action_proposals where organization_id=p_organization_id and run_id=p_run_id and id=(p_arguments->>'proposal_id')::uuid for update;
 select * into pay from payments where proposal_id=p.id;
 if found then result:=to_jsonb(pay); else
 if p.status<>'pending' or p.expires_at<=now() or p.run_revision<>r.revision then raise exception 'stale or expired proposal' using errcode='23514'; end if;
 if (select count(*) from approvals a join memberships m on m.organization_id=a.organization_id and m.user_id=a.user_id and m.active and m.role in ('director','approver')
 where a.proposal_id=p.id and a.action_hash=p.action_hash and a.decision='approve' and a.user_id is distinct from p.proposed_by)<2
 or exists(select 1 from approvals where proposal_id=p.id and decision='reject') then raise exception 'two distinct current human approvals required' using errcode='42501'; end if;
 amount:=(p.action->>'amount_minor')::bigint;
 if not r.cash_established then raise exception 'cash evidence missing'; end if;
 select coalesce(sum(amount_minor),0) into total from ledger_entries where organization_id=p_organization_id and run_id=p_run_id and account='cash' and currency=r.currency;
 select coalesce(sum(amount_minor),0) into reserved from payments where organization_id=p_organization_id and run_id=p_run_id and status in ('reserved','submitting','uncertain','submitted');
 if total-reserved<amount then raise exception 'insufficient unreserved cash' using errcode='23514'; end if;
 if exists(select 1 from payments x join action_proposals a on a.id=x.proposal_id where x.organization_id=p_organization_id and x.run_id=p_run_id and x.status<>'failed' and a.action->>'obligation_id'=p.action->>'obligation_id') then raise exception 'obligation already reserved'; end if;
 insert into payments(organization_id,run_id,proposal_id,amount_minor,currency) values(p_organization_id,p_run_id,p.id,amount,r.currency) returning * into pay;
 update action_proposals set status='reserved' where id=p.id; result:=to_jsonb(pay);
 end if;
 when 'transition_payment' then
 select * into strict pay from payments where organization_id=p_organization_id and run_id=p_run_id and id=(p_arguments->>'payment_id')::uuid for update;
 if not ((pay.status='reserved' and p_arguments->>'status'='submitting') or (pay.status='submitting' and p_arguments->>'status' in ('submitted','uncertain','failed')) or (pay.status='uncertain' and p_arguments->>'status' in ('submitted','failed')))
 then raise exception 'invalid payment state transition' using errcode='23514'; end if;
 if p_arguments->>'status'='submitting' then
 select * into p from action_proposals where id=pay.proposal_id;
 if p.run_revision<>r.revision or p.expires_at<=now() or
 (select count(*) from approvals a join memberships m on m.organization_id=a.organization_id and m.user_id=a.user_id and m.active and m.role in ('director','approver')
 where a.proposal_id=p.id and a.action_hash=p.action_hash and a.decision='approve' and a.user_id is distinct from p.proposed_by)<2
 then raise exception 'submission authority expired or changed' using errcode='23514'; end if;
 end if;
 if p_arguments->>'status'='submitted' and coalesce(p_arguments->>'provider_reference','')='' then raise exception 'provider reference required'; end if;
 update payments set status=p_arguments->>'status',provider_reference=coalesce(p_arguments->>'provider_reference',provider_reference),updated_at=now() where id=pay.id returning * into pay;
 result:=to_jsonb(pay);
 when 'get_payment_status' then
 select to_jsonb(x) into result from payments x where x.organization_id=p_organization_id and x.run_id=p_run_id and x.id=(p_arguments->>'payment_id')::uuid;
 when 'get_trace' then
 select to_jsonb(t) into result from trace_events t where t.organization_id=p_organization_id and t.run_id=p_run_id and t.id=(p_arguments->>'trace_id')::uuid;
 when 'confirm_payment' then
 select * into strict pay from payments where organization_id=p_organization_id and run_id=p_run_id and id=(p_arguments->>'payment_id')::uuid for update;
 select * into p from action_proposals where id=pay.proposal_id;
 item:=p_arguments->'receipt';
 if jsonb_typeof(item) is distinct from 'object' or not(item ?& array['provider_reference','destination','asset','network','amount_minor','status'])
 or pay.status<>'submitted' or item->>'provider_reference' is distinct from pay.provider_reference or item->>'destination' is distinct from p.action->>'destination'
 or item->>'asset' is distinct from p.action->>'asset' or item->>'network' is distinct from p.action->>'network' or (item->>'amount_minor')::bigint is distinct from pay.amount_minor or item->>'status' is distinct from 'confirmed'
 or (p.action ? 'amount_base_units' and item->>'amount_base_units' is distinct from p.action->>'amount_base_units')
 then raise exception 'verified receipt mismatch' using errcode='23514'; end if;
 insert into ledger_transactions(organization_id,run_id,description,idempotency_key) values(p_organization_id,p_run_id,'Confirmed testnet payout','payment:'||pay.id) returning id into row_id;
 insert into ledger_entries(organization_id,run_id,transaction_id,account,currency,amount_minor) values
 (p_organization_id,p_run_id,row_id,'cash',pay.currency,-pay.amount_minor),(p_organization_id,p_run_id,row_id,'expense',pay.currency,pay.amount_minor);
 update obligations set settled_minor=settled_minor+pay.amount_minor,status=case when settled_minor+pay.amount_minor=amount_minor then 'settled' else status end,version=version+1,updated_at=now() where id=(p.action->>'obligation_id')::uuid and organization_id=p_organization_id and run_id=p_run_id;
 update payments set status='confirmed',receipt=item,updated_at=now() where id=pay.id;
 update action_proposals set status='executed' where id=p.id;
 update demo_runs set revision=revision+1,updated_at=now() where id=p_run_id;
 result:=jsonb_build_object('payment_id',pay.id,'status','confirmed','ledger_transaction_id',row_id);
 when 'record_trace' then
 insert into trace_events(organization_id,run_id,case_id,event_type,payload,idempotency_key) values(p_organization_id,p_run_id,(p_arguments->>'case_id')::uuid,p_arguments->>'event_type',p_arguments->'payload',key) returning id into row_id;
 result:=jsonb_build_object('id',row_id);
 when 'get_active_skill' then
 select to_jsonb(s) into result from skill_versions s where s.organization_id=p_organization_id and s.run_id=p_run_id and s.skill_name=p_arguments->>'skill_name' and s.is_active;
 when 'save_skill_version' then
 insert into skill_versions(organization_id,run_id,skill_name,version,artifact_path,content_sha256,parent_version_id,status,metadata)
 values(p_organization_id,p_run_id,p_arguments->>'skill_name',p_arguments->>'version',p_arguments->>'artifact_path',p_arguments->>'content_sha256',(p_arguments->>'parent_version_id')::uuid,coalesce(p_arguments->>'status','candidate'),coalesce(p_arguments->'metadata','{}')) returning id into row_id;
 select to_jsonb(s) into result from skill_versions s where id=row_id;
 when 'initialize_skill_baseline' then
 if p_arguments->>'skill_name'<>'organizer-expenses' then raise exception 'baseline skill outside permitted scope' using errcode='42501'; end if;
 if exists(select 1 from skill_versions where organization_id=p_organization_id and run_id=p_run_id and skill_name=p_arguments->>'skill_name' and is_active)
 then raise exception 'active baseline already initialized' using errcode='23514'; end if;
 update skill_versions set is_active=true,status='baseline' where organization_id=p_organization_id and run_id=p_run_id and id=(p_arguments->>'version_id')::uuid
 and skill_name=p_arguments->>'skill_name' and parent_version_id is null and status='baseline';
 if not found then raise exception 'bundled baseline required'; end if;
 result:=jsonb_build_object('id',p_arguments->>'version_id','status','baseline');
 when 'record_eval_run' then
 row_id:=coalesce((p_arguments->>'id')::uuid,gen_random_uuid());
 insert into eval_runs(id,organization_id,run_id,skill_name,baseline_version_id,candidate_version_id,status,metrics,artifact_path)
 values(row_id,p_organization_id,p_run_id,p_arguments->>'skill_name',(p_arguments->>'baseline_version_id')::uuid,(p_arguments->>'candidate_version_id')::uuid,p_arguments->>'status',coalesce(p_arguments->'metrics','{}'),p_arguments->>'artifact_path')
 on conflict(id) do update set status=excluded.status,metrics=excluded.metrics,artifact_path=excluded.artifact_path,updated_at=now() where eval_runs.organization_id=p_organization_id and eval_runs.run_id=p_run_id;
 if not found then raise exception 'evaluation scope denied'; end if; select to_jsonb(e) into result from eval_runs e where id=row_id;
 when 'record_eval_result' then
 insert into eval_results(organization_id,run_id,eval_run_id,case_key,variant,passed,hard_invariants_passed,metrics,details)
 values(p_organization_id,p_run_id,(p_arguments->>'eval_run_id')::uuid,p_arguments->>'case_key',p_arguments->>'variant',(p_arguments->>'passed')::boolean,(p_arguments->>'hard_invariants_passed')::boolean,coalesce(p_arguments->'metrics','{}'),coalesce(p_arguments->'details','{}')) returning id into row_id;
 result:=jsonb_build_object('id',row_id);
 when 'record_promotion' then
 insert into promotions(organization_id,run_id,skill_name,version_id,previous_version_id,eval_run_id,state,reason)
 values(p_organization_id,p_run_id,p_arguments->>'skill_name',(p_arguments->>'version_id')::uuid,(p_arguments->>'previous_version_id')::uuid,(p_arguments->>'eval_run_id')::uuid,p_arguments->>'state',p_arguments->>'reason') returning id into row_id;
 result:=jsonb_build_object('id',row_id);
 when 'set_active_skill_version' then
 if p_arguments->>'skill_name'<>'organizer-expenses' then raise exception 'skill outside permitted improvement scope' using errcode='42501'; end if;
 select id into active_id from skill_versions where organization_id=p_organization_id and run_id=p_run_id and skill_name=p_arguments->>'skill_name' and is_active;
 if active_id is distinct from (p_arguments->>'expected_active_version_id')::uuid then raise exception 'active skill changed' using errcode='40001'; end if;
 select * into strict eval from eval_runs where organization_id=p_organization_id and run_id=p_run_id and id=(p_arguments->>'eval_run_id')::uuid;
 if eval.status<>'passed' or eval.candidate_version_id<>(p_arguments->>'version_id')::uuid or eval.baseline_version_id is distinct from active_id
 or not exists(select 1 from eval_results where eval_run_id=eval.id and variant='candidate') or exists(select 1 from eval_results where eval_run_id=eval.id and variant='candidate' and (not hard_invariants_passed or (details->>'group'='regression' and not passed)))
 or coalesce((eval.metrics->>'gate_passed')::boolean,false) is not true then raise exception 'fixed evaluation gate not met' using errcode='23514'; end if;
 update skill_versions set is_active=false where id=active_id;
 update skill_versions set is_active=true,status='promoted' where organization_id=p_organization_id and run_id=p_run_id and id=(p_arguments->>'version_id')::uuid and skill_name=p_arguments->>'skill_name';
 if not found then raise exception 'skill missing'; end if;
 insert into promotions(organization_id,run_id,skill_name,version_id,previous_version_id,eval_run_id,state,reason)
 values(p_organization_id,p_run_id,p_arguments->>'skill_name',(p_arguments->>'version_id')::uuid,active_id,eval.id,'promoted',coalesce(p_arguments->>'reason','Fixed evaluation gate passed')) returning id into row_id;
 result:=jsonb_build_object('id',p_arguments->>'version_id','previous_version_id',active_id,'promotion_id',row_id);
 when 'rollback_skill_version' then
 if p_arguments->>'skill_name'<>'organizer-expenses' then raise exception 'skill outside permitted scope' using errcode='42501'; end if;
 select id into active_id from skill_versions where organization_id=p_organization_id and run_id=p_run_id and skill_name=p_arguments->>'skill_name' and is_active;
 if active_id is distinct from (p_arguments->>'expected_active_version_id')::uuid then raise exception 'active skill changed' using errcode='40001'; end if;
 if not exists(select 1 from promotions where organization_id=p_organization_id and run_id=p_run_id and id=(p_arguments->>'promotion_id')::uuid and version_id=active_id and previous_version_id=(p_arguments->>'version_id')::uuid and state='promoted')
 or coalesce(p_arguments->>'reason','')='' then raise exception 'recorded promotion and rollback reason required'; end if;
 update skill_versions set is_active=false,status='rolled_back' where id=active_id;
 update skill_versions set is_active=true where organization_id=p_organization_id and run_id=p_run_id and id=(p_arguments->>'version_id')::uuid and skill_name=p_arguments->>'skill_name';
 if not found then raise exception 'rollback version missing'; end if;
 insert into promotions(organization_id,run_id,skill_name,version_id,previous_version_id,state,reason) values(p_organization_id,p_run_id,p_arguments->>'skill_name',(p_arguments->>'version_id')::uuid,active_id,'rolled_back',p_arguments->>'reason');
 result:=jsonb_build_object('id',p_arguments->>'version_id','previous_version_id',active_id,'state','rolled_back');
 when 'record_report' then
 insert into report_snapshots(organization_id,run_id,cutoff,data,artifact_path) values(p_organization_id,p_run_id,(p_arguments->>'cutoff')::timestamptz,finance_json_money_strings(p_arguments->'data'),p_arguments->>'artifact_path') returning id into row_id;
 result:=jsonb_build_object('id',row_id);
 when 'set_connection_status' then
 insert into connections(organization_id,run_id,provider,status,data) values(p_organization_id,p_run_id,p_arguments->>'provider',p_arguments->>'status',coalesce(p_arguments->'data','{}'))
 on conflict(organization_id,run_id,provider) do update set status=excluded.status,data=connections.data||excluded.data,updated_at=now(); result:=jsonb_build_object('status',p_arguments->>'status');
 else raise exception 'unsupported finance operation: %',p_operation using errcode='22023';
 end case;
 if key is not null then
 insert into finance_operations(organization_id,run_id,idempotency_key,operation,request_hash,result) values(p_organization_id,p_run_id,key,p_operation,request_hash,coalesce(result,'null'));
 perform finance_audit(p_organization_id,p_run_id,p_operation,jsonb_build_object('record_id',coalesce(result->>'id',result->>'payment_id')));
 end if;
 return result;
end $$;

-- Scope every exposed table, including worker credentials' explicit RPC scope.
alter table organizations enable row level security;
create policy organization_read on organizations for select to authenticated using(finance_is_member(id));
alter table memberships enable row level security;
create policy own_membership_read on memberships for select to authenticated using(user_id=auth.uid());
alter table demo_runs enable row level security;
create policy run_read on demo_runs for select to authenticated using(finance_can_access(organization_id,id));
do $$ declare tab text; begin
 foreach tab in array array['connections','source_items','documents','cases','case_dependencies','funds','budget_lines','obligations','action_proposals','approvals','payments','ledger_transactions','ledger_entries','jobs','audit_events','trace_events','skill_versions','eval_runs','eval_results','promotions','report_snapshots','finance_operations'] loop
 execute format('alter table public.%I enable row level security',tab);
 execute format('create policy scoped_read on public.%I for select to authenticated using(public.finance_can_access(organization_id,run_id))',tab);
 execute format('revoke all on public.%I from anon,authenticated',tab);
 -- Raw traces/operations are not browser readable. Snapshot exposes reviewed display data only.
 if tab not in ('trace_events','finance_operations','case_dependencies') then execute format('grant select on public.%I to authenticated',tab); end if;
 end loop;
end $$;
alter table worker_heartbeats enable row level security;
revoke all on worker_heartbeats from anon,authenticated;
revoke all on organizations,memberships,demo_runs from anon,authenticated;
grant select on organizations,memberships,demo_runs to authenticated;

-- Storage objects are private and run-prefixed. Only worker uploads.
insert into storage.buckets(id,name,public,file_size_limit) values('finance-artifacts','finance-artifacts',false,10485760) on conflict(id) do nothing;
create policy finance_artifact_read on storage.objects for select to authenticated using(
 bucket_id='finance-artifacts' and exists(select 1 from demo_runs r where
 name like r.organization_id::text||'/'||r.id::text||'/%' and finance_can_access(r.organization_id,r.id))
);
create policy finance_private_broadcast on realtime.messages for select to authenticated using(
 exists(select 1 from demo_runs r where realtime.topic()='finance:'||r.organization_id||':'||r.id and finance_can_access(r.organization_id,r.id))
);

-- Functions default to PUBLIC execute in PostgreSQL: explicitly remove that.
do $$ declare fn record; begin
 for fn in select p.oid::regprocedure as signature from pg_proc p join pg_namespace n on n.oid=p.pronamespace
 where n.nspname='public' and (p.proname like 'finance_%' or p.proname in ('get_finance_snapshot','enqueue_finance_command','approve_finance_proposal','create_finance_demo','lease_finance_job','renew_finance_job','finish_finance_job','fail_finance_job')) loop
 execute format('revoke all on function %s from public,anon,authenticated',fn.signature);
 execute format('grant execute on function %s to service_role',fn.signature);
 end loop;
end $$;
grant execute on function finance_can_access(uuid,uuid),finance_is_member(uuid) to authenticated;
grant execute on function get_finance_snapshot(uuid,uuid),enqueue_finance_command(uuid,uuid,text,jsonb,text),approve_finance_proposal(uuid,text,text),create_finance_demo(text,uuid) to authenticated;
grant all on all tables in schema public to service_role;
grant usage,select on all sequences in schema public to service_role;
commit;
