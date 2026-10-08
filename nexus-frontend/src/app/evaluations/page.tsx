"use client";

import { SimplePage } from "@/components/SimplePage";
import { EvaluationsPanel } from "@/features/evaluations/EvaluationsPanel";

/**
 * Halaman /evaluations — Evaluation & Testing built-in (Fitur #4).
 *
 * Dataset uji (CSV/JSON) dijalankan terhadap sebuah workflow; hasilnya
 * dibandingkan dengan expected dan diberi metrik accuracy/latency/cost
 * plus opsi LLM-as-judge. Riwayat run disimpan untuk perbandingan regresi.
 */
export default function EvaluationsPage() {
  return (
    <SimplePage
      title="Evaluasi"
      subtitle="Uji workflow dengan dataset, ukur accuracy, latensi, dan biaya — lalu bandingkan dengan baseline."
      maxW="max-w-5xl"
    >
      <EvaluationsPanel />
    </SimplePage>
  );
}
