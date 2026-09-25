-- Community contribution platform --------------------------------------------
-- Design note: a contributed integration is untrusted until it has been
-- executed. `status` gates every read path, and `verification_report` records
-- what the runner actually did, so the UI can never present a submitted
-- manifest as working.
create table if not exists community_integrations (
    id              uuid primary key default gen_random_uuid(),
    developer_id    uuid references auth.users (id) on delete cascade,
    name            text not null,
    canonical_key   text generated always as (lower(regexp_replace(name, '[^a-zA-Z0-9]+', '', 'g'))) stored,
    source_url      text not null,
    description     text not null default '',
    manifest        jsonb not null,
    status          text not null default 'pending'
                    check (status in ('pending', 'approved', 'rejected', 'needs_changes')),
    rejection_reason text,
    verification_report jsonb,
    tested_at       timestamptz,
    install_count   integer not null default 0,
    revenue_share_pct numeric(5,2) not null default 20.00
                    check (revenue_share_pct >= 0 and revenue_share_pct <= 100),
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);

create unique index if not exists community_integrations_canonical_uniq
    on community_integrations (canonical_key);
create index if not exists community_integrations_status_idx
    on community_integrations (status);
-- A developer may only have one pending submission per canonical name.
create unique index if not exists community_integrations_pending_uniq
    on community_integrations (developer_id, canonical_key)
    where status in ('pending', 'needs_changes');

create table if not exists community_earnings (
    id              uuid primary key default gen_random_uuid(),
    developer_id    uuid not null references auth.users (id) on delete cascade,
    integration_id  uuid not null references community_integrations (id) on delete cascade,
    amount_usd      numeric(12,2) not null check (amount_usd >= 0),
    period_start    date not null,
    period_end      date not null,
    paid_at         timestamptz,
    created_at      timestamptz not null default now(),
    check (period_end >= period_start)
);

create index if not exists community_earnings_developer_idx
    on community_earnings (developer_id, period_start desc);
create unique index if not exists community_earnings_period_uniq
    on community_earnings (integration_id, period_start);

-- ---------------------------------------------------------------------------
-- Earnings may only exist for an APPROVED integration.
--
-- This was previously expressed as
--     alter table community_integrations
--         add constraint community_earnings_require_approved
--         foreign key (id) references community_integrations (id);
-- which is a no-op: `id` is already the primary key, so the constraint can
-- never be violated and enforces nothing about `status`. It is replaced by a
-- trigger that actually reads `status`.
-- ---------------------------------------------------------------------------
create or replace function check_integration_approved()
returns trigger as $$
begin
    if not exists (
        select 1 from community_integrations
        where id = NEW.integration_id
        and status = 'approved'
    ) then
        raise exception 'Cannot record earnings for non-approved integration';
    end if;
    return NEW;
end;
$$ language plpgsql;

create trigger community_earnings_approved_check
    before insert or update on community_earnings
    for each row execute function check_integration_approved();

-- The trigger above guards writes to earnings, but it can be side-stepped by
-- approving an integration, recording earnings, then flipping the status back
-- to 'rejected'. This guard closes that path.
create or replace function check_status_change_with_earnings()
returns trigger as $$
begin
    if NEW.status <> 'approved' and OLD.status = 'approved'
       and exists (select 1 from community_earnings where integration_id = OLD.id)
    then
        raise exception 'Cannot un-approve an integration that already has earnings';
    end if;
    return NEW;
end;
$$ language plpgsql;

create trigger community_integrations_status_guard
    before update of status on community_integrations
    for each row execute function check_status_change_with_earnings();

-- ---------------------------------------------------------------------------
-- Row level security
--
-- Submissions are untrusted: only approved rows are publicly readable, a
-- developer may write their own rows, and nothing but the service role may
-- moderate or record earnings. Without RLS the anon key could read every
-- pending manifest and self-approve.
-- ---------------------------------------------------------------------------
alter table community_integrations enable row level security;
alter table community_earnings enable row level security;

drop policy if exists community_integrations_public_read on community_integrations;
create policy community_integrations_public_read on community_integrations
    for select using (status = 'approved');

drop policy if exists community_integrations_own_write on community_integrations;
create policy community_integrations_own_write on community_integrations
    for insert with check (developer_id = auth.uid());

drop policy if exists community_integrations_own_update on community_integrations;
-- deliberately no status predicate here: moderation happens with the service
-- role, which bypasses RLS. A policy that let a user update their own row
-- would otherwise let them set status='approved'.
create policy community_integrations_own_update on community_integrations
    for update using (developer_id = auth.uid())
    with check (developer_id = auth.uid() and status <> 'approved');

drop policy if exists community_earnings_own_read on community_earnings;
create policy community_earnings_own_read on community_earnings
    for select using (developer_id = auth.uid());

-- No insert/update policy on community_earnings: only the service role writes.

