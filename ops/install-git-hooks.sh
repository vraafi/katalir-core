#!/usr/bin/env bash
# Pasang git hooks versi-repo (`.githooks/`) ke repo ini.
#
# KENAPA: hook di `.git/hooks/` TIDAK ikut ter-commit, jadi tidak bisa
# melindungi siapa pun selain mesin yang memasangnya. Dengan
# `core.hooksPath=.githooks`, hook-nya ikut repo dan bisa di-review/di-update.
#
# Pakai (dari root repo):
#   bash ops/install-git-hooks.sh
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

if [ ! -d .githooks ]; then
  echo "FATAL: .githooks/ tidak ada" >&2
  exit 1
fi

chmod +x .githooks/* 2>/dev/null || true
git config core.hooksPath .githooks

echo "OK: core.hooksPath -> .githooks"
echo "Hook aktif:"
ls -1 .githooks | sed 's/^/  - /'
echo
echo "Uji cepat:"
git hook run pre-commit 2>/dev/null || node nexus-frontend/scripts/check-api-url-csp.mjs
