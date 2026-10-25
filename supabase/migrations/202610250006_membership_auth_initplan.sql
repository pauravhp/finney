-- Cache the request's authenticated identity once instead of calling auth.uid()
-- for every membership row. Access semantics and RLS remain unchanged.
begin;
alter policy own_membership_read on public.memberships
using (user_id = (select auth.uid()));
commit;
