"""rich-metadata: A Rich-based TUI toolkit for building metadata browsers."""

from .cli import (
    configure_logging,
    list_fetcher,
    page_fetcher,
    months_in_range,
    parse_date,
    parse_date_args,
    resolve_entity_type,
    strip_internal_keys,
)
from .display import (
    DisplayEngine,
    EntityDef,
    HeaderField,
    HeaderLink,
    SectionDef,
    SummaryField,
    TableColumn,
    format_duration,
    info_grid,
    parse_duration,
    show_text_panel,
)
from .images import get_image_escape, show_image_beside
from .navigator import BaseNavigator, QuitSignal

__all__ = [
    # display
    "DisplayEngine",
    "EntityDef",
    "HeaderField",
    "HeaderLink",
    "SectionDef",
    "SummaryField",
    "TableColumn",
    "format_duration",
    "info_grid",
    "parse_duration",
    "show_text_panel",
    # images
    "get_image_escape",
    "show_image_beside",
    # navigator
    "BaseNavigator",
    "QuitSignal",
    # cli
    "configure_logging",
    "list_fetcher",
    "page_fetcher",
    "months_in_range",
    "parse_date",
    "parse_date_args",
    "resolve_entity_type",
    "strip_internal_keys",
]
