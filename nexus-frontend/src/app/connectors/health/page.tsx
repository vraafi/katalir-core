"use client";

import { SimplePage } from "@/components/SimplePage";
import { ConnectorHealthDashboard } from "@/features/connectors";

/**
 * Halaman /connectors/health — dashboard kesehatan konektor (FASE 2/3/6).
 *
 * Menampilkan hasil **probe live** (ALIVE/AUTH/DEAD/UNKNOWN) dari tabel
 * `connector_health`, bukan metadata katalog. Ini jawaban langsung atas
 * temuan audit: angka katalog tidak sama dengan "terhubung".
 */
export default function ConnectorHealthPage() {
  return (
    <SimplePage
      title="Connector Health"
      subtitle="Status nyata konektor dari probe live — ALIVE berarti benar-benar mengirim data."
      maxW="max-w-6xl"
    >
      <ConnectorHealthDashboard />
    </SimplePage>
  );
}
