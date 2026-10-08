-- 2026_plugins.sql — Fitur #11 Plugin / Extension System (Okt 2026)
-- Registry plugin per-user supaya pemasangan BERTAHAN lintas restart/deploy.
-- Yang disimpan hanya MANIFEST (deklaratif: nama, versi, capability, entry,
-- dependensi) — bukan kode. Handler tetap kode server; `entry` hanya penunjuk.
-- Idempotent.

CREATE TABLE IF NOT EXISTS plugin_registry (
    id           bigserial   PRIMARY KEY,
    owner        text        NOT NULL,
    name         text        NOT NULL,
    version      text        NOT NULL,
    manifest     jsonb       NOT NULL DEFAULT '{}'::jsonb,
    enabled      boolean     NOT NULL DEFAULT true,
    installed_at timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (owner, name)
);

CREATE INDEX IF NOT EXISTS idx_plugin_registry_owner
    ON plugin_registry (owner);

-- Capability tersimpan sebagai jsonb -> dapat dicari/di-audit tanpa parsing
-- di aplikasi (mis. "plugin mana saja yang meminta capability http?").
CREATE INDEX IF NOT EXISTS idx_plugin_registry_caps
    ON plugin_registry USING gin ((manifest -> 'capabilities'));

ALTER TABLE plugin_registry ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS plugin_registry_owner ON plugin_registry;
CREATE POLICY plugin_registry_owner ON plugin_registry
    FOR ALL
    USING (owner = (auth.jwt() ->> 'email'))
    WITH CHECK (owner = (auth.jwt() ->> 'email'));

-- service_role (dipakai backend) melewati RLS; kebijakan eksplisit di bawah
-- membuat niat itu terbaca, bukan tersirat.
DROP POLICY IF EXISTS plugin_registry_service ON plugin_registry;
CREATE POLICY plugin_registry_service ON plugin_registry
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public' AND table_name = 'plugin_registry';
