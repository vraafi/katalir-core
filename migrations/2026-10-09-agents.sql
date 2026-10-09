-- ============================================================================
-- 2026-10-09-agents.sql
-- TASK 5 / Fitur #1 — n8n Agents sebagai FIRST-CLASS ENTITY
-- ============================================================================
-- Di n8n, "AI Agent" adalah NODE di dalam workflow. Fitur ini mengangkatnya
-- menjadi entitas kelas satu: punya siklus hidup, kanal, dan bisa diekspos
-- sebagai MCP server.
--
-- Dua tabel:
--   * agents          — definisi agent (model, instruksi, tools, status)
--   * agent_channels  — kanal terhubungnya (web/api/webhook/slack/schedule/mcp)
--
-- Idempoten: aman dijalankan berulang (IF NOT EXISTS / DROP POLICY IF EXISTS).
--
-- Cara menjalankan: Supabase Dashboard -> SQL Editor -> tempel -> Run.
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid()

-- ---------------------------------------------------------------------------
-- agents
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.agents (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         uuid NOT NULL,
    name            text NOT NULL,
    description     text NOT NULL DEFAULT '',
    instruction     text NOT NULL DEFAULT '',
    model           text NOT NULL DEFAULT '',
    tools           text[] NOT NULL DEFAULT '{}',
    memory_enabled  boolean NOT NULL DEFAULT true,
    workflow_id     text,
    status          text NOT NULL DEFAULT 'draft',
    version         integer NOT NULL DEFAULT 1,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT agents_name_not_blank CHECK (length(btrim(name)) > 0),
    CONSTRAINT agents_status_valid
        CHECK (status IN ('draft', 'active', 'paused', 'archived'))
);

-- Daftar agent milik user (terbaru dulu) — query utama sidebar /agents.
CREATE INDEX IF NOT EXISTS idx_agents_user_created
    ON public.agents (user_id, created_at DESC);

-- Filter status (draft/active/paused/archived).
CREATE INDEX IF NOT EXISTS idx_agents_status
    ON public.agents (status);

-- Pencarian tools (GIN, karena text[]).
CREATE INDEX IF NOT EXISTS idx_agents_tools
    ON public.agents USING gin (tools);

-- ---------------------------------------------------------------------------
-- agent_channels
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.agent_channels (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id    uuid NOT NULL REFERENCES public.agents(id) ON DELETE CASCADE,
    user_id     uuid NOT NULL,
    type        text NOT NULL,
    config      jsonb NOT NULL DEFAULT '{}'::jsonb,
    enabled     boolean NOT NULL DEFAULT true,
    created_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT agent_channels_type_valid
        CHECK (type IN ('web', 'api', 'webhook', 'slack', 'schedule', 'mcp', 'embed'))
);

CREATE INDEX IF NOT EXISTS idx_channels_agent
    ON public.agent_channels (agent_id);

CREATE INDEX IF NOT EXISTS idx_channels_user
    ON public.agent_channels (user_id, created_at DESC);

-- ---------------------------------------------------------------------------
-- RLS: user hanya boleh melihat/mengubah agent miliknya.
-- ---------------------------------------------------------------------------
ALTER TABLE public.agents ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS agents_select_own ON public.agents;
CREATE POLICY agents_select_own ON public.agents
    FOR SELECT USING (auth.uid() = user_id);

DROP POLICY IF EXISTS agents_insert_own ON public.agents;
CREATE POLICY agents_insert_own ON public.agents
    FOR INSERT WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS agents_update_own ON public.agents;
CREATE POLICY agents_update_own ON public.agents
    FOR UPDATE USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS agents_delete_own ON public.agents;
CREATE POLICY agents_delete_own ON public.agents
    FOR DELETE USING (auth.uid() = user_id);

ALTER TABLE public.agent_channels ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS channels_select_own ON public.agent_channels;
CREATE POLICY channels_select_own ON public.agent_channels
    FOR SELECT USING (auth.uid() = user_id);

DROP POLICY IF EXISTS channels_insert_own ON public.agent_channels;
CREATE POLICY channels_insert_own ON public.agent_channels
    FOR INSERT WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS channels_update_own ON public.agent_channels;
CREATE POLICY channels_update_own ON public.agent_channels
    FOR UPDATE USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS channels_delete_own ON public.agent_channels;
CREATE POLICY channels_delete_own ON public.agent_channels
    FOR DELETE USING (auth.uid() = user_id);

-- ---------------------------------------------------------------------------
-- updated_at otomatis
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.touch_agents()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_touch_agents ON public.agents;
CREATE TRIGGER trg_touch_agents
    BEFORE UPDATE ON public.agents
    FOR EACH ROW EXECUTE FUNCTION public.touch_agents();

-- ============================================================================
-- SELESAI. Verifikasi cepat:
--   SELECT column_name, data_type FROM information_schema.columns
--    WHERE table_name = 'agents' ORDER BY ordinal_position;
--   SELECT column_name, data_type FROM information_schema.columns
--    WHERE table_name = 'agent_channels' ORDER BY ordinal_position;
-- ============================================================================
