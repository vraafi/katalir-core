-- Backup SKEMA 3 tabel R-1 (tanpa data)
-- dibuat: 20260930-181910
-- tujuan: rollback DROP POLICY di docs/security/audit-report.md §B.6
-- cara restore: psql -f <file ini>  (aman diulang: CREATE OR REPLACE / DROP IF EXISTS)

ALTER TABLE public.execution_logs ENABLE ROW LEVEL SECURITY;
-- RLS=True FORCE=False

DROP POLICY IF EXISTS "Izinkan semua akses ke execution_logs" ON public.execution_logs;
CREATE POLICY "Izinkan semua akses ke execution_logs" ON public.execution_logs
    FOR ALL TO "public"
    USING (true)
    WITH CHECK (true);

ALTER TABLE public.executions ENABLE ROW LEVEL SECURITY;
-- RLS=True FORCE=False

DROP POLICY IF EXISTS "Izinkan semua akses ke executions" ON public.executions;
CREATE POLICY "Izinkan semua akses ke executions" ON public.executions
    FOR ALL TO "public"
    USING (true)
    WITH CHECK (true);

ALTER TABLE public.workflows ENABLE ROW LEVEL SECURITY;
-- RLS=True FORCE=False

DROP POLICY IF EXISTS "Allow public read and write" ON public.workflows;
CREATE POLICY "Allow public read and write" ON public.workflows
    FOR ALL TO "public"
    USING (true)
    WITH CHECK (true);

DROP POLICY IF EXISTS "workflows_owner_all" ON public.workflows;
CREATE POLICY "workflows_owner_all" ON public.workflows
    FOR ALL TO "public"
    USING ((auth.uid() = user_id))
    WITH CHECK ((auth.uid() = user_id));
