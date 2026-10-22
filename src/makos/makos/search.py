"""Compatibility facade: the old local-only helpers, now implemented by the `makos.seek` package."""
from pathlib import Path

from .catalog import APPS  # noqa: F401
from .seek import providers
from .seek.units import calculate, convert  # noqa: F401


def applications(query):
    q = query.casefold().strip()
    return [a for a in APPS if q in a.name.casefold()]


def documents(query, home=None, limit=30):
    """Bounded file-name search (at most 500 directories under the visible user folders); never follows links or reads hidden folders."""
    return [Path(r.path) for r in providers.walk_fallback(query, home, limit)]
