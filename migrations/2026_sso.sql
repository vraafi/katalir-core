-- 2026_sso.sql — Fitur #7 SSO/SAML/OIDC/LDAP (Okt 2026)
-- Organisasi (tenant) SSO + user hasil JIT provisioning.
-- Idempotent.

CREATE TABLE IF NOT EXISTS sso_orgs (
    id            bigserial PRIMARY KEY,
    org           text        NOT NULL UNIQUE,
    role_mapping  jsonb       NOT NULL DEFAULT '{}'::jsonb,
    domains       jsonb       NOT NULL DEFAULT '[]'::jsonb,
    default_role  text        NOT NULL DEFAULT 'viewer',
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sso_users (
    id          bigserial PRIMARY KEY,
    email       text        NOT NULL UNIQUE,
    name        text,
    org         text,
    provider    text,
    groups      jsonb       NOT NULL DEFAULT '[]'::jsonb,
    active      boolean     NOT NULL DEFAULT true,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sso_users_org ON sso_users (org);
CREATE INDEX IF NOT EXISTS idx_sso_users_active ON sso_users (active);

ALTER TABLE sso_orgs  ENABLE ROW LEVEL SECURITY;
ALTER TABLE sso_users ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS sso_users_self ON sso_users;
CREATE POLICY sso_users_self ON sso_users
    FOR SELECT
    USING (email = (auth.jwt() ->> 'email'));

SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public' AND table_name IN ('sso_orgs', 'sso_users')
ORDER BY 1;
