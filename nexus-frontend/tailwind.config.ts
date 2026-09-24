import type { Config } from "tailwindcss";

// Catatan oklch + Tailwind 3.4 (temuan FASE 1, 2026-09-21):
// - Parser PostCSS MENOLAK sintaks spasi "rgb(R G B / a)" -> ModuleBuildError
//   500, halaman blank. Karena itu SEMUA warna di sini bentuk koma klasik.
// - Var 3-komponen oklch "L C H" + rgb(var(--x)/alpha) dirender UNGU oleh
//   Tailwind 3.4 (lihat globals.css). Nilai oklch tetap di :root globals.css
//   sebagai dokumen target migrasi Tailwind v4.
const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/features/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        bg: {
          DEFAULT: "rgb(250, 250, 250)",
          subtle: "rgb(244, 244, 245)",
        },
        surface: {
          DEFAULT: "rgb(255, 255, 255)",
          elevated: "rgb(255, 255, 255)",
        },
        border: {
          DEFAULT: "rgb(228, 228, 231)",
          strong: "rgb(212, 212, 216)",
        },
        fg: {
          DEFAULT: "rgb(24, 24, 27)",
          muted: "rgb(82, 82, 91)",
          subtle: "rgb(113, 113, 122)",
        },
        accent: {
          DEFAULT: "rgb(99, 102, 241)",
          hover: "rgb(79, 70, 229)",
          fg: "rgb(255, 255, 255)",
        },
        success: "rgb(34, 197, 94)",
        danger: "rgb(239, 68, 68)",
        warning: "rgb(245, 158, 11)",
        brand: {
          DEFAULT: "#6366F1",
          dark: "#4F46E5",
        },
      },
      borderRadius: {
        xs: "6px",
        sm: "10px",
        md: "14px",
        lg: "20px",
        xl: "28px",
      },
      boxShadow: {
        xs: "0 1px 2px 0 rgb(0, 0, 0, 0.04)",
        sm: "0 1px 3px 0 rgb(0, 0, 0, 0.06), 0 1px 2px -1px rgb(0, 0, 0, 0.04)",
        md: "0 4px 12px -2px rgb(0, 0, 0, 0.08), 0 2px 4px -2px rgb(0, 0, 0, 0.04)",
        lg: "0 12px 32px -4px rgb(0, 0, 0, 0.10), 0 4px 8px -4px rgb(0, 0, 0, 0.04)",
        focus: "0 0 0 4px rgb(99, 102, 241, 0.18)",
      },
      fontFamily: {
        sans: ["var(--font-sans)"],
        mono: ["var(--font-mono)"],
      },
      fontSize: {
        caption: ["11px", { lineHeight: "13px", letterSpacing: "0.006em", fontWeight: "500" }],
        footnote: ["12px", { lineHeight: "16px" }],
        subhead: ["13px", { lineHeight: "18px", fontWeight: "500" }],
        callout: ["15px", { lineHeight: "20px", letterSpacing: "-0.006em" }],
        body: ["17px", { lineHeight: "24px", letterSpacing: "-0.010em" }],
        title3: ["20px", { lineHeight: "28px", letterSpacing: "-0.010em", fontWeight: "600" }],
        title2: ["24px", { lineHeight: "32px", letterSpacing: "-0.014em", fontWeight: "600" }],
        title1: ["32px", { lineHeight: "40px", letterSpacing: "-0.019em", fontWeight: "600" }],
        display: ["48px", { lineHeight: "56px", letterSpacing: "-0.022em", fontWeight: "600" }],
      },
      transitionTimingFunction: {
        "out-apple": "cubic-bezier(0.32, 0.72, 0, 1)",
        "ease-apple": "cubic-bezier(0.4, 0, 0.2, 1)",
      },
      keyframes: {
        "fade-up": {
          from: { opacity: "0", transform: "translateY(8px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        "fade-in": {
          from: { opacity: "0" },
          to: { opacity: "1" },
        },
        shimmer: {
          "100%": { transform: "translateX(100%)" },
        },
      },
      animation: {
        "fade-up": "fade-up 400ms cubic-bezier(0.32,0.72,0,1) both",
        "fade-in": "fade-in 300ms ease-out both",
        shimmer: "shimmer 1.6s infinite",
      },
    },
  },
  plugins: [],
};
export default config;
