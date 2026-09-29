# Katalir Game Dev — Stack Recommendation

Riset selesai 2026-09-28. Semua angka berasal dari GitHub REST API.
Detail per repo ada di `research.md`, biaya di `cost-analysis.md`.

**Fase ini riset. Tidak ada kode yang ditulis, tidak ada dependency yang
dipasang, tidak ada deploy.**

## 0. Tiga temuan yang mengubah rencana

1. **`kage` tidak layak jadi orchestrator.** Brief menyebutnya "AI-native
   cron". Faktanya: **3 stars, tanpa license, 267 hari tanpa commit.**
   Memakainya sebagai fondasi berarti membangun di atas proyek yang sudah mati.
2. **Tidak ada Phaser MCP server.** Brief merekomendasikan PoC Web
   (Phaser), tapi pencarian API tidak menemukan satupun Phaser MCP yang
   nyata. Jadi target PoC **tidak punya engine bridge**; Phaser harus
   dikemudikan lewat kode yang dihasilkan worker, bukan lewat MCP.
3. **Rust toolchain tidak ada di mesin ini.** Empat repo kandidat adalah
   Rust. Bukan blocker riset, tapi pekerjaan install nyata.

## 1. Rekomendasi Final

| Kategori | Pilihan | Alternatif | Alasan (berbasis data) |
|---|---|---|---|
| Orchestrator | **LoopFlow pattern sendiri + cron (Task Scheduler)** | loopflow (repo) | Keputusan user 2026-09-28. Semua kandidat eksternal gugur: `kage` mati dan `cargo install kage` bahkan memasang crate milik orang lain; `HarnessOfHarness` artefak riset; `loopflow` sendiri belum punya keluaran JSON atau verdict terstruktur. Pola gate yang dipakai sudah ada dan terbukti jalan di `scripts/gamedev/verify_gate.py` (PASS dan FAIL, dua-duanya exit code benar). Cron Windows memicu runner-nya. |
| Worker | **cline/cline** | (Claude Code via API saja) | 69.499 stars, **Apache-2.0**, aktif 0 hari. `anthropics/claude-code` punya 148k stars tapi lisensi `NONE` — source-available, bukan OSS. Claude tetap bisa dipakai lewat `ANTHROPIC_API_KEY`, tapi bukan sebagai fondasi yang di-*vendor-lock*. |
| Framework | **leigest519/OpenGame** | htdt/godogen | 2.958 stars, Apache-2.0, TypeScript, 25 hari. Jalur web-nya matang; jalur 3D masih PR. `godogen` lebih besar (7k) tapi Python dan fokus Godot/Bevy, tidak cocok untuk PoC web. |
| Engine Bridge G3 (Roblox) | **Roblox/studio-rust-mcp-server** | (tidak ada) | Satu-satunya repo **official** di daftar. Tapi 178 hari stale + 21 issue + butuh Rust + Windows-only. Kandidat G3, bukan PoC. |
| Engine Bridge G4 (Unity) | **IvanMurzak/Unity-MCP** | CoderGamester/mcp-unity | 4.349 stars, Apache-2.0, aktif 0 hari, jalan dengan Claude Code/Gemini/Copilot. 54 issue terbuka = surface besar, itu risiko yang harus diuji. |
| Engine Bridge G5 (Godot) | **hi-godot/godot-ai** | Coding-Solo/godot-mcp | 2.668 stars, MIT, aktif 0 hari, hanya 8 issue. `godot-mcp` lebih stars (5.8k) tapi 165 hari stale dan 72 issue. |
| Asset 3D | **krazyjakee/MoGen** | (tidak ada) | Satu-satunya kandidat 3D di daftar. 35 stars, MIT, aktif 10 hari, butuh Rust. Single point of failure —dicatat di Risiko. |
| Asset 2D | **pixellab-code/pixellab-mcp** (conditional) | (tidak ada) | `pixelda` di brief **SKIP**: 321 hari mati, tanpa license, bahasa SCSS. PixelLab MCP ada (42 stars) tapi **lisensi belum dikonfirmasi** — jangan dipakai sebelum dicek. |
| Connector | **Katalir Studio Connector** | Cloudflare Tunnel (repo tidak diverifikasi) | `sorreal` dan `@wearewebera/mcp-tunnel` ada di brief tanpa URL dan tidak sempat diverifikasi. Tidak direkomendasikan tanpa data. |

### 1.1 Kompatibilitas antar komponen

- Cline (Node/TS) + OpenGame (Node/TS): kompatibel, satu runtime.
- Cline + Unity-MCP / godot-ai: keduanya MCP, jadi bisa dihubungkan dari
  Cline yang speaks MCP. Godot lewat GDScript, jadi butuh Godot terpasang.
- Roblox MCP: Rust, jadi **tidak kompatibel dengan stack Node tanpa
  toolchain tambahan**. Ini yang memisahkan G3 dari G1-G2.
- MoGen: Rust, standalone lewat CLI. Harus dipanggil sebagai proses,
  bukan lewat MCP.

## 2. Biaya Total

**$0 / bulan.** Rincian dan syaratnya di `cost-analysis.md`.

Dua syarat yang harus jujur disebut: lisensi PixelLab MCP belum
terkonfirmasi, dan kuota Gemini/Kaggle tetap ada batasnya meski kunci
nya gratis.

## 3. Proof of Concept Plan — 1 minggu

**Engine: Web (Phaser).** Dipilih karena: satu runtime dengan Node
yang sudah ada, tidak perlu editor yang harus diinstal, dan bisa
diverifikasi otomatis lewat `BRAVE_CDP_URL`.

**Kenapa bukan Godot/Unity di PoC:** keduanya butuh editor terinstal dan
lisensi, menambah hari setup, dan tidak memberi informasi apa pun soal
MCP karena Web tidak punya MCP (lihat temuan 0.2). PoC harus
membuktikan orkestrasi, bukan kompatibilitas engine.

### 3.1 Jadwal 7 hari

| Hari | Pekerjaan | Keluaran yang harus ada |
|---|---|---|
| 1-2 | Pasang `clite` (bukan `cline`) dan konfirmasi mode headless.
| 1-2 | Pakang `clite` (bukan `cline`) dan konfirmasi mode headless. LoopFlow gate sudah ada; tambahkan pemicu cron. | 1 prompt menghasilkan run log JSON terstruktur plus verdict PASS/FAIL. |
| 5-6 | Jalankan 1 prompt end-to-end. Loop: hasil worker -> build -> verifikasi headless via `BRAVE_CDP_URL` -> umpan balik ke worker. Maks 5 iterasi. | 1 game yang benar-benar jalan di browser. |
| 7 | Ukur dan tulis jujur: berapa iterasi, berapa menit, berapa-interupsi manusia. | Angka, bukan klaim. Laporan di `docs/gamedev/poc-results.md`. |

### 3.2 Metrik sukses PoC

PoC dianggap berhasil kalau, tanpa intervensi manusia di tengah:

1. 1 prompt menghasilkan proyek Phaser yang **kompilasi tanpa error**.
2. Game **jalan di browser** (terverifikasi headless, bukan diklaim).
3. Minimal 1 aset visual/gameplay **dihasilkan atau di-place**, bukan placeholder abu-abu.
4. Loop verifikasi otomatis menemukan kesalahan dan worker memperbaikinya
   tanpa manusia.

Kalau poin 1-2 tercapai tapi 3-4 tidak, itu **PoC parsial** dan harus
dilaporkan sebagai parsial.

## 4. Risiko + Mitigasi

| # | Risiko | Bukti | Mitigasi |
|---|---|---|---|
| R1 | **Tidak ada MCP untuk engine Web.** Target PoC tidak punya bridge. | 5 query API, tidak ada hasil Phaser MCP (§3.1 research) | PoC Web dikemudikan lewat kode, bukan MCP. Kalau butuh kontrol editor, Godot/Unity tetap menyediakan MCP. |
| R2 | **Orkestrator kandidat tidak ada yang matang.** | `kage` 3 stars/tanpa license/267d; `loopflow` 3 fitur dasar masih open | Tulis connector sendiri yang kecil. Kurangsekali lebih murah daripada menunggu kandidat. |
| R3 | **MoGen adalah single point of failure untuk 3D.** | Satu-satunya kandidat 3D, 35 stars, butuh Rust | PoC tidak butuh 3D. Tunda sampai G5, dan siapkan fallback procedural mesh. |
| R4 | **Rate limit Gemini.** 13 kunci bukan berarti tanpa batas. | Nama kunci ada di `.env`; kuota harian tetap berlaku | Rotasi kunci + backoff. Ubah target "no rate limit" menjadi "rotasi + backoff". |
| R5 | **Rust toolchain tidak ada.** | `rustc`/`cargo` MISSING | Pasang `rustup` saat G3/G5. Tidak dipakai di G1-G2. |
| R6 | **Lisensi PixelLab MCP belum jelas.** | API mengembalikan `NONE` | Jangan pakai sebelum lisensi dikonfirmasi. Aset 2D sementara pakai placeholder. |
| R7 | **Unity-MCP punya 54 issue terbuka.** | API `open_issues_count: 54` | G4 dimulai dengan spike 2 hari untuk tool yang paling sering dipakai, bukan langsungurfaces penuh. |
| R9 | **"1 prompt jadi game 100% tanpa intervensi" mungkin tidak tercapai.** | Tidak ada bukti eksternal, dan loop agentik punya batas | Nyatakan ini sebagai **aspirasi**, bukan komitmen. Ukur di PoC, laporkan angkanya apa adanya. |
| R9 | **"1 prompt jadi game 100% tanpa intervensi" mungkin tidak tercapai.** | Tidak ada bukti eksternal, dan loop agentik punya batas | Nyatakan target ini sebagai **aspirasi**, bukan komitmen. Ukur di PoC, laporkan angkanya apa adanya. |

## 5. Timeline G1-G5

| Fase | Isi | Durasi | Syarat keluar |
|---|---|---|---|
| **G1** | Infra: Cline headless + Studio Connector + run log JSON | 1-2 hari | Connector menerima prompt, log terstruktur |
| **G2** | PoC Web/Phaser end-to-end | 1-2 minggu | 1 prompt -> game jalan, angka iterasi tercatat |
| **G3** | Roblox: pasang Rust, `studio-rust-mcp-server`, spike publish | 2-3 minggu | 1 game Roblox ter-publish via `ROBLOX_OPEN_CLOUD_API_KEY` |
| **G4** | Unity: `IvanMurzak/Unity-MCP`, spike 2 hari dulu | 3-4 minggu | 1 scene Unity dibangun lewat MCP, tanpa manual copy-paste |
| **G5** | Godot: `hi-godot/godot-ai` + MoGen (Rust) + polish | 2-3 minggu | 1 game Godot jalan, aset 3D dari MoGen |
| | **Total** | **2-3 bulan** | |

G1-G2 bisa dikerjakan tanpa menginstall apa pun. G3 dan G5 butuh
Rust. G4 butuh Unity Editor terpasang.

## 6. Yang perlu keputusan user sebelum Prompt 2

1. **Web/Phaser tanpa MCP** atau **langsung Godot dengan MCP** untuk PoC?
   Rekomendasi: Web dulu, karena lebih cepat membuktikan orkestrasi.
2. **Rust boleh diinstal?** Required untuk G3 dan G5.
3. **Asset 2D** — konfirmasi lisensi PixelLab, atau pakai placeholder dulu?
4. **Target "1 prompt -> game"** mau diukur sebagai apa? Playable
   minimal, atau game yang benar-benar layak main?

