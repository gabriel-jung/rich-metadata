"""Data-driven entity display engine.

Instead of writing per-entity display functions, declare entities with
``EntityDef`` and let the ``DisplayEngine`` render summaries, headers,
sections, and full detail views.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .images import show_image_beside

# ─── Dataclasses ────────────────────────────────────────────────────────────


@dataclass
class SummaryField:
    """A field shown in one-line entity summaries (search results, lists).

    If ``key`` is set, the value is extracted and optionally passed to ``transform``.
    If ``key`` is empty, ``transform`` receives the whole entity dict.

    Example::

        SummaryField(key="name", style="bold")
        SummaryField(key="country", style="dim", fallback="Unknown")
        SummaryField(transform=lambda d: f"({d.get('real_name', '')})")
    """

    key: str = ""  # entity dict key to extract the value from
    style: str = ""  # Rich style applied to the field (e.g. "bold", "dim")
    prefix: str = ""  # text prepended to the value (e.g. "by ")
    fallback: str = ""  # shown when the key is missing or empty
    transform: Callable[[Any], str] | None = None  # transform(value) or transform(entity)


@dataclass
class HeaderField:
    """A row in the header info panel (key/value grid).

    If ``key`` is set, the value is extracted and optionally passed to ``transform``.
    If ``key`` is empty, ``transform`` receives the whole entity dict.

    Example::

        HeaderField("Genre", key="genre")
        HeaderField("Status", key="status", transform=colorize_status)
        HeaderField("Origin", transform=lambda d: f"{d['country']} ({d['city']})")
    """

    label: str  # left-column label shown in the grid
    key: str = ""  # entity dict key to extract the value from
    transform: Callable[[Any], str] | None = None  # transform(value) or transform(entity)


@dataclass
class TableColumn:
    """A column in a table section.

    Example::

        TableColumn("Title", "name", style="bold")
        TableColumn("Duration", "duration", justify="right")
        TableColumn("Year", "year", width=6, style="dim")
    """

    header: str  # column header text
    key: str  # item dict key to extract cell values from
    style: str = ""  # Rich style for cell text
    justify: str = "left"  # column alignment: "left", "right", "center"
    width: int | None = None  # fixed column width (None = auto)
    transform: Callable[[Any], str] | None = None  # applied to cell value


@dataclass
class SectionDef:
    """A detail section shown when viewing an entity.

    The rendering mode is auto-detected:

    - Has ``columns`` → table (flat list or grouped dict, auto-detected)
    - Has ``custom_render`` → custom rendering function
    - Neither → text panel

    ``label`` defaults to the key with underscores replaced by spaces and
    title-cased (e.g. ``"related_items"`` → ``"Related Items"``).

    Example::

        SectionDef("chapters", navigable=True,
                   columns=[TableColumn("Title", "name"), TableColumn("Pages", "pages")])
        SectionDef("description", lazy=True)
        SectionDef("contributors", navigable=True,
                   columns=[TableColumn("Name", "name"), TableColumn("Role", "role")])
    """

    key: str  # entity dict key holding the section data
    label: str = ""  # display label (default: derived from key)
    columns: list[TableColumn] = field(default_factory=list)  # columns for table sections

    def __post_init__(self):
        if not self.label:
            self.label = self.key.replace("_", " ").title()
    navigable: bool = False  # whether items can be selected for navigation
    lazy: bool = False  # if True, data is fetched on demand (not on initial load)
    numbered: bool = True  # show row numbers in tables
    duration_key: str | None = None  # item key for durations — if set, shows total (e.g. "duration")
    group_key: str | None = None  # item key to group a list[dict] into a dict[str, list]
    custom_render: Callable[[Console, dict], None] | None = None  # custom render function
    nav_items: Callable[[dict], list] | None = None  # custom extractor for navigable items


@dataclass
class HeaderLink:
    """A navigation link shown in the interactive menu below sections.

    Links are resolved at display time: if the reference is missing or None,
    the link is hidden. The ``label`` supports ``{key}`` placeholders filled
    from the entity dict.

    Example::

        HeaderLink("Publisher: {publisher}", "publisher", ref_key="publisher_url")
        HeaderLink("Author: {author}", "author",
                   ref_fn=lambda d: f"https://site.com/author/{d['author_id']}")
    """

    label: str  # display label with {key} placeholders
    target_type: str  # entity type to navigate to
    ref_key: str = ""  # entity dict key holding the reference (URL or ID)
    ref_fn: Callable[[dict], str | None] | None = None  # compute reference from entity

    def resolve(self, entity: dict) -> tuple[str, str] | None:
        """Return (display_label, ref) or None if the link doesn't apply."""
        ref = self.ref_fn(entity) if self.ref_fn else entity.get(self.ref_key)
        if not ref:
            return None
        display = self.label.format_map(_SafeDict(entity))
        return display, ref


class _SafeDict(dict):
    """Dict subclass for safe ``str.format_map`` — returns ``'{key}'`` for missing keys."""

    def __missing__(self, key):
        return f"{{{key}}}"


@dataclass
class EntityDef:
    """Complete definition of how to display an entity type.

    Register instances with ``DisplayEngine.register()`` to teach
    the engine how to render summaries, headers, sections, and detail views
    for a given ``_type``.

    Example::

        book_def = EntityDef(
            type_name="book",
            summary=[
                SummaryField(key="title", style="bold"),
                SummaryField(prefix="by ", key="author"),
            ],
            header_fields=[
                HeaderField("Author", key="author"),
                HeaderField("Year", key="year"),
            ],
            sections=[
                SectionDef(key="chapters", label="Chapters", navigable=True,
                           columns=[TableColumn("Title", "name", style="bold")]),
            ],
            header_links=[
                HeaderLink("Author: {author}", "author", ref_key="author_url"),
            ],
        )
        engine = DisplayEngine()
        engine.register(book_def)
    """

    type_name: str  # matches the ``_type`` field in entity dicts
    summary: list[SummaryField] = field(default_factory=list)  # one-line summary fields
    header_fields: list[HeaderField] = field(default_factory=list)  # info panel rows
    header_image_key: str | None = None  # entity key holding image bytes (e.g. "_cover_data")
    header_title: Callable[[dict], str] | None = None  # custom title (default: entity["name"])
    panel_border_style: str = "blue"  # Rich border style for the header panel
    sections: list[SectionDef] = field(default_factory=list)  # detail sections
    header_links: list[HeaderLink] = field(default_factory=list)  # interactive navigation links
    footer: list[str | Callable[[dict], str | None]] | None = None  # keys or callables for footer lines
    auto_full: bool = False  # if True, show all sections inline (no interactive menu)


# ─── Helpers ────────────────────────────────────────────────────────────────


def _deep_get(d: dict, key: str, default=""):
    """Get a value by key, supporting dot-notation for nested access (e.g. 'author.name')."""
    if "." not in key:
        return d.get(key, default)
    for part in key.split("."):
        if not isinstance(d, dict):
            return default
        d = d.get(part, default)
    return d


def info_grid(rows: list[tuple[str, str]]) -> Table:
    """Build a borderless key/value grid for info sections."""
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="bold", justify="right")
    grid.add_column()
    for label, value in rows:
        if value:
            grid.add_row(label, value)
    return grid


def show_text_panel(console: Console, text: str | None, title: str) -> None:
    """Show text in a bordered panel, or a 'not available' message."""
    if text:
        console.print()
        console.print(Panel(text, title=title, border_style="dim"))
    else:
        console.print(f"\n[dim]No {title.lower()} available.[/dim]")


def parse_duration(dur: str) -> int | None:
    """Parse 'MM:SS' or 'H:MM:SS' to total seconds, or None if unparseable."""
    parts = dur.strip().split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    except ValueError:
        pass
    return None


def format_duration(seconds: int) -> str:
    """Format total seconds as 'H:MM:SS' or 'MM:SS'."""
    h, remainder = divmod(seconds, 3600)
    m, s = divmod(remainder, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


# ─── Display Engine ─────────────────────────────────────────────────────────


class DisplayEngine:
    """Renders entities based on EntityDef declarations."""

    def __init__(self, console: Console | None = None):
        self.console = console or Console()
        self._registry: dict[str, EntityDef] = {}

    def register(self, *entity_defs: EntityDef) -> None:
        """Register one or more entity definitions."""
        for defn in entity_defs:
            self._registry[defn.type_name] = defn

    def get_def(self, type_name: str) -> EntityDef | None:
        """Return the entity definition for a type, or None."""
        return self._registry.get(type_name)

    # ── Summary ──────────────────────────────────────────────────────────

    def summary(self, entity: dict) -> None:
        """Render a one-line summary."""
        defn = self._registry.get(entity.get("_type", ""))
        if not defn:
            self.console.print(f"[bold]{entity.get('name', str(entity))}[/bold]")
            return

        parts: list[str] = []
        for f in defn.summary:
            if f.key:
                val = entity.get(f.key, f.fallback) or f.fallback
                if f.transform:
                    val = f.transform(val)
            elif f.transform:
                val = f.transform(entity)
            else:
                val = f.fallback

            if val:
                text = f"{f.prefix}{val}"
                parts.append(f"[{f.style}]{text}[/{f.style}]" if f.style else text)

        self.console.print("  ".join(parts))

    # ── Header ───────────────────────────────────────────────────────────

    def header(self, entity: dict) -> None:
        """Render the info panel with optional image."""
        defn = self._registry.get(entity.get("_type", ""))
        if not defn:
            return

        rows: list[tuple[str, str]] = []
        for hf in defn.header_fields:
            if hf.key:
                val = entity.get(hf.key, "")
                if hf.transform:
                    val = hf.transform(val)
            elif hf.transform:
                val = hf.transform(entity)
            else:
                continue

            if val is not None:
                rows.append((hf.label, str(val)))

        grid = info_grid(rows)
        title = (
            defn.header_title(entity)
            if defn.header_title
            else f"[bold]{entity.get('name', '')}[/bold]"
        )
        panel = Panel(grid, title=title, border_style=defn.panel_border_style)

        self.console.print()
        image_data = (
            entity.get(defn.header_image_key) if defn.header_image_key else None
        )
        show_image_beside(self.console, image_data, panel)

        if defn.footer:
            for item in defn.footer:
                val = entity.get(item) if isinstance(item, str) else item(entity)
                if val:
                    self.console.print(f"[dim]{val}[/dim]")

    # ── Sections ─────────────────────────────────────────────────────────

    def section(self, entity: dict, section_key: str) -> None:
        """Render a specific section."""
        defn = self._registry.get(entity.get("_type", ""))
        if not defn:
            return
        sec = next((s for s in defn.sections if s.key == section_key), None)
        if sec:
            self._render_section(entity, sec)

    def details(self, entity: dict) -> None:
        """Render header + all sections.

        Lazy sections are included only if their data is already present.
        """
        self.header(entity)
        defn = self._registry.get(entity.get("_type", ""))
        if not defn:
            return
        for sec in defn.sections:
            if not sec.lazy or entity.get(sec.key):
                self._render_section(entity, sec)

    def _render_section(self, entity: dict, sec: SectionDef) -> None:
        """Dispatch a section to the right renderer based on its definition."""
        if sec.custom_render:
            sec.custom_render(self.console, entity)
        elif sec.columns:
            self._render_table(entity, sec)
        else:
            show_text_panel(self.console, entity.get(sec.key), sec.label)

    def _render_table(self, entity: dict, sec: SectionDef) -> None:
        """Render a table section. Handles flat lists and grouped dicts uniformly."""
        data = entity.get(sec.key)
        if not data:
            return

        # Normalize to dict[str, list] — a flat list is one unnamed group
        if isinstance(data, list):
            if sec.group_key:
                groups: dict[str, list] = {}
                for item in data:
                    gk = item.get(sec.group_key, "")
                    groups.setdefault(gk, []).append(item)
            else:
                groups = {"": data}
        elif isinstance(data, dict):
            groups = data
        else:
            return

        table = Table(title=sec.label, border_style="dim", show_edge=False)
        if sec.numbered:
            table.add_column("#", justify="right", style="dim", width=4)
        for col in sec.columns:
            table.add_column(
                col.header, style=col.style, justify=col.justify, width=col.width,
            )

        total_seconds = 0
        all_have_duration = True
        idx = 1
        first_group = True

        for group_name, items in groups.items():
            label = group_name.strip().capitalize() if group_name else ""
            if label:
                if not first_group:
                    table.add_section()
                first_group = False
                empty_cols = [""] * len(sec.columns)
                if sec.numbered:
                    table.add_row("", f"[bold dim]{label}[/bold dim]", *empty_cols[1:])
                else:
                    table.add_row(f"[bold dim]{label}[/bold dim]", *empty_cols[1:])

            for item in items:
                row: list[str] = []
                if sec.numbered:
                    row.append(str(idx))
                for col in sec.columns:
                    val = _deep_get(item, col.key)
                    if col.transform:
                        val = col.transform(val)
                    row.append(str(val) if val is not None else "")
                table.add_row(*row)
                idx += 1

                if sec.duration_key:
                    dur = item.get(sec.duration_key, "")
                    parsed = parse_duration(dur) if dur else None
                    if parsed is not None:
                        total_seconds += parsed
                    else:
                        all_have_duration = False

        self.console.print()
        self.console.print(table)

        if sec.duration_key and all_have_duration and total_seconds > 0:
            self.console.print(
                f"  [dim]Total: {format_duration(total_seconds)}[/dim]"
            )

    # ── Selection / Pagination helpers ───────────────────────────────────

    def section_page(
        self, items: list[dict], start: int = 0, count: int = 25,
    ) -> None:
        """Display a page of items using their summary format."""
        end = min(start + count, len(items))
        self.console.print()
        for i in range(start, end):
            item = items[i]
            self.console.print(
                f"  [bold cyan]\\[{i + 1}][/bold cyan] ", end="",
            )
            self.summary(item)

    def select_from_list(
        self,
        items: list[dict],
        *,
        title: str = "",
        label: str = "results",
        page_size: int = 10,
    ) -> dict | None:
        """Display a paginated numbered list and prompt for selection."""
        if not items:
            self.console.print(f"[dim]No {label} found.[/dim]")
            return None

        if len(items) == 1:
            return items[0]

        total = len(items)
        total_pages = (total + page_size - 1) // page_size
        page = 0

        while True:
            start = page * page_size
            end = min(start + page_size, total)

            if title:
                self.console.print(f"\n[bold]{title}[/bold]")
            if total_pages > 1:
                self.console.print(
                    f"[dim]Page {page + 1}/{total_pages} — {total} {label}[/dim]\n"
                )
            else:
                self.console.print(f"[dim]{total} {label}[/dim]\n")

            mixed = len({item.get("_type") for item in items}) > 1
            for i in range(start, end):
                tag = (
                    f"[dim]{items[i].get('_type', ''):>6}[/dim] " if mixed else ""
                )
                self.console.print(
                    f"  [bold cyan]\\[{i + 1}][/bold cyan] {tag}", end="",
                )
                self.summary(items[i])

            self.console.print()
            hints = []
            if page > 0:
                hints.append("[bold]p[/bold]rev page")
            if page < total_pages - 1:
                hints.append("[bold]n[/bold]ext page")
            hints.append("[bold]0[/bold] to cancel")
            self.console.print(f"[dim]{' | '.join(hints)}[/dim]")

            try:
                raw = self.console.input("\n[bold]>[/bold] ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                return None

            if not raw:
                continue
            if raw == "n" and page < total_pages - 1:
                page += 1
                continue
            if raw == "p" and page > 0:
                page -= 1
                continue
            if raw == "0":
                return None

            try:
                choice = int(raw)
            except ValueError:
                continue

            if 1 <= choice <= total:
                return items[choice - 1]
