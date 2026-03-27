"""CLI scaffolding helpers shared across metadata browser projects."""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime

from loguru import logger


def configure_logging(verbose: bool) -> None:
    """Standard loguru setup: debug to stderr if verbose, else warnings only."""
    logger.remove()
    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        level="DEBUG" if verbose else "WARNING",
    )


def resolve_entity_type(
    args: argparse.Namespace, types: list[str],
) -> tuple[str | None, str | None]:
    """Extract (entity_type, name_query) from parsed args.

    Returns ``(None, None)`` if no entity type flag was given.
    """
    for t in types:
        value = getattr(args, t, None)
        if value is not None:
            name = value if value is not True else None
            return (t, name)
    return (None, None)


def strip_internal_keys(obj):
    """Remove keys starting with '_' (binary data, internal fields) for JSON output."""
    if isinstance(obj, dict):
        return {
            k: strip_internal_keys(v) for k, v in obj.items() if not k.startswith("_")
        }
    if isinstance(obj, list):
        return [strip_internal_keys(item) for item in obj]
    return obj


def page_fetcher(fetch, first_page=None):
    """Adapt a page-number API to ``browse()``'s offset-based interface.

    Wraps ``fetch(page_number) -> (results, has_more)`` into
    ``fetch_page(start, count) -> (results, total)``.

    The total is estimated progressively — it reports one extra page
    when ``has_more`` is True, and self-corrects as pages are fetched.

    Pass ``first_page=(results, has_more)`` to seed page 1 from a
    pre-fetched result (avoids a redundant API call on the first page).
    """
    cache: dict[int, tuple[list, bool]] = {}
    if first_page is not None:
        cache[1] = first_page

    def adapted(start, count):
        page = start // count + 1
        if page not in cache:
            cache[page] = fetch(page)
        results, has_more = cache[page]
        total = start + len(results) + (count if has_more else 0)
        return results, total

    return adapted


def list_fetcher(items: list):
    """Wrap a pre-fetched list into a ``fetch_page(start, count)`` callable.

    Returns a function compatible with ``BaseNavigator.browse()``::

        navigator.browse(fetch_page=list_fetcher(my_items))
    """
    def fetch_page(start, count):
        return items[start : start + count], len(items)
    return fetch_page


def parse_date(date_str: str) -> date | None:
    """Parse a 'YYYY-MM-DD' string to a date, or None if invalid."""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return None


def months_in_range(from_date: date, to_date: date) -> list[str]:
    """Return list of 'YYYY-MM' strings covering a date range."""
    months = []
    current = from_date.replace(day=1)
    while current <= to_date:
        months.append(current.strftime("%Y-%m"))
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)
    return months


def parse_date_args(args, console=None) -> tuple[date | None, date | None] | None:
    """Parse ``--from``/``--to`` argparse flags into dates.

    Expects ``args.from_date`` and ``args.to_date`` attributes.
    Returns ``(from_date, to_date)`` on success, or ``None`` if
    a provided date string is invalid (prints error to ``console``
    if provided, otherwise to stderr).
    """
    from_date = parse_date(args.from_date) if args.from_date else None
    to_date = parse_date(args.to_date) if args.to_date else None

    def _error(msg):
        if console:
            console.print(f"[red]{msg}[/red]")
        else:
            print(msg, file=sys.stderr)

    if args.from_date and not from_date:
        _error("Invalid --from date. Use YYYY-MM-DD format.")
        return None
    if args.to_date and not to_date:
        _error("Invalid --to date. Use YYYY-MM-DD format.")
        return None
    return from_date, to_date
