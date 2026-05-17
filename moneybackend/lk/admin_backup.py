import gzip
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone


class BackupError(RuntimeError):
    pass


@dataclass(frozen=True)
class BackupFile:
    name: str
    path: Path
    size: int
    created_at: datetime


def _backup_dir() -> Path:
    path = Path(settings.BACKUP_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _backup_log_dir() -> Path:
    path = Path(settings.BACKUP_LOG_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _journal_path() -> Path:
    return _backup_log_dir() / 'backup-events.log'


def _append_journal(action: str, status: str, file_path: Path | None = None, message: str = '') -> None:
    size = '-'
    file_name = ''
    if file_path and file_path.exists():
        size = str(file_path.stat().st_size)
        file_name = str(file_path)

    with _journal_path().open('a', encoding='utf-8') as journal:
        journal.write(
            f'{timezone.now().isoformat()}\t{action}\t{status}\t{size}\t{file_name}\t{message}\n'
        )


def _database_settings() -> dict:
    database = settings.DATABASES['default']
    if database.get('ENGINE') != 'django.db.backends.postgresql':
        raise BackupError('Backup через админку поддерживает только PostgreSQL.')
    return database


def _pg_env(database: dict) -> dict:
    env = os.environ.copy()
    password = database.get('PASSWORD') or ''
    if password:
        env['PGPASSWORD'] = str(password)
    return env


def _pg_common_args(database: dict) -> list[str]:
    args: list[str] = []
    host = database.get('HOST')
    port = database.get('PORT')
    user = database.get('USER')
    if host:
        args.extend(['--host', str(host)])
    if port:
        args.extend(['--port', str(port)])
    if user:
        args.extend(['--username', str(user)])
    return args


def _run_checked(args: list[str], *, database: dict, stdin=None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            args,
            stdin=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_pg_env(database),
            check=True,
            text=False,
        )
    except FileNotFoundError as exc:
        raise BackupError(f'Не найдена утилита {args[0]}. Проверь postgresql-client в backend image.') from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode('utf-8', errors='replace') if exc.stderr else ''
        raise BackupError(stderr.strip() or f'Команда {args[0]} завершилась с ошибкой.') from exc


def _validate_backup_file(file_path: Path) -> None:
    if file_path.suffixes[-2:] != ['.dump', '.gz'] and file_path.suffixes[-2:] != ['.sql', '.gz']:
        raise BackupError('Поддерживаются только .dump.gz и .sql.gz backup-файлы.')

    size = file_path.stat().st_size
    if size < settings.BACKUP_MIN_BYTES:
        raise BackupError(f'Backup слишком маленький: {size} байт.')

    try:
        with gzip.open(file_path, 'rb') as archive:
            while archive.read(1024 * 1024):
                pass
    except OSError as exc:
        raise BackupError('gzip-проверка backup-файла не прошла.') from exc


def _safe_backup_file(filename: str) -> Path:
    if filename != Path(filename).name:
        raise Http404('Invalid backup file name')
    file_path = _backup_dir() / filename
    if not file_path.exists() or not file_path.is_file():
        raise Http404('Backup file not found')
    _validate_backup_file(file_path)
    return file_path


def list_backup_files() -> list[BackupFile]:
    result: list[BackupFile] = []
    for file_path in sorted(_backup_dir().glob('*.gz'), reverse=True):
        if file_path.suffixes[-2:] not in (['.dump', '.gz'], ['.sql', '.gz']):
            continue
        stat = file_path.stat()
        result.append(
            BackupFile(
                name=file_path.name,
                path=file_path,
                size=stat.st_size,
                created_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.get_current_timezone()),
            )
        )
    return result


def _sync_backup(file_path: Path) -> str:
    targets = [
        ('BACKUP_REMOTE_DIR', settings.BACKUP_REMOTE_DIR),
        ('BACKUP_RCLONE_REMOTE', settings.BACKUP_RCLONE_REMOTE),
        ('BACKUP_RSYNC_TARGET', settings.BACKUP_RSYNC_TARGET),
        ('BACKUP_SCP_TARGET', settings.BACKUP_SCP_TARGET),
    ]
    configured = [(name, value) for name, value in targets if value]
    if not configured:
        return ''
    if len(configured) > 1:
        raise BackupError('Настрой только один внешний target для backup.')

    name, value = configured[0]
    if name == 'BACKUP_REMOTE_DIR':
        remote_dir = Path(value)
        remote_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_path, remote_dir / file_path.name)
    elif name == 'BACKUP_RCLONE_REMOTE':
        _run_checked(['rclone', 'copy', str(file_path), value], database=_database_settings())
    elif name == 'BACKUP_RSYNC_TARGET':
        _run_checked(['rsync', '-a', str(file_path), f'{value}/'], database=_database_settings())
    elif name == 'BACKUP_SCP_TARGET':
        _run_checked(['scp', '-p', str(file_path), f'{value}/'], database=_database_settings())

    _append_journal('sync', 'ok', file_path, name)
    return name


def create_database_backup() -> BackupFile:
    database = _database_settings()
    db_name = database.get('NAME')
    if not db_name:
        raise BackupError('Не указано имя PostgreSQL базы.')

    timestamp = timezone.localtime().strftime('%Y%m%d-%H%M%S')
    target = _backup_dir() / f'money-postgres-{timestamp}.dump.gz'
    tmp = target.with_suffix(target.suffix + '.tmp')
    command = [
        'pg_dump',
        '--format=custom',
        '--no-owner',
        '--no-acl',
        *_pg_common_args(database),
        str(db_name),
    ]

    try:
        with gzip.open(tmp, 'wb') as archive:
            process = subprocess.run(
                command,
                stdout=archive,
                stderr=subprocess.PIPE,
                env=_pg_env(database),
                check=False,
            )
        if process.returncode != 0:
            stderr = process.stderr.decode('utf-8', errors='replace') if process.stderr else ''
            raise BackupError(stderr.strip() or 'pg_dump завершился с ошибкой.')

        tmp.replace(target)
        _validate_backup_file(target)
        synced_to = ''
        if settings.BACKUP_UPLOAD_AFTER_CREATE:
            synced_to = _sync_backup(target)
        _append_journal('backup', 'ok', target, f'created {synced_to}'.strip())
        return list_backup_files()[0]
    except Exception:
        tmp.unlink(missing_ok=True)
        if target.exists():
            target.unlink()
        raise


def restore_check_backup(filename: str) -> None:
    file_path = _safe_backup_file(filename)
    database = _database_settings()
    temp_db = f'money_restore_check_{timezone.localtime().strftime("%Y%m%d_%H%M%S")}_{os.getpid()}'
    common_args = _pg_common_args(database)

    try:
        _run_checked(['createdb', *common_args, temp_db], database=database)
        with gzip.open(file_path, 'rb') as archive:
            if file_path.suffixes[-2:] == ['.dump', '.gz']:
                _run_checked(
                    ['pg_restore', '--exit-on-error', '--no-owner', '--no-acl', *common_args, '--dbname', temp_db],
                    database=database,
                    stdin=archive,
                )
            else:
                _run_checked(
                    ['psql', '-v', 'ON_ERROR_STOP=1', *common_args, '--dbname', temp_db],
                    database=database,
                    stdin=archive,
                )
        _run_checked(
            ['psql', '-v', 'ON_ERROR_STOP=1', *common_args, '--dbname', temp_db, '-c', 'select count(*) from django_migrations;'],
            database=database,
        )
        _append_journal('restore-check', 'ok', file_path, 'temporary database restored')
    except Exception as exc:
        _append_journal('restore-check', 'error', file_path, str(exc))
        raise
    finally:
        subprocess.run(
            ['dropdb', '--if-exists', *common_args, temp_db],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=_pg_env(database),
            check=False,
        )


def backup_admin_view(request):
    if not request.user.is_superuser:
        raise PermissionDenied

    if request.method == 'POST':
        action = request.POST.get('action')
        try:
            if action == 'create':
                backup = create_database_backup()
                messages.success(request, f'Backup создан: {backup.name}')
            elif action == 'restore-check':
                filename = request.POST.get('filename', '')
                restore_check_backup(filename)
                messages.success(request, f'Restore-check прошел: {filename}')
            else:
                messages.error(request, 'Неизвестное действие.')
        except BackupError as exc:
            messages.error(request, str(exc))
        return redirect('admin:database_backup')

    context = {
        **admin.site.each_context(request),
        'title': 'Backup базы',
        'backups': list_backup_files(),
        'journal_path': _journal_path(),
        'backup_dir': _backup_dir(),
        'has_remote_target': any([
            settings.BACKUP_REMOTE_DIR,
            settings.BACKUP_RCLONE_REMOTE,
            settings.BACKUP_RSYNC_TARGET,
            settings.BACKUP_SCP_TARGET,
        ]),
    }
    return TemplateResponse(request, 'admin/database_backups.html', context)


def backup_download_view(request, filename: str):
    if not request.user.is_superuser:
        raise PermissionDenied

    file_path = _safe_backup_file(filename)
    return FileResponse(file_path.open('rb'), as_attachment=True, filename=file_path.name)


def install_admin_backup(site: admin.AdminSite) -> None:
    if getattr(site, '_money_database_backup_installed', False):
        return

    original_get_urls = site.get_urls
    original_get_app_list = site.get_app_list

    def get_urls():
        custom_urls = [
            path('db-backups/', site.admin_view(backup_admin_view), name='database_backup'),
            path('db-backups/<str:filename>/download/', site.admin_view(backup_download_view), name='database_backup_download'),
        ]
        return custom_urls + original_get_urls()

    def get_app_list(request, app_label=None):
        app_list = original_get_app_list(request, app_label)
        if request.user.is_superuser:
            app_list.append({
                'name': 'Обслуживание',
                'app_label': 'maintenance',
                'app_url': '',
                'has_module_perms': True,
                'models': [{
                    'name': 'Backup базы',
                    'object_name': 'DatabaseBackup',
                    'perms': {'view': True},
                    'admin_url': reverse('admin:database_backup'),
                    'add_url': None,
                    'view_only': True,
                }],
            })
        return app_list

    site.get_urls = get_urls
    site.get_app_list = get_app_list
    site._money_database_backup_installed = True
