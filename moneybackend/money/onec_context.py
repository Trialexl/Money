from contextlib import contextmanager
from contextvars import ContextVar


ONEC_SYNC_HEADER_META = 'HTTP_X_ONEC_SYNC'
_outbox_sync_suppressed = ContextVar('money_outbox_sync_suppressed', default=False)


def is_outbox_sync_suppressed():
    return _outbox_sync_suppressed.get()


@contextmanager
def suppress_outbox_sync():
    token = _outbox_sync_suppressed.set(True)
    try:
        yield
    finally:
        _outbox_sync_suppressed.reset(token)


def is_onec_sync_request(request):
    header_value = str(request.META.get(ONEC_SYNC_HEADER_META, '')).strip().lower()
    return header_value in {'1', 'true', 'yes', 'on'}
