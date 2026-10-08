"use client";

import { SimplePage } from "@/components/SimplePage";
import { InsightsPanel } from "@/features/insights/InsightsPanel";

/**
 * Halaman /insights — Insights & Analytics (Fitur #5).
 *
 * Success rate, error rate, latensi, waktu yang dihemat, dan ROI per rentang
 * 7/30/365 hari, dengan filter workflow dan ekspor CSV.
 */
export default function InsightsPage() {
  return (
    <SimplePage
      title="Insight"
      subtitle="Pantau kesehatan workflow: success rate, latensi, error, waktu yang dihemat, dan ROI."
      maxW="max-w-5xl"
    >
      <InsightsPanel />
    </SimplePage>
  );
}
