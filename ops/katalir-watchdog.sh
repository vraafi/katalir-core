#!/usr/bin/env bash
# ============================================================================
# katalir-watchdog.sh — watchdog + auto-recovery untuk Katalir backend.
#
# KENAPA ADA: insiden 11 Okt 2026 menunjukkan gejala di FRONTEND bisa berasal
# dari sebab yang sama sekali lain (deploy basi). Watchdog ini menutup celah
# yang berbeda dan tetap perlu: backend/tunnel yang MATI tanpa terdeteksi.
# systemd `Restart=always` hanya menangani proses yang EXIT — ia tidak tahu
# bedanya "hidup tapi tidak bisa melayani" (mis. Supabase mati, event loop
# macet, port tidak listen) dan "sehat".
#
# DESAIN (best practice Okt 2026):
#   * Probe LIVENESS lokal (`http://127.0.0.1:8100/katalir-api/health`),
#     bukan URL publik. Kalau kita memprobe lewat Cloudflare, satu gangguan
#     Cloudflare akan memicu restart backend yang sebenarnya sehat.
#   * Butuh `FAIL_THRESHOLD` kegagalan BERTURUT-TURUT sebelum bertindak
#     (~2 menit). Satu kegagalan sesaat bukan alasan me-restart.
#   * Restart ditargetkan: backend dulu; cloudflared hanya bila backend sehat
#     tapi jalur publik tetap tidak bisa dijangkau.
#   * Setiap aksi dicatat ke file log (audit), dan alert dikirim ke Telegram
#     bila kredensial tersedia. Kredensial TIDAK pernah dicetak.
#   * Idempoten & aman: tidak menghapus apa pun, hanya `systemctl restart`.
# ============================================================================
set -uo pipefail

ENV_FILE="${KATALIR_ENV_FILE:-/root/katalir-core/.env}"
HEALTH_URL="${WATCHDOG_HEALTH_URL:-http://127.0.0.1:8100/katalir-api/health}"
PUBLIC_URL="${WATCHDOG_PUBLIC_URL:-https://gateway.katalir.de5.net/katalir-api/health}"
# WAJIB: api_server memasang TrustedHostMiddleware (mitigasi CVE-2026-48710)
# dan ALLOWED_HOSTS produksi TIDAK memuat 127.0.0.1. Tanpa header Host yang
# sah, probe lokal dijawab `400 Invalid host header` -- BUKAN 200 -- sehingga
# watchdog menyimpulkan "backend mati" padahal sehat, lalu me-restart-nya
# berulang kali. Ini ditemukan saat pengujian: watchdog v1 melakukan restart
# palsu pada 2026-10-11T10:36:09Z. Pakai host produksi (selalu ada di
# ALLOWED_HOSTS), bukan `localhost` (bisa dihapus orang lain kapan saja).
PROBE_HOST="${WATCHDOG_PROBE_HOST:-gateway.katalir.de5.net}"
LOG_FILE="${WATCHDOG_LOG:-/var/log/katalir-watchdog.log}"
STATE_FILE="${WATCHDOG_STATE:-/var/lib/katalir-watchdog.state}"
INTERVAL="${WATCHDOG_INTERVAL:-60}"
FAIL_THRESHOLD="${WATCHDOG_FAIL_THRESHOLD:-2}"
BACKEND_UNIT="katalir-backend.service"
TUNNEL_UNIT="cloudflared.service"

mkdir -p "$(dirname "$LOG_FILE")" "$(dirname "$STATE_FILE")" 2>/dev/null || true
touch "$LOG_FILE" 2>/dev/null || true

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$LOG_FILE"; }

# Baca satu kunci dari .env tanpa mengeksekusi isinya (jangan `source`).
env_get() {
  [ -r "$ENV_FILE" ] || return 0
  sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" "$ENV_FILE" \
    | head -1 | tr -d '\r' | sed 's/^["'\'']//; s/["'\'']$//'
}

notify() {
  local text="$1"
  local tok chat
  tok="$(env_get TELEGRAM_BOT_TOKEN)"
  chat="$(env_get TELEGRAM_CHAT_ID)"
  if [ -z "$tok" ] || [ -z "$chat" ]; then
    log "ALERT (telegram dilewati, kredensial tidak ada): $text"
    return 0
  fi
  # --data-urlencode agar isi pesan tidak merusak query string.
  if curl -sS --max-time 15 -o /dev/null -X POST \
      "https://api.telegram.org/bot${tok}/sendMessage" \
      --data-urlencode "chat_id=${chat}" \
      --data-urlencode "text=${text}" >/dev/null 2>&1; then
    log "ALERT terkirim: $text"
  else
    log "ALERT GAGAL dikirim (jaringan Telegram?): $text"
  fi
}

probe() {  # $1=url -> 0 bila 2xx
  local code
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 \
    -H "Host: ${PROBE_HOST}" "$1" 2>/dev/null)"
  [ "$code" = "200" ]
}

read_fails()  { [ -r "$STATE_FILE" ] && cat "$STATE_FILE" 2>/dev/null || echo 0; }
write_fails() { printf '%s\n' "$1" > "$STATE_FILE" 2>/dev/null || true; }

log "watchdog mulai (pid=$$) interval=${INTERVAL}s threshold=${FAIL_THRESHOLD} health=${HEALTH_URL}"

fails="$(read_fails)"
case "$fails" in ''|*[!0-9]*) fails=0 ;; esac
alerted=0

while true; do
  if probe "$HEALTH_URL"; then
    if [ "$fails" -gt 0 ]; then log "PULIH setelah ${fails} kegagalan berturut-turut"; fi
    if [ "$alerted" -eq 1 ]; then notify "✅ Katalir backend PULIH (health 200)"; fi
    fails=0; alerted=0; write_fails 0
  else
    fails=$((fails + 1))
    write_fails "$fails"
    log "GAGAL (${fails}/${FAIL_THRESHOLD}) — ${HEALTH_URL} tidak membalas 200"

    if [ "$fails" -ge "$FAIL_THRESHOLD" ]; then
      log "AMBANG TERLAMPAUI — restart ${BACKEND_UNIT}"
      systemctl restart "$BACKEND_UNIT" >>"$LOG_FILE" 2>&1
      sleep 15
      if probe "$HEALTH_URL"; then
        log "restart backend BERHASIL (health 200)"
        notify "🔧 Katalir: backend di-restart otomatis oleh watchdog dan sudah sehat kembali."
        fails=0; write_fails 0
      else
        log "restart backend TIDAK menyelesaikan masalah — cek ${TUNNEL_UNIT}"
        if ! probe "$PUBLIC_URL"; then
          log "jalur publik juga gagal — restart ${TUNNEL_UNIT}"
          systemctl restart "$TUNNEL_UNIT" >>"$LOG_FILE" 2>&1
          sleep 15
        fi
        if [ "$alerted" -eq 0 ]; then
          notify "🚨 Katalir: backend TIDAK sehat walau sudah di-restart otomatis. Perlu perhatian manual."
          alerted=1
        fi
      fi
    fi
  fi
  sleep "$INTERVAL"
done
