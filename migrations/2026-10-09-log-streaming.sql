-- 2026-10-09-log-streaming.sql
-- Fitur #4: Log streaming ke SIEM (webhook / syslog / sentry)
-- Model mengikuti n8n `N8N_LOG_STREAMING_DESTINATIONS` (v2.19.0+).
--
-- Jalankan di Supabase SQL Editor. Idempoten.

-- ===========================================================================
-- 1. TUJUAN STREAMING (per pemilik)
-- ===========================================================================
-- `config` menyimpan bentuk yang sama dengan satu entri
-- `N8N_LOG_STREAMING_DESTINATIONS`:
--   {"destinations":[{ "type":"webhook|syslog|sentry", "label":"...",
--                      "enabled":true, "subscribedEvents":["n8n.audit"],
--                      "anonymizeAuditMessages":false,
--                      "circuitBreaker":{"maxFailures":5,
--                                        "failureWindow":60000},
--                      ... field spesifik tipe ... }]}
CREATE TABLE IF NOT EXISTS public.log_stream_destinations (
    owner           uuid PRIMARY KEY,
    config          jsonb NOT NULL DEFAULT '{"destinations":[]}'::jsonb,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION public.touch_log_stream_destinations()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS log_stream_destinations_touch
    ON public.log_stream_destinations;
CREATE TRIGGER log_stream_destinations_touch
    BEFORE UPDATE ON public.log_stream_destinations
    FOR EACH ROW EXECUTE FUNCTION public.touch_log_stream_destinations();

-- RLS: tiap pemilik hanya melihat/mengubah konfigurasinya sendiri. Tujuan
-- memuat kredensial (Authorization header, DSN Sentry) sehingga TIDAK boleh
-- terbaca lintas tenant.
ALTER TABLE public.log_stream_destinations ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "log_stream_owner_all" ON public.log_stream_destinations;
CREATE POLICY "log_stream_owner_all" ON public.log_stream_destinations
    FOR ALL TO authenticated
    USING (owner = auth.uid())
    WITH CHECK (owner = auth.uid());


-- ===========================================================================
-- 2. JEJAK PENGIRIMAN (opsional, untuk audit "apa yang sudah dikirim")
-- ===========================================================================
-- Menyimpan ringkasan pengiriman (BUKAN payload penuh) supaya tabel tetap
-- kecil dan tidak menjadi salinan kedua execution_logs. Berguna untuk
-- membuktikan "event sudah keluar" pada laporan kepatuhan.
CREATE TABLE IF NOT EXISTS public.log_stream_deliveries (
    id              bigserial PRIMARY KEY,
    owner           uuid,
    label           text NOT NULL DEFAULT '',
    dest_type       text NOT NULL DEFAULT '',
    event           text NOT NULL DEFAULT '',
    ok              boolean NOT NULL DEFAULT false,
    error           text NOT NULL DEFAULT '',
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS log_stream_deliveries_owner_idx
    ON public.log_stream_deliveries (owner, created_at DESC);
CREATE INDEX IF NOT EXISTS log_stream_deliveries_event_idx
    ON public.log_stream_deliveries (event);

ALTER TABLE public.log_stream_deliveries ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "log_stream_deliveries_owner_select"
    ON public.log_stream_deliveries;
CREATE POLICY "log_stream_deliveries_owner_select"
    ON public.log_stream_deliveries
    FOR SELECT TO authenticated USING (owner = auth.uid());
