"""Render exactly the versioned migration with receipts for SQL-editor setup."""

from __future__ import annotations

import hashlib

from app.resources import resource_path


def migration_sql() -> str:
    files = sorted(resource_path("supabase/migrations").glob("*.sql"))
    if not files:
        raise RuntimeError("No bundled migrations are installed")
    result = [
        """-- Generated offline. Apply only to the event-owned dedicated Supabase project.
-- Same hashes/receipts as finance migrate. No connection or credential guessing.
begin;
select pg_advisory_xact_lock(716204812);
create table if not exists public.finance_schema_migrations (
  name text primary key, sha256 text not null, applied_at timestamptz not null default now());
alter table public.finance_schema_migrations enable row level security;
revoke all on public.finance_schema_migrations from public,anon,authenticated;
"""
    ]
    for file in files:
        original = file.read_text()
        digest = hashlib.sha256(original.encode()).hexdigest()
        body = "\n".join(
            line
            for line in original.splitlines()
            if line.strip().lower() not in {"begin;", "commit;"}
        )
        marker = "$finance_body_" + digest[:12] + "$"
        outer = "$finance_receipt_" + digest[:12] + "$"
        if marker in body or outer in body:
            raise RuntimeError("Migration delimiter conflicts with content")
        name = file.name.replace("'", "''")
        result.append(f"""do {outer}
begin
  if exists(select 1 from public.finance_schema_migrations where name='{name}' and sha256<>'{digest}') then
    raise exception 'Applied migration changed; create a new migration';
  end if;
  if not exists(select 1 from public.finance_schema_migrations where name='{name}') then
    execute {marker}
{body}
{marker};
    insert into public.finance_schema_migrations(name,sha256) values('{name}','{digest}');
  end if;
end {outer};
""")
    result.append("commit;\n")
    return "\n".join(result)
