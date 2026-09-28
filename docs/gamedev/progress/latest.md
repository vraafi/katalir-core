# Katalir Game Dev — Progress

Diperbarui 2026-09-28. Semua status di bawah punya bukti; yang belum
punya bukti ditandai begitu secara terbuka.

## Fase Terakhir

**G1 (Infrastructure) — IN PROGRESS**
- Commit: (akan diisi setelah commit)
- Selesai: verification gate (diuji 2 arah), pipeline runner,
  3-file template system, Cline terpasang dan terbukti jalan.
- Belum: orchestrator (tertahan BLOCKER-2), `/gamedev` namespace.

## Prasyarat

| Prasyarat | Status | Bukti |
|---|---|---|
| Dokumen Prompt 1 | LOLOS | 3 file `docs/gamedev/*.md` |
| Katalir production 200 | LOLOS | `GET katalir.de5.net` -> 200 |
| VPS agentgateway :3011 | LOLOS | systemd `active`, `127.0.0.1:3011`; docker open-connector + free-llm-gateway healthy |
| Keys terverifikasi | **GAGAL** | `ANTHROPIC_API_KEY` dan `DEEPSEEK_API_KEY` kosong (lihat blockers.md BLOCKER-1) |

## Status Komponen

| Komponen | Status | Bukti |
|---|---|---|
| Verification gate | **DONE** | PASS pada output lengkap, FAIL pada output tidak lengkap, dua-duanya exit code benar |
| Cline worker | **DONE** | `clite` v0.0.13 terpasang; sesi headless membuat `hello.txt`, isi diverifikasi ulang independen |
| Pipeline runner | **DONE** | `run_pipeline.py` kompilasi; memakai flag Cline yang benar |
| 3-file system | **DONE** | 3 template di `templates/gamedev/` |
| Orchestrator | **TERTAHAN** | BLOCKER-2: `cargo install kage` memasang crate orang lain |
| `/gamedev` namespace | BELUM | menunggu orchestrator |
| Studio Connector (Tauri) | BELUM | butuh Rust (BLOCKER-3) |

## Status Engine

| Engine | Status | Catatan |
|---|---|---|
| Web (Phaser) | BELUM | Tidak ada Phaser MCP (BLOCKER-5); dikemudikan via kode |
| Roblox | BELUM | Rust belum ada; MCP repo 178 hari stale |
| Unity | BELUM | Perlu tulis ulang rencana: bukan plugin official (BLOCKER-6) |
| Godot | BELUM | `hi-godot/godot-ai` kandidat, belum diuji |

## Proyek Aktif

Belum ada. Menunggu keputusan user soal BLOCKER-1 (worker utama).

## Blocker

Lihat `docs/gamedev/feedback/blockers.md` untuk detail dan cara
membuktikan ulang. Ringkas: BLOCKER-1 (key kosong) sampai
BLOCKER-7 (lisensi PixelLab).

## Keputusan Tertunda untuk User

1. Isi `ANTHROPIC_API_KEY` + `DEEPSEEK_API_KEY`, atau izinkan G1 jalan
   dengan Groq/Gemini sebagai worker?
2. Boleh pasang Rust (`rustup`)? Wajib untuk G3 dan G5.
3. PoC G2: Web tanpa MCP dulu, atau langsung Godot yang punya MCP?
