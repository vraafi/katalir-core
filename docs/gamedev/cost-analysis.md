# Katalir Game Dev — Cost Analysis

Tanggal: 2026-09-28 · Sifat: **riset saja, belum ada yang dibayar**

## 1. Ringkasan

| Kategori | Komponen | Biaya |
|---|---|---|
| Orchestrator | Katalir Studio Connector (tulis sendiri) | $0 |
| Worker | cline/cline (Apache-2.0) | $0 |
| Framework | OpenGame (Apache-2.0) | $0 |
| Engine bridge G4 | IvanMurzak/Unity-MCP (Apache-2.0) | $0 |
| Engine bridge G5 | hi-godot/godot-ai (MIT) | $0 |
| Engine bridge G3 | Roblox studio-rust-mcp-server (MIT) | $0 |
| Asset 3D | MoGen (MIT) | $0 |
| Asset 2D | PixelLab MCP (license BELUM dikonfirmasi) | $0* |
| LLM | GEMINI_KEY_1..13, ANTHROPIC, GROQ, DEEPSEEK | $0 (kunci sudah ada) |
| GPU (opsional) | KAGGLE_API_TOKEN | $0 |
| Editor | Godot, Unity Personal, Roblox Studio | $0 |
| Toolchain | Rust (rustup) | $0 |

**Total biaya bulanan: $0.**

\* Dengan dua syarat: lisensi PixelLab MCP harus dikonfirmasi lebih
dulu, dan pemakaian GPU Kaggle tunduk pada kuota mingguan gratis.

## 2. Kunci yang sudah ada di `.env` (nama saja, tanpa value)

Dihitung dengan membaca **nama variabel saja** dari `.env`. Tidak ada
value yang dicetak atau disalin ke dokumen ini.

| Kunci | Jumlah | Peran di pipeline game dev |
|---|---|---|
| `GEMINI_KEY_1` .. `GEMINI_KEY_13` | 13 | Orkestrasi multi-agent: memecah 1 prompt jadi langkah-langkah. 13 kunci berarti rotasi saat rate limit kena. |
| `ANTHROPIC_API_KEY` | 1 | Coding agent kualitas tinggi untuk menulis TypeScript/Phaser. |
| `GROQ_API_KEY` | 1 | Inferensi cepat untuk iterasi asset dan cek cepat. |
| `DEEPSEEK_API_KEY` | 1 | Fallback murah saat kunci lain kena rate limit. |
| `OPENAI_API_KEY` | 1 | Provider kompatibel OpenAI tambahan. |
| `KAGGLE_API_TOKEN` | 1 | GPU gratis mingguan untuk membuat mesh dan training kecil. |
| `ROBLOX_OPEN_CLOUD_API_KEY` | 1 | Publish hasil ke Roblox (fase G3). |
| `ROBLOX_UNIVERSE_ID`, `ROBLOX_PLACE_ID` | 2 | Target publish Roblox yang sudah ada. |
| `PEXELS_API_KEY` | 1 | Stok foto sebagai placeholder aset sementara. |
| `BRAVE_CDP_URL` | 1 | Browser automation untuk memverifikasi game web berjalan. |
| `GITHUB_TOKEN` | 1 | Clone repo riset dan CI. |
| `HYRVE_API_KEY` | 1 | Model tambahan (sudah dipakai Katalir). |

**Kunci yang perlu didaftar baru: 0 untuk PoC web.**
Satu-satunya tambahan yang mungkin perlu: Rust toolchain (gratis, bukan
API key) dan Godot Editor (gratis).

## 3. Biaya tersembunyi yang harus jujur disebut

| Item | Status nyata |
|---|---|
| Listrik & mesin | Biaya lokal, tidak masuk hitungan bulanan |
| Rate limit Gemini | 13 kunci menutup sebagian besar, tapi kuota per hari tetap ada. Pipeline yang looping 24 jam akan kena. |
| Kaggle GPU | 30 jam/minggu gratis. Training asset berat bisa menghabiskan kuota dalam 1-2 hari. |
| Roblox Studio | Gratis, tapi hanya Windows, dan build prosesnya berat. |
| Unity | Unity Personal gratis di bawah ambang pendapatan. Amendment aset bisa memicunya jadi berbayar. |
| Storage asset | Git LFS atau object storage, cukup pada skala PoC. |

## 4. Yang TIDAK $0

- **Waktu.** 2-3 bulan Fase G1-G5 adalah investasi engineer, bukan biaya.
- **Verifikasi manual.** "1 prompt jadi game" tidak bisa dijamin 100%.
  See dokumen rekomendasi, bagian Risiko.
- **Lisensi PixelLab MCP** belum terkonfirmasi. Jangan diasumsikan gratis
  hanya karena repo-nya publik.
