#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
SUDO="${SUDO:-sudo}"

if [ "$(id -u)" -eq 0 ]; then
  SUDO=""
fi

cd "$APP_DIR"

if [ ! -f "docker-compose.yml" ]; then
  echo "ERROR: docker-compose.yml was not found in $APP_DIR" >&2
  exit 1
fi

if ! command -v git >/dev/null 2>&1; then
  echo "ERROR: git is not installed" >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker is not installed" >&2
  exit 1
fi

if [ ! -f ".env" ]; then
  echo "ERROR: .env was not found. Create it from .env.example before deploy." >&2
  exit 1
fi

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "ERROR: local tracked files have changes. Commit, stash, or revert them before update." >&2
  git status --short
  exit 1
fi

run_git_pull() {
  if [ -w "$APP_DIR/.git" ]; then
    git pull --ff-only
  else
    $SUDO git pull --ff-only
  fi
}

run_docker() {
  $SUDO docker "$@"
}

echo "==> Updating repository"
run_git_pull

echo "==> Pulling Docker images"
run_docker compose pull

echo "==> Starting services"
run_docker compose up -d --remove-orphans

echo "==> Pruning dangling Docker images"
run_docker image prune -f

echo "==> Current services"
run_docker compose ps

echo "==> Update finished"
