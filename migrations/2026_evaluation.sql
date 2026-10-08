-- migrations/2026_evaluation.sql
-- Fitur #4: Evaluation & Testing built-in (8 Okt 2026)
-- ======================================================================
-- Menyimpan hasil tiap run evaluasi (dataset + metrik + hasil per-kasus)
-- sehingga bisa dibandingkan antar waktu (regresi vs baseline).
-- ======================================================================

create table if not exists eval_runs (
    run_id         text primary key,
    owner          text not null default '',
    name           text not null default 'eval',
    dataset_name   text not null default '',
    accuracy       double precision,
    passed         integer,
    total          integer,
    latency_mean_ms double precision,
    cost_total_usd double precision,
    summary        jsonb not null default '{}'::jsonb,
    results        jsonb not null default '[]'::jsonb,
    created_at     timestamptz not null default now()
);

create index if not exists eval_runs_owner_idx on eval_runs (owner, created_at desc);

alter table eval_runs enable row level security;

drop policy if exists eval_runs_owner on eval_runs;
create policy eval_runs_owner on eval_runs
    for all using (owner = auth.jwt() ->> 'email')
    with check (owner = auth.jwt() ->> 'email');
