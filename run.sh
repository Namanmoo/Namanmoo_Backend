#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# NaManMoo 무기 생성 API 실행.
#
#   ./run.sh          개발 모드 (코드 변경 시 자동 재시작)
#   ./run.sh --test   pytest 실행
#
# .env 가 있으면 자동으로 읽는다. GEMINI_API_KEY 가 없으면 목 모드로 뜬다.
# 포트 변경: PORT=9000 ./run.sh
# ─────────────────────────────────────────────────────────────
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
PY="$ROOT/.venv/bin/python"

if [ ! -x "$PY" ]; then
  echo "가상환경이 없습니다. 먼저 준비하세요:" >&2
  echo "  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT/.env"
  set +a
  echo ".env 로드됨"
fi

if [ "${1:-}" = "--test" ]; then
  exec "$PY" -m pytest -q
fi

PORT="${PORT:-8790}"
HOST="${HOST:-127.0.0.1}"

if [ -z "${GEMINI_API_KEY:-}" ]; then
  echo "GEMINI_API_KEY 없음 — 목 모드로 뜹니다 (응답 형태는 동일)."
fi

echo "http://$HOST:$PORT  (문서: /docs, 상태: /healthz)"
exec "$PY" -m uvicorn app.main:app --host "$HOST" --port "$PORT" --reload --app-dir "$ROOT"
