"use client";

import { Plus, Sparkles } from "lucide-react";

/**
 * Empty state kanvas (FASE 3).
 *
 * Kenapa perlu: sebelumnya kanvas kosong = bidang gelap tanpa petunjuk apa pun,
 * dan pengguna awam tidak tahu harus mulai dari mana (temuan audit FASE 0:
 * `/builder` tidak punya CTA). Sekarang: ilustrasi alur + satu CTA besar
 * ("Tambah Node") + satu jalur cepat ("Muat contoh workflow") yang langsung
 * menampilkan alur jadi.
 *
 * Ilustrasi digambar inline (SVG + token tema) — bukan file gambar: tidak ada
 * request jaringan, tidak ada aset yang bisa ketinggalan saat build, dan
 * warnanya otomatis ikut 4 tema.
 */
export function CanvasEmptyState({
  onAddNode,
  onLoadExample,
}: {
  onAddNode: () => void;
  onLoadExample: () => void;
}) {
  return (
    <div className="k-empty" data-testid="canvas-empty-state">
      <div className="k-empty__panel">
        <svg
          data-testid="empty-illustration"
          width="168"
          height="72"
          viewBox="0 0 168 72"
          aria-hidden="true"
          style={{ margin: "0 auto 12px", display: "block" }}
        >
          <g fill="none" stroke="var(--edge-color)" strokeWidth="2" strokeDasharray="6 4">
            <path d="M44 36 H78" />
            <path d="M110 36 H140" />
          </g>
          <g>
            <rect x="8" y="22" width="36" height="28" rx="8" fill="var(--node-bg)" stroke="var(--node-trigger-color)" />
            <rect x="78" y="22" width="32" height="28" rx="8" fill="var(--node-bg)" stroke="var(--node-action-color)" />
            <rect x="140" y="22" width="20" height="28" rx="8" fill="var(--node-bg)" stroke="var(--node-mcp-color)" />
          </g>
          <circle cx="62" cy="36" r="3" fill="var(--node-pulse-color)" />
          <circle cx="126" cy="36" r="3" fill="var(--node-pulse-color)" />
        </svg>

        <div className="k-empty__title">Kanvas masih kosong</div>
        <p className="k-empty__desc">
          Mulai dengan satu node, atau muat contoh alur untuk melihat cara kerjanya. Setelah ada
          beberapa node, klik <strong>Auto Layout</strong> supaya alurnya rapi otomatis.
        </p>

        <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
          <button
            type="button"
            data-testid="btn-empty-add-node"
            onClick={onAddNode}
            className="flex h-10 items-center gap-2 rounded-lg px-4 text-[13px] font-semibold text-[color:var(--canvas-accent-fg)]"
            style={{ background: "var(--canvas-accent-solid)" }}
          >
            <Plus size={16} strokeWidth={2} aria-hidden="true" />
            Tambah Node
          </button>
          <button
            type="button"
            data-testid="btn-empty-example"
            onClick={onLoadExample}
            className="flex h-10 items-center gap-2 rounded-lg border px-4 text-[13px] font-semibold"
            style={{
              borderColor: "var(--node-border)",
              color: "var(--canvas-text-primary)",
            }}
          >
            <Sparkles size={16} strokeWidth={1.75} aria-hidden="true" />
            Muat contoh workflow
          </button>
        </div>
      </div>
    </div>
  );
}
