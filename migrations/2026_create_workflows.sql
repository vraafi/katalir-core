-- =============================================================================
--  MIGRACIÓN SUPABASE — tabla `workflows` (Visual AI Agent Workflow Builder)
--  Ejecutar en Supabase Dashboard: SQL Editor -> Run
-- =============================================================================
create table if not exists public.workflows (
  id uuid primary key default gen_random_uuid(),
  name text not null default 'Draft Workflow',
  description text not null default '',
  flow_data jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

alter table public.workflows enable row level security;
create policy "workflows_public_all" on public.workflows
  for all using (true);