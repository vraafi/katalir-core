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

-- Earnings may only be recorded against an approved integration.
alter table community_integrations
    add constraint community_earnings_require_approved
    foreign key (id) references community_integrations (id);
