# Tokens 2026 — Katalir (oklch, dark-first-ready)

Keputusan: GANTI nilai `--bg/--surface/--border/--fg/--accent/--success/--warning/--error/--info`
dari `rgb()` ke `oklch()` sesuai misi. Skala/ketentuan lain (radius, shadow, tipografi,
motion) SUDAH sesuai — tidak diubah.

> Catatan: file `globals.css` + `tailwind.config.ts` BELUM diubah di FASE 0
> (menunggu approval). Di bawah nilai target persis untuk di-apply di FASE 1.

```css
:root {
  --background: oklch(0.99 0.005 85);
  --surface:    oklch(0.97 0.008 85);
  --border:     oklch(0.90 0.010 85);
  --text:       oklch(0.18 0.015 275);
  --text-muted: oklch(0.45 0.015 275);
}
.dark {
  --background: oklch(0.15 0.01 275);
  --surface:    oklch(0.19 0.012 275);
  --border:     oklch(0.26 0.015 275);
  --text:       oklch(0.95 0.008 85);
  --text-muted: oklch(0.65 0.015 275);
}
:root, .dark {
  --accent:  oklch(0.62 0.18 275);
  --success: oklch(0.68 0.15 155);
  --warning: oklch(0.75 0.15 75);
  --error:   oklch(0.62 0.19 15);
  --info:    oklch(0.68 0.13 230);
}
```

Mapping ke variabel repo saat ini: `--bg`<-`--background`, `--bg-subtle` tetap
turunan surface, `--surface-elevated` = surface + shadow-md, `--fg*`<-`--text*`,
`--accent-hover` = accent 10% lebih terang (oklch L+0.06), `--accent-fg` = putih
di light / background di dark. Tailwind `colors` TIDAK berubah bentuk
(`rgb(var(--x) / <alpha>)`) — hanya nilai var yang diganti, jadi 0 refactor
komponen. `color-scheme: light/dark` dipertahankan agar scrollbar/form native
ikut tema. Kontras: text/background light ~15.4:1, dark ~14.1:1 (WCAG AAA
untuk body); text-muted keduanya > 4.5:1 (AA).
