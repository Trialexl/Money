#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
BACKUP_DIR="${BACKUP_DIR:-$APP_DIR/backups/postgres}"
SUDO="${SUDO:-sudo}"

if [ "$(id -u)" -eq 0 ]; then
  SUDO=""
fi

cd "$APP_DIR"

usage() {
  cat <<'USAGE'
Usage:
  ./backup-db.sh backup
  ./backup-db.sh list
  ./backup-db.sh restore <backup-file>
  ./backup-db.sh cleanup [days]

Commands:
  backup          Create compressed PostgreSQL custom dump in backups/postgres/.
  list            Show local backup files.
  restore FILE    Restore selected .dump.gz or .sql.gz file after explicit confirmation.
  cleanup [days]  Delete only local backup files older than N days. Default: 30.

Safety:
  This script never removes Docker volumes and never runs docker system prune --volumes.
USAGE
}

run_docker() {
  $SUDO docker "$@"
}

require_stack() {
  if [ ! -f "docker-compose.yml" ]; then
    echo "ERROR: docker-compose.yml was not found in $APP_DIR" >&2
    exit 1
  fi
  if ! command -v docker >/dev/null 2>&1; then
    echo "ERROR: docker is not installed" >&2
    exit 1
  fi
}

create_backup() {
  require_stack
  mkdir -p "$BACKUP_DIR"

  local timestamp target tmp
  timestamp="$(date +%Y%m%d-%H%M%S)"
  target="$BACKUP_DIR/money-postgres-$timestamp.dump.gz"
  tmp="$target.tmp"

  echo "==> Creating PostgreSQL backup"
  if run_docker compose exec -T db sh -c 'pg_dump --format=custom --no-owner --no-acl -U "$POSTGRES_USER" -d "$POSTGRES_DB"' | gzip -c > "$tmp"; then
    mv "$tmp" "$target"
    gzip -t "$target"
    echo "Backup created: $target"
  else
    rm -f "$tmp"
    echo "ERROR: backup failed" >&2
    exit 1
  fi
}

list_backups() {
  if [ ! -d "$BACKUP_DIR" ]; then
    echo "No backup directory: $BACKUP_DIR"
    return
  fi

  find "$BACKUP_DIR" -maxdepth 1 -type f \( -name '*.dump.gz' -o -name '*.sql.gz' \) -print | sort
}

resolve_backup_file() {
  local requested="$1"
  if [ -f "$requested" ]; then
    printf '%s\n' "$requested"
    return
  fi
  if [ -f "$BACKUP_DIR/$requested" ]; then
    printf '%s\n' "$BACKUP_DIR/$requested"
    return
  fi
  echo "ERROR: backup file not found: $requested" >&2
  exit 1
}

restore_backup() {
  require_stack
  if [ "${1:-}" = "" ]; then
    echo "ERROR: restore requires backup file path or file name" >&2
    usage
    exit 1
  fi

  local file confirmation
  file="$(resolve_backup_file "$1")"
  case "$file" in
    *.dump.gz|*.sql.gz) ;;
    *)
      echo "ERROR: supported restore files are .dump.gz and .sql.gz" >&2
      exit 1
      ;;
  esac

  gzip -t "$file"
  echo "Restore file: $file"
  echo "This will overwrite objects in the current PostgreSQL database."
  read -r -p "Type RESTORE to continue: " confirmation
  if [ "$confirmation" != "RESTORE" ]; then
    echo "Restore cancelled."
    exit 0
  fi

  echo "==> Restoring PostgreSQL backup"
  case "$file" in
    *.dump.gz)
      gzip -dc "$file" | run_docker compose exec -T db sh -c 'pg_restore --clean --if-exists --no-owner --no-acl -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
      ;;
    *.sql.gz)
      gzip -dc "$file" | run_docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
      ;;
  esac
  echo "Restore finished."
}

cleanup_backups() {
  local days="${1:-${BACKUP_RETENTION_DAYS:-30}}"
  if ! [[ "$days" =~ ^[0-9]+$ ]]; then
    echo "ERROR: days must be a non-negative integer" >&2
    exit 1
  fi
  if [ ! -d "$BACKUP_DIR" ]; then
    echo "No backup directory: $BACKUP_DIR"
    return
  fi

  echo "==> Deleting backup files older than $days days from $BACKUP_DIR"
  find "$BACKUP_DIR" -maxdepth 1 -type f \( -name '*.dump.gz' -o -name '*.sql.gz' \) -mtime +"$days" -print -delete
  echo "Cleanup finished."
}

command="${1:-help}"
case "$command" in
  backup)
    create_backup
    ;;
  list)
    list_backups
    ;;
  restore)
    restore_backup "${2:-}"
    ;;
  cleanup)
    cleanup_backups "${2:-}"
    ;;
  help|-h|--help)
    usage
    ;;
  *)
    echo "ERROR: unknown command: $command" >&2
    usage
    exit 1
    ;;
esac
