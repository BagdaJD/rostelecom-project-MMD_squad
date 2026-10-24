#!/usr/bin/env bash
# Прокси к npm для окружений без системного Node.js.
# Использует node из nodejs-bin (venv .venv-docs), если обычного npm нет в PATH.
set -euo pipefail

if command -v npm >/dev/null 2>&1; then
  exec npm "$@"
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
NB="$(ls -d "$ROOT"/.venv-docs/lib*/python*/site-packages/nodejs 2>/dev/null | head -1 || true)"

if [[ -z "$NB" || ! -x "$NB/bin/node" ]]; then
  echo "node не найден. Установите Node.js 20+ или: .venv-docs/bin/pip install nodejs-bin" >&2
  exit 127
fi

exec "$NB/bin/node" "$NB/lib/node_modules/npm/bin/npm-cli.js" "$@"
