-- migrations/2026-10-09-durable-dapr.sql
-- TASK 6 / Fitur #9: Durable Execution via Dapr — idempotency ledger.
--
-- Latar (Diagrid, 2026-10-06 — https://www.diagrid.io/blog/durable-n8n-workflows-dapr):
--   "Durability alone does not automatically make every external operation
--    safe."  Kasus nyata: node menagih kartu; tagihan sukses, tetapi proses
--   mati SEBELUM status node tercatat. Saat pulih, node dijalankan lagi.
--   Solusinya kunci idempoten stabil: workflow execution + node identifier.
--
-- Tabel ini LEDGER efek samping, BUKAN tabel checkpoint baru:
--   checkpoint tetap `executions` + `execution_steps` (fitur #2).
--   Ledger hanya mencatat "efek samping langkah Y sudah terjadi".
--
-- Skema NYATA (diverifikasi via information_schema, bukan diasumsikan):
--   executions.id            uuid
--   execution_steps.execution_id  uuid
-- Maka kolom execution_id di sini bertipe uuid agar FK-nya sahih.
--
-- Idempoten: aman dijalankan berulang.

CREATE TABLE IF NOT EXISTS public.durable_ledger (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    execution_id  uuid        NOT NULL,
    step_id       text        NOT NULL,
    key           text        NOT NULL,
    result        jsonb,
    created_at    timestamptz NOT NULL DEFAULT now()
);

-- Satu efek samping per (eksekusi, langkah). Inilah jaminan "sekali saja".
CREATE UNIQUE INDEX IF NOT EXISTS uq_durable_ledger_exec_step
    ON public.durable_ledger (execution_id, step_id);

-- Kunci juga unik supaya downstream bisa memakai `key` sebagai idempotency
-- key ke penyedia pembayaran (pola yang disebut Diagrid).
CREATE UNIQUE INDEX IF NOT EXISTS uq_durable_ledger_key
    ON public.durable_ledger (key);

CREATE INDEX IF NOT EXISTS ix_durable_ledger_execution
    ON public.durable_ledger (execution_id);

-- FK ke executions(id): ledger tidak boleh menunjuk eksekusi yang tak ada.
-- ON DELETE CASCADE supaya menghapus eksekusi tidak menyisakan sampah.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_durable_ledger_execution'
    ) THEN
        ALTER TABLE public.durable_ledger
            ADD CONSTRAINT fk_durable_ledger_execution
            FOREIGN KEY (execution_id) REFERENCES public.executions (id)
            ON DELETE CASCADE;
    END IF;
END $$;

ALTER TABLE public.durable_ledger ENABLE ROW LEVEL SECURITY;

-- Kepemilikan diturunkan lewat rantai:
--   durable_ledger.execution_id -> executions.workflow_id -> workflows.user_id
-- (`executions` tidak menyimpan user_id, jadi kebijakan lama yang menunjuk
--  e.user_id salah dan sudah dibuang.)
DROP POLICY IF EXISTS durable_ledger_select_own ON public.durable_ledger;
CREATE POLICY durable_ledger_select_own ON public.durable_ledger
    FOR SELECT USING (
        EXISTS (
            SELECT 1
            FROM public.executions e
            JOIN public.workflows w ON w.id = e.workflow_id
            WHERE e.id = public.durable_ledger.execution_id
              AND w.user_id = auth.uid()
        )
    );

COMMENT ON TABLE public.durable_ledger IS
    'Ledger idempotensi efek samping (TASK 6 / Fitur #9). Satu baris per (execution_id, step_id).';
