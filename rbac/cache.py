"""Global RBAC version: bumped on any role/capability/assignment change, so every
user's cached abilities payload is invalidated at once (same as sis_backend)."""
from django.core.cache import cache

VERSION_KEY = "rbac:global_version"
ABILITIES_TTL = 3600


def rbac_version() -> int:
    v = cache.get(VERSION_KEY)
    if v is None:
        cache.add(VERSION_KEY, 1, timeout=None)
        v = cache.get(VERSION_KEY) or 1
    return int(v)


def bump_rbac_version() -> None:
    try:
        cache.incr(VERSION_KEY)
    except ValueError:
        cache.set(VERSION_KEY, 2, timeout=None)


def abilities_cache_key(user_id: int) -> str:
    return f"abilities:{user_id}:{rbac_version()}"
