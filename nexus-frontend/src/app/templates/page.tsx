"use client";

import { SimplePage } from "@/components/SimplePage";
import { TemplateGallery } from "@/features/templates";

/**
 * Halaman /templates — galeri template workflow (Fitur #10).
 *
 * Memakai `SimplePage` (pola yang sama dengan /integrations, /settings) supaya
 * navbar minimal + provider (Auth, Query, I18n, CanvasTheme) konsisten. Lebar
 * dinaikkan ke `max-w-5xl` karena isinya kisi kartu 3 kolom, bukan formulir.
 */
export default function TemplatesPage() {
  return (
    <SimplePage
      title="Template"
      subtitle="Mulai dari alur siap pakai — pakai satu klik, lalu sesuaikan di Builder."
      maxW="max-w-5xl"
    >
      <TemplateGallery />
    </SimplePage>
  );
}
