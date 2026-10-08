# PUSH BLOCKER — instruksi manual

**Status commit:** `a3e6fd3` sudah ada di branch `main` (lokal).
**Origin head masih:** `39347f1` → **push TIDAK masuk.**

## Diagnosis (terbukti, bukan dugaan)

```
$ git push --verbose origin main
Pushing to https://github.com/vraafi/katalir-core.git
<hang, timeout 124 detik>

$ ssh -T git@github.com
git@github.com: Permission denied (publickey).

$ printf 'protocol=https\nhost=github.com\n\n' | git credential fill
<hang, exit 0, tanpa output>          <- credential helper menunggu interaksi

$ git config --get credential.helper
!".../PortableGit/mingw64/bin/git-credential-manager.exe"
```

Kredensial tersimpan ada (`credential-manager github list` → `x-access-token`),
tetapi `git credential fill` **hang** — artinya Git Credential Manager
menunggu **prompt interaktif** (refresh token / 2FA) yang tidak bisa
diselesaikan di lingkungan non-interaktif ini.

Ini kategori **"butuh password/login yang tidak ada di `.env`"** → sesuai
aturan brief: tulis instruksi manual, lanjut fitur lain.

## Cara menyelesaikan (pilih salah satu)

### Opsi A — jalankan sendiri (paling cepat)
Buka terminal **PowerShell** biasa (bukan sandbox), lalu:
```powershell
cd C:\Users\user\Proyek_AI
git push origin main
```
Dialog GitHub akan muncul → login → push selesai.
Saat itu commit `a3e6fd3` + semua commit fitur berikutnya akan terkirim.

### Opsi B — Personal Access Token (kalau tidak mau dialog)
1. Buat token di https://github.com/settings/tokens (scope `repo`).
2. Simpan ke `.env` sebagai `GITHUB_TOKEN=...` (JANGAN di-commit).
3. Beri tahu saya → saya push memakai:
   `git push https://x-access-token:<token>@github.com/vraafi/katalir-core.git main`

### Opsi C — install `gh` lalu login
```powershell
winget install GitHub.cli
gh auth login
cd C:\Users\user\Proyek_AI ; git push origin main
```

## Catatan
- Saya **tidak** memasukkan token apa pun ke URL remote (itu akan
  tertinggal di `.git/config` dan bocor).
- Semua pekerjaan **tersimpan aman di commit lokal** — tidak ada yang hilang.
- Saya lanjut mengerjakan fitur berikutnya sambil menunggu; commit akan
  menumpuk dan terkirim sekaligus saat push berhasil.
