# ops/ — operasional Katalir backend

Artefak di direktori ini dipasang ke VPS `107.173.51.78` (`/root/katalir-core`).

## Isi

| Berkas | Peran |
|---|---|
| `katalir-watchdog.sh` | Watchdog: cek `/health` tiap 60 s, restart backend setelah 2 kegagalan berturut, restart `cloudflared` bila jalur publik tetap gagal, kirim alert Telegram, catat semua ke `/var/log/katalir-watchdog.log`. |
| `katalir-watchdog.service` | Unit systemd untuk watchdog (enable + start saat boot). |
| `katalir-backend.service` | Unit backend yang diperbarui: `Restart=always`, `RestartSec=10`, `StartLimitBurst=5`, `--timeout-graceful-shutdown 30`. |
| `install-ops.sh` | Pemasang idempoten. Jalankan **di VPS** sebagai root. |
| `backend_hard_test.py` | 20 skenario hard test Fase 3 + 4 skenario Fase 4. Jalankan **di VPS**. |
| `frontend_e2e_playwright.py` | E2E frontend via Playwright (login UI → kirim prompt → screenshot → cek riwayat). Jalankan **di lokal**. |
| `_status_block.py` | Blok `_probe_with_timeout()` + `/status` yang disisipkan ke `api_server.py` di VPS (VPS tertinggal dari HEAD, jadi dipakai patch bedah — lihat catatan di bawah). |

## Pemasangan

```bash
# dari lokal
scp -i ~/.ssh/katalir_vps_ed25519 ops/* root@107.173.51.78:/root/katalir-core/ops/
ssh -i ~/.ssh/katalir_vps_ed25519 root@107.173.51.78 \
    'cd /root/katalir-core && bash ops/install-ops.sh'
```

## Verifikasi

```bash
ssh -i ~/.ssh/katalir_vps_ed25519 root@107.173.51.78 '
  systemctl is-active katalir-backend katalir-watchdog
  curl -sS -H "Host: gateway.katalir.de5.net" http://127.0.0.1:8100/katalir-api/health
  curl -sS -H "Host: gateway.katalir.de5.net" http://127.0.0.1:8100/katalir-api/status
  tail -20 /var/log/katalir-watchdog.log'
```

## Dua jebakan yang WAJIB diingat

1. **Probe lokal butuh header `Host` yang sah.** `api_server.py` memasang
   `TrustedHostMiddleware` (mitigasi CVE-2026-48710) dan `ALLOWED_HOSTS`
   produksi **tidak** memuat `127.0.0.1`:

   ```console
   $ curl -H "Host: 127.0.0.1" http://127.0.0.1:8100/katalir-api/health   -> 400 Invalid host header
   $ curl -H "Host: localhost"  http://127.0.0.1:8100/katalir-api/health   -> 200
   $ curl -H "Host: gateway.katalir.de5.net" http://127.0.0.1:8100/...     -> 200
   ```

   Watchdog versi pertama mengabaikan ini dan **me-restart backend tanpa sebab**
   pada `2026-10-11T10:36:09Z` (bukti di `/var/log/katalir-watchdog.log.v1`).
   Versi sekarang memakai `Host: gateway.katalir.de5.net`.

2. **Klien non-browser ditolak Cloudflare (`403 error code: 1010`).** Setiap
   skrip uji WAJIB memasang `User-Agent` browser. `curl` lolos, `urllib` polos
   tidak — hasilnya 403 palsu yang mudah disalahartikan sebagai backend rusak.

## Catatan: VPS tertinggal dari HEAD

Per 11 Okt 2026, `api_server.py` di VPS masih berbasis sebelum iterasi 1/2
(35 berkas `.py` berbeda, 12 berkas tidak ada — termasuk `mcp_compat.py`,
`chat_stream.py`, `evidence_ledger.py`, `workflow_ops.py`). Karena itu `/status`
dipasang lewat patch bedah, bukan dengan menyamakan seluruh repo.

Menyamakan penuh = pekerjaan rilis tersendiri: butuh memasang berkas baru +
memastikan dependensi baru ada di `venv/` (mis. `mcp>=2`), lalu menjalankan
regresi. **Jangan** lakukan `scp` borongan tanpa itu — `api_server.py` mengimpor
modul-modul tersebut di level modul, sehingga satu modul hilang = backend mati.

Cadangan: `api_server.py.bak-<UTC>` dan `.env.bak-<UTC>` ada di `/root/katalir-core`.
