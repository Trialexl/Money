#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
BACKUP_DIR="${BACKUP_DIR:-$APP_DIR/backups/postgres}"
BACKUP_LOG_DIR="${BACKUP_LOG_DIR:-$APP_DIR/backups/logs}"
BACKUP_EVENTS_LOG="${BACKUP_EVENTS_LOG:-$BACKUP_LOG_DIR/backup-events.log}"
BACKUP_MIN_BYTES="${BACKUP_MIN_BYTES:-1024}"
BACKUP_UPLOAD_AFTER_CREATE="${BACKUP_UPLOAD_AFTER_CREATE:-true}"
BACKUP_REMOTE_DIR="${BACKUP_REMOTE_DIR:-}"
BACKUP_RCLONE_REMOTE="${BACKUP_RCLONE_REMOTE:-}"
BACKUP_RSYNC_TARGET="${BACKUP_RSYNC_TARGET:-}"
BACKUP_SCP_TARGET="${BACKUP_SCP_TARGET:-}"
BACKUP_ALERT_WEBHOOK_URL="${BACKUP_ALERT_WEBHOOK_URL:-}"
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
  ./backup-db.sh status
  ./backup-db.sh sync [backup-file|latest]
  ./backup-db.sh restore-check [backup-file|latest]
  ./backup-db.sh restore <backup-file>
  ./backup-db.sh cleanup [days]

Commands:
  backup          Create compressed PostgreSQL custom dump in backups/postgres/.
  list            Show local backup files.
  status          Show latest backup and recent backup/restore-check events.
  sync FILE       Upload selected backup to configured off-server storage.
  restore-check   Restore selected backup into a temporary DB and drop it after check.
  restore FILE    Restore selected .dump.gz or .sql.gz file after explicit confirmation.
  cleanup [days]  Delete only local backup files older than N days. Default: 30.

Safety:
  This script never removes Docker volumes and never runs docker system prune --volumes.
  restore-check uses a temporary database and does not overwrite the current database.

Off-server upload env, choose exactly one:
  BACKUP_REMOTE_DIR=/mnt/backup/money
  BACKUP_RCLONE_REMOTE=remote:money/postgres
  BACKUP_RSYNC_TARGET=user@backup-host:/srv/backups/money
  BACKUP_SCP_TARGET=user@backup-host:/srv/backups/money
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

is_truthy() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

append_journal() {
  local action="$1"
  local status="$2"
  local file="${3:-}"
  local message="${4:-}"
  local size="-"

  mkdir -p "$BACKUP_LOG_DIR"
  if [ -n "$file" ] && [ -f "$file" ]; then
    size="$(wc -c < "$file" | tr -d ' ')"
  fi

  printf '%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$(date -Iseconds)" \
    "$action" \
    "$status" \
    "$size" \
    "$file" \
    "$message" >> "$BACKUP_EVENTS_LOG"
}

notify_failure() {
  local message="$1"

  if [ -z "$BACKUP_ALERT_WEBHOOK_URL" ]; then
    return
  fi

  if command -v curl >/dev/null 2>&1; then
    curl -fsS \
      -H "Content-Type: application/json" \
      -d "{\"text\":\"${message//\"/\\\"}\"}" \
      "$BACKUP_ALERT_WEBHOOK_URL" >/dev/null || true
  fi
}

fail_command() {
  local action="$1"
  local message="$2"
  local file="${3:-}"

  append_journal "$action" "error" "$file" "$message"
  notify_failure "Money backup ${action} failed: ${message}"
  echo "ERROR: $message" >&2
  exit 1
}

validate_backup_file() {
  local file="$1"
  local size

  case "$file" in
    *.dump.gz|*.sql.gz) ;;
    *)
      fail_command "verify" "supported backup files are .dump.gz and .sql.gz" "$file"
      ;;
  esac

  gzip -t "$file" || fail_command "verify" "gzip integrity check failed" "$file"

  size="$(wc -c < "$file" | tr -d ' ')"
  if ! [[ "$BACKUP_MIN_BYTES" =~ ^[0-9]+$ ]]; then
    fail_command "verify" "BACKUP_MIN_BYTES must be a non-negative integer" "$file"
  fi
  if [ "$size" -lt "$BACKUP_MIN_BYTES" ]; then
    fail_command "verify" "backup is too small: ${size} bytes, minimum is ${BACKUP_MIN_BYTES}" "$file"
  fi

  if [[ "$file" == *.dump.gz ]]; then
    gzip -dc "$file" | run_docker compose exec -T db sh -c 'pg_restore --list >/dev/null' \
      || fail_command "verify" "pg_restore cannot read custom dump" "$file"
  fi
}

latest_backup() {
  if [ ! -d "$BACKUP_DIR" ]; then
    return 1
  fi

  find "$BACKUP_DIR" -maxdepth 1 -type f \( -name '*.dump.gz' -o -name '*.sql.gz' \) -print | sort | tail -n 1
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
    validate_backup_file "$target"
    echo "Backup created: $target"
    append_journal "backup" "ok" "$target" "created"
    if is_truthy "$BACKUP_UPLOAD_AFTER_CREATE" && has_remote_target; then
      sync_backup "$target"
    fi
  else
    rm -f "$tmp"
    fail_command "backup" "pg_dump failed" "$target"
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
  if [ "$requested" = "latest" ]; then
    local latest
    latest="$(latest_backup || true)"
    if [ -n "$latest" ]; then
      printf '%s\n' "$latest"
      return
    fi
    echo "ERROR: no backup files found in $BACKUP_DIR" >&2
    exit 1
  fi
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

has_remote_target() {
  [ -n "$BACKUP_REMOTE_DIR" ] || [ -n "$BACKUP_RCLONE_REMOTE" ] || [ -n "$BACKUP_RSYNC_TARGET" ] || [ -n "$BACKUP_SCP_TARGET" ]
}

sync_backup() {
  local file="${1:-latest}"
  file="$(resolve_backup_file "$file")"
  validate_backup_file "$file"

  local configured=0
  [ -n "$BACKUP_REMOTE_DIR" ] && configured=$((configured + 1))
  [ -n "$BACKUP_RCLONE_REMOTE" ] && configured=$((configured + 1))
  [ -n "$BACKUP_RSYNC_TARGET" ] && configured=$((configured + 1))
  [ -n "$BACKUP_SCP_TARGET" ] && configured=$((configured + 1))

  if [ "$configured" -eq 0 ]; then
    fail_command "sync" "no off-server target configured" "$file"
  fi
  if [ "$configured" -gt 1 ]; then
    fail_command "sync" "configure only one off-server target" "$file"
  fi

  echo "==> Uploading backup off-server"
  if [ -n "$BACKUP_REMOTE_DIR" ]; then
    mkdir -p "$BACKUP_REMOTE_DIR"
    cp -p "$file" "$BACKUP_REMOTE_DIR/" \
      || fail_command "sync" "copy to BACKUP_REMOTE_DIR failed" "$file"
  elif [ -n "$BACKUP_RCLONE_REMOTE" ]; then
    command -v rclone >/dev/null 2>&1 || fail_command "sync" "rclone is not installed" "$file"
    rclone copy "$file" "$BACKUP_RCLONE_REMOTE" \
      || fail_command "sync" "rclone copy failed" "$file"
  elif [ -n "$BACKUP_RSYNC_TARGET" ]; then
    command -v rsync >/dev/null 2>&1 || fail_command "sync" "rsync is not installed" "$file"
    rsync -a "$file" "$BACKUP_RSYNC_TARGET/" \
      || fail_command "sync" "rsync upload failed" "$file"
  elif [ -n "$BACKUP_SCP_TARGET" ]; then
    command -v scp >/dev/null 2>&1 || fail_command "sync" "scp is not installed" "$file"
    scp -p "$file" "$BACKUP_SCP_TARGET/" \
      || fail_command "sync" "scp upload failed" "$file"
  fi

  append_journal "sync" "ok" "$file" "uploaded"
  echo "Upload finished."
}

restore_check() {
  require_stack

  local file="${1:-latest}"
  file="$(resolve_backup_file "$file")"
  validate_backup_file "$file"

  local temp_db
  temp_db="money_restore_check_$(date +%Y%m%d_%H%M%S)_$$"

  cleanup_restore_check() {
    run_docker compose exec -T db sh -c 'dropdb --if-exists -U "$POSTGRES_USER" "$1"' sh "$temp_db" >/dev/null 2>&1 || true
  }
  trap cleanup_restore_check EXIT

  echo "==> Checking restore in temporary database: $temp_db"
  run_docker compose exec -T db sh -c 'createdb -U "$POSTGRES_USER" "$1"' sh "$temp_db" \
    || fail_command "restore-check" "temporary database creation failed" "$file"

  case "$file" in
    *.dump.gz)
      gzip -dc "$file" | run_docker compose exec -T db sh -c 'pg_restore --exit-on-error --no-owner --no-acl -U "$POSTGRES_USER" -d "$1"' sh "$temp_db" \
        || fail_command "restore-check" "pg_restore into temporary database failed" "$file"
      ;;
    *.sql.gz)
      gzip -dc "$file" | run_docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1"' sh "$temp_db" \
        || fail_command "restore-check" "psql restore into temporary database failed" "$file"
      ;;
  esac

  run_docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1" -c "select count(*) from django_migrations;" >/dev/null' sh "$temp_db" \
    || fail_command "restore-check" "restored database smoke query failed" "$file"

  cleanup_restore_check
  trap - EXIT
  append_journal "restore-check" "ok" "$file" "temporary database restored"
  echo "Restore-check finished."
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
  validate_backup_file "$file"
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
      gzip -dc "$file" | run_docker compose exec -T db sh -c 'pg_restore --clean --if-exists --no-owner --no-acl -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
        || fail_command "restore" "pg_restore into current database failed" "$file"
      ;;
    *.sql.gz)
      gzip -dc "$file" | run_docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
        || fail_command "restore" "psql restore into current database failed" "$file"
      ;;
  esac
  append_journal "restore" "ok" "$file" "current database restored"
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
  append_journal "cleanup" "ok" "" "older than ${days} days"
  echo "Cleanup finished."
}

show_status() {
  local latest
  latest="$(latest_backup || true)"

  if [ -n "$latest" ]; then
    echo "Latest backup:"
    ls -lh "$latest"
  else
    echo "Latest backup: none"
  fi

  echo
  echo "Recent events:"
  if [ -f "$BACKUP_EVENTS_LOG" ]; then
    tail -n 20 "$BACKUP_EVENTS_LOG"
  else
    echo "No journal yet: $BACKUP_EVENTS_LOG"
  fi
}

command="${1:-help}"
case "$command" in
  backup)
    create_backup
    ;;
  list)
    list_backups
    ;;
  status)
    show_status
    ;;
  sync)
    sync_backup "${2:-latest}"
    ;;
  restore-check)
    restore_check "${2:-latest}"
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
