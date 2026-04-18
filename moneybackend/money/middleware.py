from .onec_context import is_onec_sync_request, suppress_outbox_sync


class OneCSyncRequestMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not is_onec_sync_request(request):
            return self.get_response(request)

        with suppress_outbox_sync():
            return self.get_response(request)
