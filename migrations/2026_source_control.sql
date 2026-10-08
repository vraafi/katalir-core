-- 2026_source_control.sql — Fitur #5 Source Control / Git (Okt 2026)
-- Tabel koneksi Git per-user. Token disimpan TERENKRIPSI (Fernet via
-- vault_security), tidak pernah dikembalikan mentah ke klien.
-- Idempotent.

CREATE TABLE IF NOT EXISTS git_connections (
    id          bigserial PRIMARY KEY,
    owner       text        NOT NULL,
    provider    text        NOT NULL,
    repo        text        NOT NULL,
    token_enc   text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (owner, provider)
);

CREATE INDEX IF NOT EXISTS idx_git_connections_owner
    ON git_connections (owner);

ALTER TABLE git_connections ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS git_connections_owner ON git_connections;
CREATE POLICY git_connections_owner ON git_connections
    FOR ALL
    USING (owner = (auth.jwt() ->> 'email'))
    WITH CHECK (owner = (auth.jwt() ->> 'email'));

SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public' AND table_name = 'git_connections';
