# REPO RESEARCH — verifikasi 06345af (15–16 Okt 2026, akses 23:45–00:05 GMT+7)

## R1. Official: Gemini API Rate limits
- URL: https://ai.google.dev/gemini-api/docs/rate-limits
- Tanggal akses: 16 Okt 2026 00:01 GMT+7 (via WebFetch)
- Temuan: halaman TIDAK lagi menampilkan tabel RPM/TPM/RPD per model untuk
  Free tier inline — mengarah ke AI Studio ("View your active rate limits in AI Studio").
  Yang tertulis: rate limit per PROJECT (bukan per kunci), RPD reset tengah malam
  Pacific, 429 RESOURCE_EXHAUSTED saat limit terlampaui.
- Implikasi verifikasi: dokumen resmi SAAT INI tidak bisa dipakai untuk memastikan
  model mana yang punya kuota Free tier → bukti penentu tetap empiris (probe).

## R2. Official: Gemini API models.list
- URL: https://ai.google.dev/api/models#method-models-list
- Tanggal akses: 15 Okt 2026 (sesi EVL-1/EVL-2) — dipakai probe via SDK `google-genai`
  `client.models.list()`; katalog per kunci/proyek = 63 model (raw JSON terverifikasi).

## R3. Repo rotator/katalog (min. 3)
| Repo | Catatan | Akses |
|---|---|---|
| snailyp/gemini-balance | kanonik; FastAPI; rotasi kunci + filter model + monitoring; banyak fork | 15 Okt (sesi 06:10) + 16 Okt 00:03 |
| yxmeco/gemini-balance; Panda2data/gemini-balance | fork aktif; Panda2data menambah model-rate-limit per kunci (commit 67c2e4c, Agu 2025) | 16 Okt 00:03 |
| LiteLLM | router multi-provider, fallback + cooldown; jadi referensi pola cooldown per (kunci,model) | 15 Okt (sesi sebelumnya) |
| Kesimpulan yang sama dari sesi 15 Okt: freellmapi (34 provider/635 endpoint) ada PERINGATAN CISPA arXiv 2603.01919 — 88 model asal-usul tak jelas; jangan untuk data sensitif. | | |

## R4. Forum / troubleshooting 429 (model mismatch & kuota)
- https://blog.csdn.net/2601_95892788/article/details/167577094 (5 hari lalu):
  429 harus dibaca dari `quota metric` (per_minute vs per_day) — jangan
  otomatis disimpulkan "tidak gratis".
- https://blog.csdn.net/2601_95893075/article/details/167217890 (7 Okt 2026):
  "免费层和付费层配额计数规则不一样" — kuota free vs paid dihitung beda;
  429 pada free tier BUKAN bukti model berbayar.
- Implikasi: mendukung koreksi audit bahwa 429 ≠ paid-only.

## R5. Artikel KONTRA (mendukung "free tier = Flash-Lite saja")
- https://zhuanlan.zhihu.com/p/2092564867198853982 (5 hari lalu; mengutip Google
  Support #17004136, kebijakan 9 Okt 2026): "自 2026 年 10 月 9 日起, Free tier
  用户仅可使用 Flash Lite 系列轻量文本模型" — KONTEKS: aplikasi Gemini
  (consumer Web/App), bukan endpoint API.
- https://baijiahao.baidu.com/s?id=1878002968664180074 (3 Okt 2026, IT之家):
  eksplisit "Gemini Web / App 端" free personal users → Flash-Lite.
- https://baijiahao.baidu.com/s?id=1878036833743869245 (4 Okt 2026): sama,
  konteks konsumen.
- KONTRA-KONTRA (API tetap bisa Flash non-lite):
  - https://www.ai-indeed.com/encyclopedia/21474.html (28 Sep 2026): "Gemini API
    Free Tier — 写代码调用 3.5 Flash".
  - GitHub commit boyo-ai-agent-course dc49cc8 (22 Mei 2026): "gemini 2.5 pro
    免費方案可用但額度極低…pro 系列已不開放免費方案" — flash series OK di free.
- Verdict media: klaim "free tier = Flash-Lite saja" TERKONFIRMASI HANYA untuk
  aplikasi konsumen Gemini (Web/App); TIDAK berlaku untuk
  generativelanguage.googleapis.com (dipertahankan sebagai TERKOREKSI-BENAR).

## Skill dipakai (Aturan 2)
- Repo: github.com/obra/superpowers (clone D:/caches/skills-2026/superpowers,
  sudah ada dari sesi sebelumnya; terverifikasi hari ini).
- Skill relevan yang mengikat proses ini: `verification-before-completion`
  (klaim wajib bukti sebelum "selesai"), `systematic-debugging`, `writing-plans`.
- License repo: MIT (file LICENSE superpowers) — aman dipakai sebagai proses,
  tidak ada kode yang di-copy ke codebase proprietary.
