# Katalir Game Dev — Research Log

Riset **read-only**. Tidak ada kode produksi yang disentuh, tidak ada
dependency yang diinstal, tidak ada deploy.

Tanggal riset: 2026-09-28 · Repo: `C:\Users\user\Proyek_AI` · HEAD saat riset: `e7b153c`

## 0. Metode dan buktinya

Semua angka repo di bawah diambil dari **GitHub REST API v3** pada
2026-09-28, bukan dari halaman web yang bisa berubah dan bukan dari
ingatan:

```
GET https://api.github.com/repos/{owner}/{repo}
GET https://api.github.com/repos/{owner}/{repo}/issues?state=open
GET https://api.github.com/search/repositories?q=...
```

`stars`, `license.spdx_id`, `language`, `pushed_at` semuanya field dari
respons API. Skrip probe: `scripts/probe_repos.ps1` dan
`scripts/probe_search.ps1`. Token dibaca dari `.env` (`GITHUB_TOKEN`)
dan tidak pernah dicetak.

Kolom "umur" = jumlah hari sejak `pushed_at` pada tanggal riset.

## 1. Environment (Fase A)

| Item | Nilai |
|---|---|
| OS | Windows 11 Pro |
| Node | v24.16.0 |
| Python | 3.12.10 |
| Git | 2.54.0.windows.1 |
| **rustc / cargo** | **MISSING** |
| `.reference/` | sudah ter-gitignore (`git check-ignore` -> IGNORED) |

**Temuan yang berdampak:** Rust toolchain tidak ada di mesin ini. Empat
repo kandidat adalah Rust (`kage`, `MoGen`, `Roblox/studio-rust-mcp-server`,
`Tripwire`) dan semuanya butuh `rustc` + `cargo` sebelum bisa dibangun.
Ini bukan blocker pada fase riset, tapi menjadi pekerjaan install nyata
saat implementasi.

## 2. Verifikasi keberadaan repo (Fase B)

13 repo dengan URL eksplisit **semua ada**. Hasil API mentah
(`stars | license | language | pushed_at | umur`):

```
raskell-io/kage                       3 | NONE        | Rust       | 2026-01-05 | 267d
faisalishfaq2005/loopflow             38 | MIT         | TypeScript | 2026-06-29 |  91d
Flesymeb/HarnessOfHarness            146 | MIT         | TypeScript | 2026-09-28 |   1d
cline/cline                        69499 | Apache-2.0  | TypeScript | 2026-09-28 |   0d
anthropics/claude-code             148477 | NONE        | TypeScript | 2026-09-28 |   0d
leigest519/OpenGame                 2958 | Apache-2.0  | TypeScript | 2026-09-03 |  25d
htdt/godogen                        7017 | MIT         | Python     | 2026-09-26 |   2d
Donchitos/Claude-Code-Game-Studios 25506 | MIT        | Shell      | 2026-09-24 |   5d
NintendaDev/unikit-ai                 17 | MIT         | Shell      | 2026-09-26 |   3d
Roblox/studio-rust-mcp-server        492 | MIT         | Rust       | 2026-04-03 | 178d
krazyjakee/MoGen                      35 | MIT         | Rust       | 2026-09-18 |  10d
dada-x/pixelda                        16 | NONE        | SCSS       | 2025-11-12 | 321d
aliboIly/Tripwire                      3 | MIT         | Rust       | 2026-08-25 |  35d
```

### 2.1 Koreksi terhadap angka di brief

Brief menyebut beberapa angka stars yang **tidak akurat** menurut API.
Selisihnya searah (brief lebih rendah), jadi kemungkinan brief ditulis
dari cache lama:

| Repo | Stars di brief | Stars aktual (API) |
|---|---|---|
| leigest519/OpenGame | 1.684 | **2.958** |
| htdt/godogen | 6.730 | **7.017** |
| Donchitos/Claude-Code-Game-Studios | 21.8k | **25.506** |

Tidak mengubah keputusan, tapi dicatat agar tidak dipakai sebagai angka
di materi launch.

## 3. Tiga "Engine MCP Bridge" yang tidak punya URL (Fase B/C)

Brief menyebut tiga bridge tanpa URL. Ketiganya perlu dicari:

| Item di brief | Hasil pencarian faktual |
|---|---|
| "Unity official Claude Code plugin (Sept 2026)" | **Tidak ada repo official Unity.** Yang ada `IvanMurzak/Unity-MCP` (4.349 stars, Apache-2.0, C#, 0d) — proyek komunitas, bukan Unity Inc. |
| "Godot Editor MCP (Aug 2026)" | **Tidak ada repo official Godot.** Kandidat nyata: `Coding-Solo/godot-mcp` (5.863 stars, MIT, JavaScript, 165d) dan `hi-godot/godot-ai` (2.668 stars, MIT, GDScript, 0d) — keduanya komunitas. |
| "Phaser Game Agent MCP" | **TIDAK DITEMUKAN.** Lihat bagian 3.1. |

### 3.1 Phaser MCP tidak ada — temuan terpenting di fase ini

Hasil pencarian API, apa adanya:

```
"phaser mcp"          -> total 483, tapi top result: meta-ads-analyzer (433 stars),
                         sqlmap-skynet (98), claude-code-mastery (95)
"phaser game agent"   -> total 5, semua repo di bawah 5 stars
"phaser ai agent"     -> total 105, semua tidak relevan
"2d game mcp server"  -> total 9, semua di bawah 160 stars
```

Angka `total 483` itu fuzzy match, bukan bukti. GitHub mengembalikan repo
apa saja yang mengandung token mirip, dan `sqlmap-skynet` jelas bukan
server Phaser. **Tidak ada Phaser MCP server yang nyata.**

Konsekuensi langsung: brief merekomendasikan **PoC di Web (Phaser)**,
tapi target itu **tidak punya engine bridge MCP**. Phaser harus
dikemudikan lewat kode yang Katalir hasilkan sendiri, bukan lewat MCP.
Ini mengubah rencana PoC dan dicatat di dokumen rekomendasi.

## 4. Deep dive per repo (Fase C)

README dan open issues dibaca. Judul issue di bawah **disalin dari API**,
bukan disusun ulang.

### 4.1 Orchestrator

**`raskell-io/kage`** — 3 stars, **NO LICENSE**, Rust, 267 hari tidak disentuh.
- Deskripsi di brief: "AI-native cron, continuous mode, SQLite".
- Realita: 3 stars, tanpa license, tanpa aktivitas. Tidak layak jadi
  fondasi orkestrasi.
- **Verdict: SKIP.** Gagal 2 aspek (License, Lifecycle) dan 3 stars.

**`faisalishfaq2005/loopflow`** — 38 stars, MIT, TypeScript, 91 hari.
- YAML verification gate dengan step runner CLI.
- Open issues (semua 2026-06-29, sama dengan tanggal commit terakhir):
  - `[feature]: Structured gate verdicts via JSON schema`
  - `[feature]: --json output for loopflow run`
  - `[feature]: loopflow logs — browse run history`
- **Kelemahan nyata:** tiga request untuk fitur dasar (keluaran JSON,
  riwayat run, verdict terstruktur) masih terbuka sejak 3 bulan lalu.
  Gate-nya belum bisa dipakai mesin tanpa mem-parse YAML mentah. Untuk
  orkestrasi otonom itu belum cukup.
- **Verdict: ALTERNATIF**, bukan pemenang.

**`Flesymeb/HarnessOfHarness`** — 146 stars, MIT, TypeScript, 1 hari.
- Multi-day harness; brief mengaitkannya ke paper 2609.01481.
- Open issues:
  - `#2 [2026-09-14] Verify evals on Papers with Code`
  - `#1 [2026-09-14] Could you open-source the PRD document for the Fusepoint game?`
- **Kelemahan nyata:** artefak riset, bukan tool produksi. Issue #1
  menunjukkan PRD proyek masih tertutup. Issue #2 berarti evaluasi
  berada di luar repo. Ketergantungan pada satu paper juga risiko bila
  hasilnya tidak reproducible.
- **Verdict: ALTERNATIF.**


### 4.2 Worker

**`cline/cline`** — 69.499 stars, **Apache-2.0**, TypeScript, 0 hari.
- CLI headless resmi, lisensi permisif dan jelas.
- **Verdict: PEMENANG.** Satu-satunya worker besar dengan lisensi OSS.

**`anthropics/claude-code`** — 148.477 stars, **NO LICENSE** (spdx `NONE`),
TypeScript, 0 hari.
- Source-available, bukan open source; tidak ada LICENSE dengan SPDX id.
- **Verdict: SKIP untuk fondasi.** Catatan penting: `ANTHROPIC_API_KEY`
  **sudah ada** di `.env`, jadi Claude boleh dipakai sebagai LLM backend
  lewat API tanpa memaketkan repo proprietary itu sebagai fondasi.

### 4.3 Game framework

**`leigest519/OpenGame`** — 2.958 stars, Apache-2.0, TypeScript, 25 hari.
- Generator game web end-to-end.
- Issues: PR `feat(3d): ship threed_basic v1 milestone`,
  `#46 Landscape mapping: how AI game generators compare on editor experience`,
  PR `#44 Add EvoLink OpenAI-compatible provider support`.
- **Kelemahan nyata:** jalur 3D masih berupa PR yang belum merge dan
  provider baru masih PR. Jalur web/2D yang matang, bukan 3D.
- **Verdict: PEMENANG** untuk target Web.

**`htdt/godogen`** — 7.017 stars, MIT, Python, 2 hari.
- Mendukung Godot/Bevy/Babylon.js.
- **Kelemahan nyata:** Python berarti orkestrasi butuh interpreter
  terpisah, dan fokusnya Godot/Bevy bukan Web sehingga tidak langsung
  cocok dengan target PoC.
- **Verdict: ALTERNATIF**, bagus untuk fase G5.

**`Donchitos/Claude-Code-Game-Studios`** — 25.506 stars, MIT, **Shell**, 5 hari.
- 49 agent, tapi bahasa utama Shell.
- **Kelemahan nyata:** mengunci orkestrasi ke Shell, dan 49 agent berarti
  49 permukaan prompt yang harus dijaga. Overhead tinggi.
- **Verdict: TIDAK DIPILIH**, tetap dibaca sebagai referensi pola.

**`NintendaDev/unikit-ai`** — 17 stars, MIT, Shell, 3 hari.
- **Verdict: SKIP.** 17 stars, terlalu baru dan kecil untuk fondasi.

### 4.4 Engine MCP bridge

**`Roblox/studio-rust-mcp-server`** — 492 stars, MIT, Rust, 178 hari,
21 open issues.
- Satu-satunya repo **official** di daftar ini (organisasi Roblox).
- **Kelemahan nyata:** (a) Rust, sedangkan toolchain tidak ada di mesin;
  (b) 178 hari tanpa commit dengan 21 issue terbuka, artinya proyek ini
  bergerak lambat; (c) Roblox Studio hanya jalan di Windows.
- **Verdict: KANDIDAT G3**, bukan target PoC.

**`IvanMurzak/Unity-MCP`** — 4.349 stars, **Apache-2.0**, C#, 0 hari,
54 open issues.
- Deskripsi: "Any C# method may be turned into a tool by a single line",
  jalan dengan Claude Code, Gemini, dan Copilot.
- **Kelemahan nyata:** 54 issue terbuka berarti surface besar dengan
  banyak edge case. Unity Editor harus terpasang; lisensi Unity Personal
  gratis, tapi proses build punya syarat lisensi.
- **Verdict: PEMENANG untuk Unity (G4).**

**`Coding-Solo/godot-mcp`** — 5.863 stars, MIT, JavaScript, 165 hari,
72 open issues.
- Melakukan launch editor, menjalankan project, menangkap debug output.
- **Kelemahan nyata:** 165 hari tanpa aktivitas dan 72 issue terbuka.
  Kombinasi "jarang dipakai" dan "banyak yang belum selesai".
- **Verdict: ALTERNATIF Godot.**

**`hi-godot/godot-ai`** — 2.668 stars, MIT, GDScript, 0 hari, 8 open issues.
- Deskripsi menyebut "production-grade", hanya 8 issue, sangat aktif.
- **Kelemahan nyata:** GDScript berarti harus lewat Godot, tidak
  standalone Node. 2.668 stars dengan 8 issue menandakan adopsi baru,
  belum terbukti pada produksi jangka panjang.
- **Verdict: PEMENANG untuk Godot (G5)**, dengan kehati-hatian.


### 4.5 Asset generation

**`krazyjakee/MoGen`** — 35 stars, MIT, Rust, 10 hari. Issues #172 sampai
#174 semuanya 2026-09-16 (import mesh, skin, animasi).
- DSL menjadi GLB. Sangat aktif, tapi 35 stars = proyek kecil.
- **Kelemahan nyata:** Rust (toolchain belum ada), dan issue
  "Mesh import: skins and animation" menunjukkan pipeline mesh masih
  berjalan.
- **Verdict: SATU-SATUNYA kandidat 3D.** Tidak ada alternatif di daftar.

**`dada-x/pixelda`** — 16 stars, **NO LICENSE**, SCSS, **321 hari**, 0 issue.
- **Verdict: SKIP.** Tidak ada license, tidak ada aktivitas, dan
  bahasa SCSS bukan generator. Nol issue pada repo sekecil dan seold
  ini berarti "tidak dipakai", bukan "bersih".

**`pixellab-code/pixellab-mcp`** (fallback yang disebut brief) — 42 stars,
**NO LICENSE**, 0 hari.
- MCP resmi PixelLab. Ditemukan lewat pencarian, bukan dari brief.
- **Verdict: kandidat 2D, TAPI tanpa license.** Lisensi harus
  dikonfirmasi sebelum dipakai.

### 4.6 Bonus

**`aliboIly/Tripwire`** — 3 stars, MIT, Rust, 35 hari.
- **Verdict: SKIP.** 3 stars, terlalu kecil untuk jadi lapisan keamanan.

## 5. Skoring 5 aspek (Fase D)

Aturan: gagal satu aspek = SKIP. Ambang lifecycle = commit < 6 bulan
(180 hari).

| Repo | Bahasa | Protokol | Dependency | Lifecycle | License | Hasil |
|---|---|---|---|---|---|---|
| cline/cline | Ya TS | Ya | Ya | Ya 0d | Ya Apache-2.0 | **LOLOS** |
| leigest519/OpenGame | Ya TS | Ya | Ya | Ya 25d | Ya Apache-2.0 | **LOLOS** |
| Flesymeb/HarnessOfHarness | Ya TS | Ya | Ya | Ya 1d | Ya MIT | **LOLOS** |
| faisalishfaq2005/loopflow | Ya TS | Ya | Ya | Ya 91d | Ya MIT | **LOLOS** |
| IvanMurzak/Unity-MCP | Ya C# | Ya MCP | Ya | Ya 0d | Ya Apache-2.0 | **LOLOS** |
| hi-godot/godot-ai | Ya GDScript | Ya MCP | Ya | Ya 0d | Ya MIT | **LOLOS** |
| htdt/godogen | Ya Python | Ya | Ya | Ya 2d | Ya MIT | **LOLOS** |
| krazyjakee/MoGen | Ya Rust | Ya | Tidak, butuh cargo | Ya 10d | Ya MIT | LOLOS* |
| Roblox/studio-rust-mcp-server | Ya Rust | Ya MCP | Tidak, butuh cargo | Hati-hati 178d | Ya MIT | LOLOS* |
| anthropics/claude-code | Ya TS | Tidak | Ya | Ya 0d | **TIDAK** | **SKIP** |
| raskell-io/kage | Ya Rust | Tidak | Tidak, butuh cargo | **TIDAK** 267d | **TIDAK** | **SKIP** |
| dada-x/pixelda | **TIDAK** SCSS | Tidak | Ya | **TIDAK** 321d | **TIDAK** | **SKIP** |
| NintendaDev/unikit-ai | Hati-hati Shell | Tidak | Ya | Ya 3d | Ya MIT | **SKIP** |
| aliboIly/Tripwire | Ya Rust | Ya | Tidak, butuh cargo | Ya 35d | Ya MIT | **SKIP** (3 stars) |
| Phaser MCP | - | - | - | - | - | **TIDAK ADA** |

\* LOLOS secara Fifth, tapi butuh Rust toolchain yang belum ada di mesin ini.

### 5.1 Lima SKIP beserta alasannya

1. **`anthropics/claude-code`** — lisensi `NONE` (source-available, bukan
   OSS). Fondasi orkestrasi tidak boleh proprietary.
2. **`raskell-io/kage`** — brief menyebutnya orchestrator utama, tapi
   reality-nya 3 stars, tanpa license, 267 hari mati.
3. **`dada-x/pixelda`** — 321 hari mati, tanpa license, bahasa SCSS.
4. **`NintendaDev/unikit-ai`** — 17 stars, Shell, belum terbukti.
5. **"Phaser Game Agent MCP"** — tidak ada di GitHub sama sekali.
   (Bonus skip keenam: `aliboIly/Tripwire`, 3 stars.)

### 5.2 Lima repo dengan skor tertinggi

1. **`cline/cline`** — 69.499 stars, Apache-2.0, aktif 0 hari.
2. **`htdt/godogen`** — 7.017 stars, MIT, aktif 2 hari.
3. **`IvanMurzak/Unity-MCP`** — 4.349 stars, Apache-2.0, aktif 0 hari.
4. **`leigest519/OpenGame`** — 2.958 stars, Apache-2.0, aktif 25 hari.
5. **`hi-godot/godot-ai`** — 2.668 stars, MIT, aktif 0 hari, 8 issue saja.

