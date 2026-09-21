# UI/UX Research 2026 — keputusan adopsi per repo (ringkas, 3 baris)

Metode: baca README/docs + cek 5 aspek (bahasa, protocol, dependency,
lifecycle/static-export, license). Status repo = observasi lokal, bukan klaim.

1. **shadcn/ui (new-york, Base UI)** — ADOPSI pola: copy-paste primitive +
   token CSS-var; BUANG: CLI init penuh (repo sudah punya ui/* sendiri).
   Alasan: zero-dep, cocok static export, MIT.
2. **ark-ui/react** — ADOPSI pola: state-machine untuk dropdown/dialog_palette
   bila Radix bermasalah; BUANG: migrasi total. Alasan: headless, MIT, React 19 OK.
3. **assistant-ui/assistant-ui** — ADOPSI pola: komposisi Thread/Message/Composer/
   ActionBar/ChainOfThought; BUANG: runtime bawaan (butuh server). Alasan: pola
   UI murni bisa ditiru tanpa dep.
4. **lobehub/lobe-chat** — ADOPSI pola: layout workbench + model switcher;
   BUANG: seluruh app. Alasan: referensi visual, MIT.
5. **xyflow/xyflow v12** — ADOPSI: custom node + BaseEdge + getSmoothStepPath
   (sudah dipakai). BUANG: - . Alasan: sudah terpasang, MIT.
6. **xyflow-nexus (design system RF v12)** — ADOPSI: token node (card/icon/badge/
   handle 44px); BUANG: paket penuh bila berbayar/GPL. Alasan: referensi visual.
7. **motion (framer-motion baru)** — ADOPSI: micro-interaksi layout/spring sesuai
   durasi misi (120/200/300ms); BUANG: layout animation global bila jank di HP.
   Alasan: React 19 OK, MIT-ish.
8. **formkit/auto-animate (3.28KB)** — ADOPSI: reorder list/sidebar; BUANG: bila
   bentrok dengan spring canvas. Alasan: 1 baris, MIT.
9. **tremor (billing charts)** — ADOPSI: kartu usage/plan; BUANG: dashboard penuh.
   Alasan: Tailwind-native, Apache-2.0.
10. **magicui** — ADOPSI: selektif (skeleton/shimmer/empty-state); BUANG: efek
    berat (marquee/particles). Alasan: copy-paste, MIT.
11. **facebook/astryx** — ADOPSI: prinsip density/spacing; BUANG: sistem penuh
    (React Native oriented). Alasan: referensi.
12. **Linear/Vercel/Attio (visual)** — ADOPSI: quiet topbar, command palette,
    empty-state copy; BUANG: - . Alasan: benchmark SaaS 2026.

DITOLAK sebagai dep: n8n (Sustainable Use License, bukan OSS) — hanya referensi
format; Composio/Pipedream (vendor lock-in, butuh API key hosted).
