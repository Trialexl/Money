from django.core.paginator import InvalidPage
from django.db.models import Q
from rest_framework.pagination import PageNumberPagination

from .onec_context import is_onec_sync_request


class OneCSyncSoftDeleteCompatibilityMixin:
    """Позволяет 1С-синхронизации обращаться к detail endpoint уже удаленных записей."""

    soft_delete_field = 'deleted'

    def include_soft_deleted_for_onec_detail(self):
        if not is_onec_sync_request(self.request):
            return False

        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        return lookup_url_kwarg in getattr(self, 'kwargs', {})

    def filter_soft_deleted(self, queryset):
        if self.include_soft_deleted_for_onec_detail():
            return queryset
        return queryset.filter(**{self.soft_delete_field: False})


class CatalogPageNumberPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100
    allowed_page_sizes = {20, 50, 100}

    def get_page_size(self, request):
        raw_value = request.query_params.get(self.page_size_query_param)
        if raw_value is None:
            return self.page_size

        try:
            page_size = int(raw_value)
        except (TypeError, ValueError):
            return self.page_size

        if page_size not in self.allowed_page_sizes:
            return self.page_size
        return page_size

    def paginate_queryset(self, queryset, request, view=None):
        self.request = request
        page_size = self.get_page_size(request)
        if not page_size:
            return None

        paginator = self.django_paginator_class(queryset, page_size)
        page_number = request.query_params.get(self.page_query_param, 1)

        if page_number in self.last_page_strings:
            page_number = paginator.num_pages

        try:
            self.page = paginator.page(page_number)
        except InvalidPage:
            fallback_page = paginator.num_pages or 1
            self.page = paginator.page(fallback_page)

        if paginator.num_pages > 1 and self.template is not None:
            self.display_page_controls = True

        return list(self.page)


class FinancialOperationListFilteringMixin:
    list_query_serializer_class = None
    search_fields = ()

    def get_list_filters(self):
        serializer_class = self.list_query_serializer_class
        if serializer_class is None:
            return {}

        serializer = serializer_class(data=self.request.query_params)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data

    def apply_search_filter(self, queryset, search):
        if not search or not self.search_fields:
            return queryset

        search_variants = {
            search,
            search.lower(),
            search.upper(),
            search.capitalize(),
            search.title(),
        }
        conditions = Q()
        for field_name in self.search_fields:
            for search_variant in search_variants:
                conditions |= Q(**{f'{field_name}__icontains': search_variant})
        return queryset.filter(conditions)
