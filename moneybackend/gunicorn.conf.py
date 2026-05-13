import multiprocessing
import os


def env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


bind = os.environ.get('GUNICORN_BIND', '0.0.0.0:8000')
worker_class = os.environ.get('GUNICORN_WORKER_CLASS', 'gthread')
workers = env_int('GUNICORN_WORKERS', min(max(multiprocessing.cpu_count(), 1), 2))
threads = env_int('GUNICORN_THREADS', 2)
timeout = env_int('GUNICORN_TIMEOUT', 180)
graceful_timeout = env_int('GUNICORN_GRACEFUL_TIMEOUT', 30)
keepalive = env_int('GUNICORN_KEEPALIVE', 5)
max_requests = env_int('GUNICORN_MAX_REQUESTS', 500)
max_requests_jitter = env_int('GUNICORN_MAX_REQUESTS_JITTER', 50)
worker_tmp_dir = os.environ.get('GUNICORN_WORKER_TMP_DIR', '/dev/shm')
accesslog = os.environ.get('GUNICORN_ACCESS_LOG', '-')
errorlog = os.environ.get('GUNICORN_ERROR_LOG', '-')
loglevel = os.environ.get('GUNICORN_LOG_LEVEL', 'info')
