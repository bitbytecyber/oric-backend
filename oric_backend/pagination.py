"""Project-wide DRF pagination with a hard max_limit guard (as sis_backend)."""
from rest_framework.pagination import LimitOffsetPagination


class OricLimitOffsetPagination(LimitOffsetPagination):
    default_limit = 20
    max_limit = 500
