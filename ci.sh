#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/moneybackend"
FRONTEND_DIR="$ROOT_DIR/frontmoney"
OPENAPI_TMP_DIR=""
CREATED_ROOT_ENV=0

cleanup() {
  if [[ -n "$OPENAPI_TMP_DIR" ]]; then
    rm -rf "$OPENAPI_TMP_DIR"
  fi
  if [[ "$CREATED_ROOT_ENV" == "1" ]]; then
    rm -f "$ROOT_DIR/.env"
  fi
}
trap cleanup EXIT

step() {
  printf '\n==> %s\n' "$1"
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'Missing required command: %s\n' "$1" >&2
    exit 1
  fi
}

if [[ -n "${BACKEND_PYTHON:-}" ]]; then
  PYTHON_BIN="$BACKEND_PYTHON"
elif [[ -x "$BACKEND_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$BACKEND_DIR/.venv/bin/python"
else
  PYTHON_BIN="$(command -v python3 || true)"
fi

if [[ -z "${PYTHON_BIN:-}" ]]; then
  printf 'Missing Python runtime. Set BACKEND_PYTHON or create moneybackend/.venv.\n' >&2
  exit 1
fi

require_cmd npm
require_cmd docker

if [[ "${CI_INSTALL_DEPS:-0}" == "1" ]]; then
  step "Install frontend dependencies"
  (cd "$FRONTEND_DIR" && npm ci)
fi

export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-lk.test_settings}"
export NEXT_PUBLIC_API_URL="${NEXT_PUBLIC_API_URL:-/api/v1}"

step "Backend system check"
(cd "$BACKEND_DIR" && "$PYTHON_BIN" manage.py check)

step "Backend migration drift check"
(cd "$BACKEND_DIR" && "$PYTHON_BIN" manage.py makemigrations --check --dry-run)

step "Backend OpenAPI schema smoke"
OPENAPI_TMP_DIR="$(mktemp -d)"
(cd "$BACKEND_DIR" && "$PYTHON_BIN" manage.py spectacular --file "$OPENAPI_TMP_DIR/openapi.yaml" --validate)

step "Backend tests"
(cd "$BACKEND_DIR" && "$PYTHON_BIN" manage.py test --noinput)

step "Frontend typecheck"
(cd "$FRONTEND_DIR" && npm exec tsc -- --noEmit)

step "Frontend tests"
(cd "$FRONTEND_DIR" && npm test)

step "Frontend production build"
(cd "$FRONTEND_DIR" && npm run build)

step "Docker Compose config"
if [[ ! -f "$ROOT_DIR/.env" ]]; then
  cp "$ROOT_DIR/.env.example" "$ROOT_DIR/.env"
  CREATED_ROOT_ENV=1
fi
(cd "$ROOT_DIR" && docker compose config >/dev/null)

step "CI checks completed"
