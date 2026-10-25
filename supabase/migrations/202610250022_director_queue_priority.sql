-- Interactive finance work gets the next available lease ahead of background
-- reviews/learning. This never interrupts a running job or changes its authority.
begin;

create or replace function public.lease_finance_job(p_worker_id text,p_lease_seconds integer default 120) returns jsonb
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
 -- Recover interrupted work first; payment recovery retains its durable provider
 -- state. Ready work waiting 15 minutes enters FIFO ahead of newer messages, so
 -- a stream of user prompts cannot starve intake or learning indefinitely.
 order by case
   when x.status='running' then 0
   when greatest(x.created_at,x.available_at)<=now()-interval '15 minutes' then 1
   when x.command_type='director_message' then 2
   when x.command_type='review_case' then 4
   when x.command_type='evaluate_improvement' then 5
   else 3
 end, x.created_at, x.id
 for update of x skip locked limit 1;
 if not found then return null; end if;
 update jobs set status='running',worker_id=p_worker_id,lease_token=gen_random_uuid(),lease_expires_at=now()+make_interval(secs=>p_lease_seconds),
 attempts=attempts+1,updated_at=now() where id=j.id returning * into j;
 perform finance_audit(j.organization_id,j.run_id,'job_started',jsonb_build_object('job_id',j.id,'attempts',j.attempts,'queue_policy','interactive-first-v1'));
 return to_jsonb(j);
end $$;

revoke all on function public.lease_finance_job(text,integer) from public,anon,authenticated;
grant execute on function public.lease_finance_job(text,integer) to service_role;

commit;
