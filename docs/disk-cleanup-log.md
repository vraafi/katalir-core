# Disk Cleanup Log — C: 100% → 3.8 GB free

Insiden: `C:` penuh (238G/238G, **0 byte tersisa**) → build webpack gagal
`ENOSPC: no space left on device`, dan bahkan tool harness tidak bisa
menulis berkas log. Pemicu: tiap `next build` memindahkan `.next` lama ke
tempat sampah aman (`%TEMP%\katalir_build_trash`) — akumulasi **7,6 GB**.

## FASE 1 — SCAN (read-only, tanpa hapus apa pun)

### `%TEMP%` — total 8.271 MB
| Ukuran | Folder | Umur |
|---|---|---|
| **7.609 MB** | `katalir_build_trash` | 8–10 Okt (build trash kita sendiri) |
| 73 MB | `mozilla-temp-files` | <7 hari |
| 63 MB | `codebuddy-marketplace-install-249LGj` | <7 hari |
| 53 MB | `skills-1ZajWp` | <7 hari |
| 50 MB | `DockerDesktopUpdates` | <7 hari |
| 49 MB | `vb-head` | <7 hari |
| 45 MB | `swcfix` | <7 hari |
| 36 MB | `tr-backup-1791192187` | <7 hari |
| 28+16 MB | `pip-unpack-*` | <7 hari |
| 25/19/13/12/11 MB | `2dimg2motion`, `node-compile-cache`, `windags`, `gameicons`, `DiagOutputDir` | <7 hari |

**Entri >7 hari: hanya 7 buah, ukuran ≈ 0 MB**
(`update-check`, `jds460395781.tmp`, `DiagOutputDir`, 3× `browser-use-user-data-dir-*`, `WinSAT`).

### Dev cache (diukur nyata)
| Ukuran | Lokasi |
|---|---|
| **8.290 MB** | `AppData\Local\npm-cache` |
| **4.409 MB** | `AppData\Local\ms-playwright` |
| **1.407 MB** | `AppData\Local\pip` |
| — | `.cargo`, `go`, `go-build` → **ABSENT** (tidak ada) |

### Scratch log repo
Total **≈ 4 MB** (terbesar `_f3_e2e.log` 745 KB). Tidak signifikan.

**Kesimpulan FASE 1:** ruang habis bukan karena sampah lama, melainkan
(i) build trash kita sendiri 7,6 GB, (ii) cache dev 14,1 GB.

## FASE 2 — PINDAHKAN DEV CACHE KE HDD `D:` (429 GB bebas)

Metode: `robocopy /E /MOVE` (salin lalu hapus sumber; bukan penghapusan).

| Cache | Pindah ke | Bytes | File | FAILED |
|---|---|---|---|---|
| npm | `D:\caches\npm` | 7,817 GB | 127.054 | **0** |
| Playwright | `D:\caches\playwright` | 4,298 GB | 3.847 | **0** |
| pip | `D:\caches\pip` | 1,363 GB | 3.943 | **0** |
| **Total** | | **13,48 GB** | | **0** |

Build trash 7,6 GB juga direlokasi ke `D:\caches\trash\katalir_build_trash_20261010`
(4,389 GB / 1.762 file, 0 failed) — ini yang menghentikan `ENOSPC`.

### Konfigurasi baru (terverifikasi)
| Tool | Setting | Nilai | Bukti |
|---|---|---|---|
| npm | `npm config get cache` | `D:\caches\npm` | output perintah |
| pip | `pip config list` | `global.cache-dir='D:/caches/pip'` | ditulis ke `Roaming\pip\pip.ini` |
| Playwright | env `PLAYWRIGHT_BROWSERS_PATH` | `D:\caches\playwright` | `setx` (user-level) |
| pip (env) | `PIP_CACHE_DIR` | `D:\caches\pip` | `setx` (user-level) |
| Docker | — | tidak ada Docker Desktop → dilewati | — |

## FASE 3 — BERSIHKAN

- `%TEMP%` >7 hari: hanya 7 entri, ≈0 MB → tidak ada ruang berarti.
- Cache npm/pip/playwright: sudah **dipindah** (FASE 2), sumber sudah tidak ada.
- Sisa shell `AppData\Local\npm-cache`: tinggal 1 berkas penanda 1 byte.
- Scratch log repo: total 4 MB, mayoritas <7 hari → tidak dihapus.
- **Tidak ada** `node_modules`, `.next`, `out/`, `dist/`, `.git` yang disentuh.

## FASE 4 — VERIFIKASI

| Item | Sebelum | Sesudah |
|---|---|---|
| Bebas `C:` | **0 MB** | **3,8 GB** |
| Bebas `D:` | 429 GB | 408 GB (terpakai 13,5 GB cache) |
| Build webpack | gagal `ENOSPC` | lihat bukti E2E di bawah |
| `npm config get cache` | `%LOCALAPPDATA%\npm-cache` | `D:\caches\npm` |
| `pip config list` | default C: | `D:/caches/pip` |

Catatan penting: karena tool cache kini di `D:`, `C:` tidak lagi terisi
14 GB tiap kali instalasi. Yang masih menulis ke `C:` adalah build trash
(`%TEMP%\katalir_build_trash`) — pantau berkala; bisa direlokasi lagi bila
tumbuh >2 GB.
