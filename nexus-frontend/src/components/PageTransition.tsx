"use client";

import { motion, useReducedMotion } from "motion/react";

/**
 * Transisi halaman (FASE 4.4) — fade + slide 8px.
 *
 * Dipakai oleh halaman akun (/settings, /billing, /help) lewat `SimplePage`.
 * Aturan yang dipegang:
 *   - hanya `opacity` + `transform` (GPU, tanpa layout thrash);
 *   - `prefers-reduced-motion: reduce` -> TANPA pergeseran (y=0); fade tetap
 *     ada karena opacity tidak memicu motion sickness (WCAG 2.3.3);
 *   - durasi 200ms (token motion repo: 120/200/300) dan tidak memblokir
 *     interaksi (`pointer-events` tidak disentuh).
 */
export function PageTransition({ children, className }: { children: React.ReactNode; className?: string }) {
  const reduce = useReducedMotion();
  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y: reduce ? 0 : 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2, ease: [0.32, 0.72, 0, 1] }}
      data-testid="page-transition"
    >
      {children}
    </motion.div>
  );
}
