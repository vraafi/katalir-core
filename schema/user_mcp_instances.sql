-- Run after review in Supabase SQL editor.
create table if not exists public.user_mcp_instances (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  mcp_id text not null,
  config jsonb not null default '{}'::jsonb,
  status text not null default 'active' check (status in ('active','inactive','error')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(user_id, mcp_id)
);
alter table public.user_mcp_instances enable row level security;
create policy "users manage own mcp instances" on public.user_mcp_instances
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
