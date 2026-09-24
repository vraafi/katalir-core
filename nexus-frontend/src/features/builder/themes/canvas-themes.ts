/**
 * Tema kanvas Katalir (FASE 3).
 *
 * Kenapa token didefinisikan DUA kali (TS + CSS `globals.css`):
 *  - CSS custom properties (`[data-canvas-theme="..."]`) adalah sumber warna untuk
 *    SEMUA yang dirender oleh CSS: kartu node, badge status, edge, handle, glow.
 *  - Objek TS di sini adalah sumber kebenaran untuk hal yang TIDAK bisa dibaca
 *    dari CSS oleh library: `colorMode` React Flow, warna `<Background>`/`MiniMap`,
 *    dan label/urutan di theme switcher.
 *  - Uji silang: `tests/canvas-fase3.spec.ts` membandingkan NILAI TS dengan nilai
 *    `getComputedStyle` di DOM, sehingga dua sumber ini tidak bisa menyimpang
 *    tanpa ada tes yang merah. (Ini yang membuat duplikasi aman, bukan sekadar
 *    "dua tempat yang harus diingat".)
 *
 * Adaptasi dari n8n Design System — SENGAJA TIDAK DI-COPY PERSIS:
 * n8n memakai oranye sebagai primary; Katalir memang sudah menetapkan accent
 * violet-indigo (oklch 0.62 0.18 275) dan keputusan itu TIDAK diubah di FASE 3.
 * Yang diadopsi dari n8n adalah POLA-nya: node per-kategori punya warna sendiri
 * (trigger/action/warna aksi), dan status eksekusi membawa makna lewat glow
 * semantic (success/error), plus dot grid gelap ala "developer tool at midnight".
 */

export const CANVAS_THEMES = ["midnight", "daylight", "cyberpunk", "minimal"] as const;
export type CanvasThemeId = (typeof CANVAS_THEMES)[number];

export interface CanvasTheme {
  id: CanvasThemeId;
  /** Nama yang ditampilkan di theme switcher. */
  name: string;
  /** Deskripsi singkat untuk tooltip/preview. */
  description: string;
  /** React Flow `colorMode` — menentukan default token bawaan library. */
  colorMode: "dark" | "light";
  /** Latar kanvas (dipakai juga oleh token CSS --canvas-bg). */
  canvasBg: string;
  /** Warna titik grid — dipakai langsung oleh `<Background color>`. */
  gridColor: string;
  /** Warna kartu node. */
  nodeBg: string;
  nodeBorder: string;
  /** Warna per kategori node (pola n8n: trigger != action). */
  kindColor: { trigger: string; agent: string; mcp: string };
  /** Glow status eksekusi (semantic). */
  successGlow: string;
  errorGlow: string;
  /** `--node-pulse-color` (MachinaOS contract) = accent tema. */
  pulse: string;
  /** Edge diam vs edge saat data mengalir. */
  edge: string;
  edgeAnimated: string;
  /** Panel samping + teks. */
  panelBg: string;
  textPrimary: string;
  textSecondary: string;
  /** Warna mask minimap + warna node di minimap; alpha mengikuti tema. */
  minimapMask: string;
  minimapNode: string;
}

export const THEMES: Record<CanvasThemeId, CanvasTheme> = {
  midnight: {
    id: "midnight",
    name: "Midnight",
    description: "n8n-inspired, gelap, dot grid halus (default)",
    colorMode: "dark",
    canvasBg: "#1B1F23",
    gridColor: "rgba(255,255,255,0.04)",
    nodeBg: "#282E36",
    nodeBorder: "#363D47",
    kindColor: { trigger: "#FF6D5A", agent: "#5C9DF5", mcp: "#8B5CF6" },
    successGlow: "#26BD73",
    errorGlow: "#F55C5C",
    pulse: "#6366F1",
    edge: "#5C9DF5",
    edgeAnimated: "#8B5CF6",
    panelBg: "#1E2227",
    textPrimary: "#F0F2F5",
    textSecondary: "#8B909A",
    minimapMask: "rgba(27,31,35,0.75)",
    minimapNode: "#3A424C",
  },
  daylight: {
    id: "daylight",
    name: "Daylight",
    description: "Bersih, kontras tinggi untuk kerja siang",
    colorMode: "light",
    canvasBg: "#FAFAF8",
    gridColor: "rgba(24,24,27,0.06)",
    nodeBg: "#FFFFFF",
    nodeBorder: "#E4E4E7",
    kindColor: { trigger: "#EA580C", agent: "#4F46E5", mcp: "#7C3AED" },
    successGlow: "#16A34A",
    errorGlow: "#DC2626",
    pulse: "#6366F1",
    edge: "#6366F1",
    edgeAnimated: "#8B5CF6",
    panelBg: "#FFFFFF",
    textPrimary: "#18181B",
    textSecondary: "#52525B",
    minimapMask: "rgba(250,250,248,0.75)",
    minimapNode: "#D4D4D8",
  },
  cyberpunk: {
    id: "cyberpunk",
    name: "Cyberpunk",
    description: "Neon glow: cyan + magenta di atas hitam pekat",
    colorMode: "dark",
    canvasBg: "#0A0A0F",
    gridColor: "rgba(0,255,213,0.10)",
    nodeBg: "#1A1A2E",
    nodeBorder: "#2E2E52",
    kindColor: { trigger: "#FF2E63", agent: "#00FFD5", mcp: "#B14AED" },
    successGlow: "#00FFD5",
    errorGlow: "#FF2E63",
    pulse: "#00FFD5",
    edge: "#00FFD5",
    edgeAnimated: "#FF2E63",
    panelBg: "#11111C",
    textPrimary: "#E9FFF9",
    textSecondary: "#8C93B0",
    minimapMask: "rgba(10,10,15,0.8)",
    minimapNode: "#00FFD5",
  },
  minimal: {
    id: "minimal",
    name: "Minimal",
    description: "Ultra-clean flat, tanpa glow berlebih",
    colorMode: "light",
    canvasBg: "#FFFFFF",
    gridColor: "rgba(0,0,0,0.05)",
    nodeBg: "#F5F5F5",
    nodeBorder: "#E5E5E5",
    kindColor: { trigger: "#18181B", agent: "#18181B", mcp: "#52525B" },
    successGlow: "#18181B",
    errorGlow: "#18181B",
    pulse: "#18181B",
    edge: "#A1A1AA",
    edgeAnimated: "#18181B",
    panelBg: "#FAFAFA",
    textPrimary: "#18181B",
    textSecondary: "#71717A",
    minimapMask: "rgba(255,255,255,0.8)",
    minimapNode: "#D4D4D8",
  },
};

export const DEFAULT_CANVAS_THEME: CanvasThemeId = "midnight";
export const CANVAS_THEME_STORAGE_KEY = "katalir.canvasTheme";

export function isCanvasThemeId(v: unknown): v is CanvasThemeId {
  return typeof v === "string" && (CANVAS_THEMES as readonly string[]).includes(v);
}

export function themeOf(id: CanvasThemeId | string | null | undefined): CanvasTheme {
  return isCanvasThemeId(id) ? THEMES[id] : THEMES[DEFAULT_CANVAS_THEME];
}
