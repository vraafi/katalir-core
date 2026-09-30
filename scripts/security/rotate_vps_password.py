"""Rotasi password root VPS dengan anti-lockout.

Urutannya penting: sesi LAMA tetap terbuka sampai sesi KEDUA dengan
password baru terbukti berhasil. Kalau `chpasswd` gagal diam-diam, kita
tahu sebelum sesi lama ditutup.

Tidak mencetak password baru ke stdout/log.
"""
import pathlib
import re
import secrets
import string
import sys

import paramiko

ROOT = pathlib.Path(__file__).resolve().parents[2]
LOG = pathlib.Path(r"C:\Users\user\AppData\Local\Temp\rot.log")


def env_value(key: str) -> str:
    text = (ROOT / ".env").read_text(encoding="utf-8", errors="replace")
    m = re.search(rf"^{key}\s*=\s*(\S+)", text, re.M)
    return m.group(1).strip().strip("\"'") if m else ""


def new_secret(n: int = 28) -> str:
    """Alfabet ASCII yang aman di shell (tanpa kutip/$/backtick/backslash)."""
    alphabet = string.ascii_letters + string.digits + "-_=+.,:@#%"
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(n))
        # Wajib punya huruf besar+kecil+angka agar lolos policy default.
        if (any(c.isupper() for c in pw) and any(c.islower() for c in pw)
                and any(c.isdigit() for c in pw)):
            return pw


def connect(host, user, password):
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(host, username=user, password=password, timeout=20,
              auth_timeout=20, banner_timeout=20)
    return c


def main() -> int:
    ip = env_value("VPS_IP")
    user = env_value("VPS_USERNAME")
    old = env_value("VPS_PASSWORD")
    lines = []

    lines.append(f"target={user}@{ip}")

    # 1. Sesi lama
    c1 = connect(ip, user, old)
    lines.append("step1: OK sesi lama terbuka")

    new = new_secret()
    # 2. Ubah password di server (tidak pernah kirim ke stdout)
    cmd = f"printf 'root:{new}\\n' | chpasswd && echo CHPASSWD_OK"
    _, out, err = c1.exec_command(cmd)
    rc = out.channel.recv_exit_status()
    lines.append(f"step2: chpasswd rc={rc} out={out.read().decode().strip()} err={err.read().decode().strip()[:80]}")
    if rc != 0:
        LOG.write_text("\n".join(lines), encoding="utf-8")
        return 1

    # 3. Sesi KEDUA dengan password BARU (sesi lama masih hidup)
    try:
        c2 = connect(ip, user, new)
        _, o2, _ = c2.exec_command("id -un")
        who = o2.read().decode().strip()
        c2.close()
        lines.append(f"step3: login password BARU -> OK (user={who})")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"step3: GAGAL {type(exc).__name__}: {str(exc)[:120]}")
        LOG.write_text("\n".join(lines), encoding="utf-8")
        return 1  # sesi lama SENGAJA dibiarkan terbuka difinally? tidak: tutup aman

    # 4. Password lama harus GAGAL
    try:
        c3 = connect(ip, user, old)
        c3.close()
        lines.append("step4: password LAMA masih BISA login -> ROTASI GAGAL")
        LOG.write_text("\n".join(lines), encoding="utf-8")
        return 1
    except Exception as exc:  # noqa: BLE001
        lines.append(f"step4: password LAMA ditolak -> {type(exc).__name__} (sesuai harapan)")

    c1.close()
    lines.append("step5: sesi lama ditutup")

    # 5. Tulis ke .env
    p = ROOT / ".env"
    text = p.read_text(encoding="utf-8", errors="replace")
    new_text = re.sub(r"^VPS_PASSWORD=.*$", f"VPS_PASSWORD={new}", text, flags=re.M)
    p.write_text(new_text, encoding="utf-8", newline="")
    lines.append("step6: .env diperbarui (nilai tidak dicetak)")

    # 6. Ulangi login dari proses BARU (anti-lockout terakhir)
    try:
        c4 = connect(ip, user, new)
        _, o4, _ = c4.exec_command("id -un")
        lines.append(f"step7: verifikasi ulang proses baru -> OK ({o4.read().decode().strip()})")
        c4.close()
    except Exception as exc:  # noqa: BLE001
        lines.append(f"step7: VERIFIKASI GAGAL {type(exc).__name__}: {str(exc)[:100]}")

    LOG.write_text("\n".join(lines), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
