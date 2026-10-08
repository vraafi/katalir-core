# Fitur #6 — Code Node (Sandbox)

**Status:** ✅ SELESAI — 14/14 skenario lolos (3× berturut-turut)
**Modul:** `code_sandbox.py` · **Tes:** `tests/test_code_sandbox.py`
**Migrasi:** tidak ada (sandbox tidak butuh tabel)

---

## A. RESEARCH

Tujuan: menjalankan kode **tidak tepercaya** dari node workflow dengan jaminan
yang diminta brief — tanpa filesystem, tanpa jaringan secara default, timeout
30 s, memori 128 MB, dan validasi AST.

### Temuan keamanan yang menentukan desain

Saat riset muncul **CVE-2026-76825** — sandbox escape pada **RestrictedPython
< 8.4** (CVSS **8.4 High**, dipublikasikan 16 Sep 2026):

> Metode `string.Formatter` (`format`, `get_field`, `get_value`, `vformat`)
> melakukan traversal atribut dan item **secara internal tanpa melewati
> `safer_getattr`**. Kode terbatas bisa memakai referensi objek hidup itu untuk
> mencapai globals fungsi, builtins, akses berkas, atau primitif eksekusi kode.

**Perbaikan:** versi **8.4**. Versi yang dipasang di sini: **8.5** → tidak
terpengaruh. Temuan ini yang menjadikan prinsip **"AST saja tidak cukup"**
sebagai dasar desain, bukan sekadar catatan.

### Perbandingan kandidat

| Paket / Pendekatan | Versi | Verdict | Alasan |
|---|---|---|---|
| **RestrictedPython** | **8.5** | ✅ **DIPAKAI (lapis 1)** | `Development Status :: 6 - Mature`, mendukung Python 3.10–3.15, lisensi **ZPL-2.1** (OSI-approved, permissive). `compile_restricted()` menolak `import`, `eval`, `exec`, `open`, `__subclasses__` **sebelum** eksekusi. Wajib ≥ 8.4 karena CVE-2026-76825. |
| `codejail` (Open edX) | — | ❌ | Bergantung pada **AppArmor + user OS terpisah**; tidak bisa dipakai di container Railway tanpa hak istimewa. |
| `secure-sandbox` | 0.0.1 | ❌ | Rilis **0.0.1** — belum matang, tidak ada riwayat produksi. Klaim "100% block rate" tidak dapat diaudit. |
| `pydantic-monty` / `agentbox-sandbox` / `codeshield-runtime` | — | ❌ | Disebut brief, tetapi tidak dapat diverifikasi sebagai paket matang/rilis stabil pada saat riset. Tidak dipakai tanpa verifikasi. |
| Docker / nsjail / gVisor | — | ❌ | Isolasi terkuat, tetapi Railway menjalankan container **tanpa hak istimewa** — tidak bisa menyalakan Docker-in-Docker atau namespace baru. Tidak layak untuk deploy saat ini. |
| `resource.setrlimit` | bawaan (Linux) | ✅ **DIPAKAI (lapis 3)** | Batas OS asli: `RLIMIT_AS` (memori), `RLIMIT_CPU`, `RLIMIT_NOFILE`, `RLIMIT_FSIZE`. Hanya ada di Linux → di Windows dilaporkan `unavailable`, tidak dipalsukan. |
| `subprocess` + hard kill | bawaan | ✅ **DIPAKAI (lapis 2)** | Proses terpisah + `timeout=` memberi pembunuhan paksa **lintas-platform**. |

### Verifikasi paket (bukan asumsi)

```
pip install --target ./_verify_f6 RestrictedPython
→ restrictedpython-8.5.dist-info   (License-Expression: ZPL-2.1,
                                    Development Status :: 6 - Mature,
                                    Requires-Python: >=3.10,<3.16)
```
Uji API nyata:
```
T1 kode aman dgn safe builtins: OK
T2 diblokir: 'import os'            -> ImportError: __import__ not found
T2 diblokir: 'import subprocess'    -> ImportError: __import__ not found
T2 diblokir: "__import__('os')"     -> SyntaxError (nama tidak valid)
T2 diblokir: "open('/etc/passwd')"  -> NameError: name 'open' is not defined
T2 diblokir: "eval('1+1')"          -> SyntaxError: Eval calls are not allowed.
T2 diblokir: "exec('x=1')"          -> SyntaxError: Exec calls are not allowed.
T2 diblokir: "(1).__class__...__subclasses__()" -> SyntaxError (nama tidak valid)
```
Lapis OS diuji terpisah:
```
A infinite loop: TIMEOUT dibunuh setelah ~3s -> OK
B memory bomb 500MB: rc=0 di Windows (resource TIDAK ADA) -> lapis OS dilewati, dilaporkan
C kode biasa: rc=0 out='halo dari sandbox' -> OK
```

**Pilihan:** `RestrictedPython` 8.5 (lapis AST) + `subprocess` (lapis proses) +
`resource` (lapis OS, Linux).

**Alasan:** hanya kombinasi ini yang memberi jaminan yang **benar-benar
ditegakkan di lingkungan deploy** (Railway = container Linux tidak berhak
istimewa). Docker/nsjail/gVisor lebih kuat tetapi **tidak bisa dijalankan** di
Railway; `codejail` butuh AppArmor + user OS; `secure-sandbox` masih 0.0.1.
Lisensi ZPL-2.1 dicatat sebagai **deviasi** dari preferensi MIT/Apache/BSD —
tetap OSI-approved dan permissive, jadi diterima, tetapi dilaporkan jujur.

---

## B. IMPLEMENTASI

### Berkas

| Berkas | Perubahan |
|---|---|
| `code_sandbox.py` | **Baru.** Validasi AST, runner subprocess, batas OS, API `execute()`, `capabilities()`. |
| `requirements.txt` | Pin `RestrictedPython==8.5` (dengan catatan CVE-2026-76825). |
| `tests/test_code_sandbox.py` | **Baru.** 14 skenario. |

### Arsitektur: tiga lapis (defence in depth)

| Lapis | Apa | Portabel? | Menutup |
|---|---|---|---|
| **1 — AST** | `compile_restricted` + allowlist eksplisit di `validate_python()` | ✅ Windows + Linux | import, eval, exec, open, escape atribut |
| **2 — Proses** | `subprocess` dengan interpreter bersih; kode user **tidak pernah** di proses API | ✅ | efek samping pada proses induk; hang (hard kill) |
| **3 — OS** | `resource.setrlimit`: `RLIMIT_AS` 128 MB, `RLIMIT_CPU`, `RLIMIT_NOFILE` 16, `RLIMIT_FSIZE` 0 | ❌ hanya Linux | memori berlebih, CPU, menulis berkas |

**Timeout** bekerja di **semua** platform lewat `subprocess.run(timeout=…)` yang
membunuh proses secara paksa.

### API modul

| Fungsi | Guna |
|---|---|
| `validate_python(code)` / `validate_javascript(code)` | Lapis 1 berdiri sendiri (dipakai sebelum eksekusi). |
| `run_python(code, timeout_s, memory_mb, allow)` | Jalankan Python terisolasi. |
| `run_javascript(code, timeout_s, memory_mb)` | Jalankan JS lewat `node` (dilaporkan jujur bila tidak ada). |
| `execute(code, language, ...)` | Titik masuk tunggal node Code; **tidak pernah melempar** untuk kode buruk. |
| `capabilities()` | Laporkan batas **nyata** lingkungan (tidak mengklaim lebih). |

### Allowlist, bukan blocklist

`safe_builtins` bawaan RestrictedPython **tidak memuat** `sum`, `min`, `max`,
`list`, `dict`, `enumerate`, `map`, `filter`, `all`, `any`, `abs`, `round`,
`reversed`, `next`. Karena itu ada **allowlist eksplisit**
(`SAFE_BUILTIN_NAMES`) yang mengambil nama-nama itu dari `builtins` asli —
hanya nama yang dikenal, tidak pernah objek berbahaya.

### Pembatasan yang dinyatakan jujur

- **"Tanpa jaringan"** dijamin oleh Lapis 1: `import socket`/`urllib`/`http`/
  `requests` semuanya ditolak, jadi tidak ada jalan mencapai jaringan. Bila
  kelak ada allowlist impor, jaringan **wajib** dikunci juga di lapis OS
  (namespace/iptables) — belum dilakukan.
- **Batas memori 128 MB** ditegakkan OS **hanya di Linux**. Di Windows modul
  `resource` tidak ada; hasil mengembalikan `os_limits: "unavailable"` dan
  `capabilities()["os_resource_limits"] = False` — **tidak dipalsukan**.
  AST + timeout tetap berlaku penuh di sana.

---

## C. HARD TEST

14 skenario (brief minta min 12). Semuanya dengan bukti raw output.

| # | Skenario | Status | Bukti (raw) |
|---|---|---|---|
| 1 | Kode Python valid berjalan | ✅ | `ok=True result=285 durasi=0.25s` |
| 2 | Output `print` tertangkap | ✅ | `stdout='halo python\n' result=7` |
| 3 | `import os` ditolak | ✅ | `import tidak diizinkan: os` |
| 4 | `import subprocess` ditolak | ✅ | `import tidak diizinkan: subprocess` |
| 5 | `open()` (filesystem) ditolak | ✅ | `fungsi tidak diizinkan: open()` |
| 6 | `eval()` ditolak | ✅ | `fungsi tidak diizinkan: eval()` |
| 7 | `exec()` ditolak | ✅ | `fungsi tidak diizinkan: exec()` |
| 8 | `__import__()` ditolak | ✅ | `fungsi tidak diizinkan: __import__()` |
| 9 | Escape lewat atribut ditolak | ✅ | `.__globals__` / `.__mro__` / `.__bases__` / `.__subclasses__` semua `akses atribut tidak diizinkan` |
| 10 | `os.system` / `check_output` / `getattr` ditolak | ✅ | `pemanggilan tidak diizinkan: .check_output()` · `fungsi tidak diizinkan: getattr()` |
| 11 | **Infinite loop dibunuh** | ✅ | `killed=True error=timeout: eksekusi dihentikan setelah 3s durasi_nyata=3.0s` |
| 12 | Validasi & error runtime | ✅ | kosong → `kode kosong` · `1/0` → `ZeroDivisionError` · bahasa ngawur → `tidak didukung` · `None` → `kode harus berupa teks` |
| 13 | Isolasi + capabilities jujur | ✅ | sandbox **tidak** mengubah env induk · `timeout_s=30 memori=128 os_resource_limits=False` (benar di Windows) |
| 14 | JavaScript + penolakan pola | ✅ | `JS ok=True result=14` (1+4+9) · `require('child_process')` → `pola tidak diizinkan di JavaScript: 'require('` |

Hasil akhir: **`14 passed`** — dijalankan 3× berturut-turut: `14 / 14 / 14`.

### Tiga bug nyata yang ditemukan tes ini

**BUG-6a — subprocess memakai interpreter yang SALAH.**
`_python_bin()` semula mengembalikan `sys.executable`, tetapi `python` di PATH
adalah **3.13.12** (tanpa RestrictedPython) sementara modul dijalankan oleh
**3.12** (punya). Akibatnya sandbox **selalu** gagal
`No module named 'RestrictedPython'`. Ditemukan dengan membandingkan
`sys.executable` vs `shutil.which('python')`. → Diperbaiki: selalu pakai
`sys.executable` + wariskan `sys.path` lewat `PYTHONPATH`, dan **buang** flag
`-I` (isolated) karena `-I` mengabaikan `PYTHONPATH` — isolasi sesungguhnya
datang dari AST + proses terpisah + batas OS, bukan dari `-I`.

**BUG-6b — `safe_builtins` tidak memuat `sum`, `print` tidak tertangkap,
dan `_getiter_` hilang.**
Tiga cacat berurutan yang hanya muncul saat dijalankan sungguhan:
(i) `sum` bukan bagian `safe_builtins` → `NameError`;
(ii) `PrintCollector.txt` adalah **list** potongan teks, bukan `str`, sehingga
`stdout` sempat menjadi list (dan `.strip()` di tes meledak);
(iii) `_getiter_` tidak diisi → setiap `for`/comprehension gagal
(`NameError: name '_getiter_' is not defined`).
→ Diperbaiki: allowlist eksplisit, `"".join(txt)`, dan `g["_getiter_"] = iter`.

**BUG-6c — `NODE_OPTIONS` dan bentuk flag V8 yang salah.**
Dua cacat pada jalur JavaScript:
(i) `NODE_OPTIONS` diwariskan dari induk (membawa `--require` shim + flag
eksperimental) → `node: bad option: --experimental-wasm-exnref`. Lebih buruk
lagi: **mewariskan env induk apa adanya ke sandbox adalah kebocoran**.
→ Diperbaiki dengan `_node_env()` yang hanya meneruskan
`PATH`/`SYSTEMROOT`/`HOME`.
(ii) `--max-old-space-size 128` ditulis sebagai dua token, sehingga `node`
membaca `-e` sebagai nilai ukuran →`illegal value for flag --max-old-space-size`.
→ Diperbaiki ke bentuk `--max-old-space-size=128`.

---

## D. VERIFIKASI

- `pytest tests/test_code_sandbox.py` → **14 passed**, 3× berturut-turut.
- Bukti kedua bahasa bekerja end-to-end:
  ```
  JS ok: True | result: 14 | stdout: 'js jalan' | err: None
  PY ok: True | result: 7  | stdout: 'halo python\n'
  ```
- `capabilities()` melaporkan batas nyata, termasuk
  `os_resource_limits: False` di Windows (jujur, bukan klaim).

## E. STATUS

Lolos. Lanjut ke Fitur #7 (External Secrets Manager).
