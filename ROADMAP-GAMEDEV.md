# ROADMAP — Katalir Game Dev Extension

Keputusan user 2026-09-28. **Eksekusi ditunda ke Q1 2027.** Dokumen
ini hanya mencatat status; tidak ada eksekusi G1 lebih lanjut.

## Status Fase

| Fase | Status | Catatan |
|---|---|---|
| **G1** | [!] partial, **ditunda** | Yang jadi: verification gate (terbukti PASS+FAIL), `clite` worker (terbukti headless), pipeline runner, 3-file template. Yang tertahan: orchestrator, `/gamedev` namespace. |
| **G2** | [ ] not started | Ditunda 2 minggu. Stack TS-only. |
| **G3** | [ ] not started | Butuh Rust; tidak dipasang (keputusan user). |
| **G4** | [ ] not started | Rencana perlu ditulis ulang: tidak ada plugin official Unity. |
| **G5** | [ ] not started | Butuh Rust (MoGen + Godot MCP GDScript). |

## Keputusan yang Sudah Dijawab

| # | Pertanyaan | Keputusan |
|---|---|---|
| 1 | API key worker | Pakai `GROQ_API_KEY` + `GEMINI_KEY_1..13` yang sudah ada. **Jangan** menunggu ANTHROPIC/DEEPSEEK/OPENAI. |
| 2 | Rust | **SKIP dulu.** TS-only untuk G2. Pasang saat G3/G5. |
| 3 | Engine PoC | **Web dulu, tanpa MCP.** Worker menghasilkan kode langsung. Godot (punya MCP) untuk nanti. |
| 4 | Orchestrator | **LoopFlow pattern sendiri + cron Windows Task Scheduler.** Bukan kage. |

## Kenapa kage Dihapus

Tiga alasan independen, semuanya terverifikasi:

1. `raskell-io/kage` cuma 3 stars, tanpa license, 267 hari tanpa commit.
2. `cargo install kage` memasang `github.com/bthkn/kage` -- crate milik
   orang lain dari 2023, bukan proyek yang disebut brief. Ini risiko
   supply chain, bukan sekadar proyek yang jelek.
3. Rust tidak ada di mesin ini, jadi `cargo` juga belum bisa dipakai.

## Kenapa Phaser MCP Dihapus

Tidak ada. Lima query GitHub tidak menemukan Phaser MCP yang nyata;
hasil teratas adalah fuzzy match tidak relevan seperti `sqlmap-skynet`.
Target Web karena itu **tidak punya engine bridge**, dan itu
disebutkan secara terbuka, bukan disamarkan.

## Stack Final (setelah keputusan)

| Kategori | Pilihan | Status |
|---|---|---|
| Orchestrator | LoopFlow pattern sendiri + cron | pattern sudah ada di `scripts/gamedev/verify_gate.py` |
| Worker | `clite` (Cline CLI v0.0.13) | terpasang, headless terbukti jalan |
| Framework (G2) | OpenGame | belum diuji |
| Engine bridge G4 | IvanMurzak/Unity-MCP | Delay, tulis ulang rencana |
| Engine bridge G5 | hi-godot/godot-ai | tertunda; butuh Godot terpasang, tidak butuh Rust |
| Asset 3D | MoGen | butuh Rust, tertunda |
| Asset 2D | PixelLab MCP | lisensi belum dikonfirmasi |

## Blockers yang Masih Terbuka

Lihat `docs/gamedev/feedback/blockers.md`. Yang utama:

- `ANTHROPIC_API_KEY` / `DEEPSEEK_API_KEY` kosong (tidak dipakai lagi
  setelah keputusan 1, tapi tetap perlu diisi kalau nanti mau dipakai).
- Rust belum ada (G3, G5).
- Lisensi PixelLab MCP belum jelas.

## Kapan Dilanjutkan

Q1 2027, dan hanya setelah:
1. Rust terpasang (kalau G3/G5 mau jalan).
2. Akses ke satu engine MCP nyata terverifikasi.
3. Target "1 prompt jadi game" punya definisi selesai yang bisa diukur,
   bukan slogan.
