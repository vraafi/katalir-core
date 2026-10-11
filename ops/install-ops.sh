#!/usr/bin/env bash
# ============================================================================
# install-ops.sh — pasang watchdog + unit systemd yang diperbarui.
# Jalankan DI VPS sebagai root, dari /root/katalir-core:
#     bash ops/install-ops.sh
#
# Idempoten: boleh dijalankan berulang. Tidak menghapus data apa pun.
# ============================================================================
set -euo pipefail

BASE="${KATALIR_BASE:-/root/katalir-core}"

if [ "$(id -u)" -ne 0 ]; then
  echo "harus root" >&2; exit 1
fi

echo "== 1. pasang skrip watchdog =="
install -m 0755 "$BASE/ops/katalir-watchdog.sh" /usr/local/bin/katalir-watchdog.sh
ls -l /usr/local/bin/katalir-watchdog.sh

echo "== 2. pasang unit systemd =="
install -m 0644 "$BASE/ops/katalir-watchdog.service" /etc/systemd/system/katalir-watchdog.service
install -m 0644 "$BASE/ops/katalir-backend.service"  /etc/systemd/system/katalir-backend.service

echo "== 3. daemon-reload =="
systemctl daemon-reload

echo "== 4. aktifkan watchdog (enable + start) =="
systemctl enable --now katalir-watchdog.service

echo "== 5. terapkan unit backend baru (RestartSec=10, StartLimitBurst=5, graceful 30s) =="
systemctl restart katalir-backend.service

echo "== 6. verifikasi =="
sleep 5
systemctl is-active katalir-backend.service katalir-watchdog.service
echo "--- backend ---"
systemctl status katalir-backend.service --no-pager | head -12
echo "--- watchdog ---"
systemctl status katalir-watchdog.service --no-pager | head -12
echo "--- health lokal ---"
curl -sS -o /dev/null -w 'local  /katalir-api/health -> %{http_code}\n' --max-time 15 \
  http://127.0.0.1:8100/katalir-api/health
echo "--- health publik ---"
curl -sS -o /dev/null -w 'public /katalir-api/health -> %{http_code}\n' --max-time 20 \
  https://gateway.katalir.de5.net/katalir-api/health
echo "--- log watchdog ---"
tail -5 /var/log/katalir-watchdog.log 2>/dev/null || true
