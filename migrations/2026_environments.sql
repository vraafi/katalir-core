-- 2026_environments.sql — Fitur #4 Multi-Environment (Okt 2026)
-- Tabel versi workflow per-environment + audit promosi.
-- Idempotent.

CREATE TABLE IF NOT EXISTS workflow_environments (
    id          bigserial PRIMARY KEY,
    owner       text        NOT NULL,
    env         text        NOT NULL,
    workflow_id text        NOT NULL,
    version     integer     NOT NULL,
    flow_data   jsonb       NOT NULL,
    config      jsonb       NOT NULL DEFAULT '{}'::jsonb,
    note        text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (owner, env, workflow_id, version)
);

CREATE INDEX IF NOT EXISTS idx_workflow_environments_lookup
    ON workflow_environments (owner, env, workflow_id, version DESC);

CREATE TABLE IF NOT EXISTS environment_audit (
    id          bigserial PRIMARY KEY,
    owner       text,
    action      text,
    env         text,
    workflow_id text,
    version     integer,
    role        text,
    approver    text,
    request_id  text,
    "from"      text,
    at          double precision NOT NULL DEFAULT 0,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_environment_audit_owner
    ON environment_audit (owner, created_at DESC);

-- RLS: owner hanya melihat barisnya sendiri (service_role bypass).
ALTER TABLE workflow_environments ENABLE ROW LEVEL SECURITY;
ALTER TABLE environment_audit     ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS workflow_environments_owner ON workflow_environments;
CREATE POLICY workflow_environments_owner ON workflow_environments
    FOR ALL
    USING (owner = (auth.jwt() ->> 'email'))
    WITH CHECK (owner = (auth.jwt() ->> 'email'));

DROP POLICY IF EXISTS environment_audit_owner ON environment_audit;
CREATE POLICY environment_audit_owner ON environment_audit
    FOR ALL
    USING (owner = (auth.jwt() ->> 'email'))
    WITH CHECK (owner = (auth.jwt() ->> 'email'));

-- Verifikasi
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN ('workflow_environments', 'environment_audit')
ORDER BY 1;
