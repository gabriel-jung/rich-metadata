"""Base navigator with interactive browsing, pagination, and back-navigation."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from .cli import strip_internal_keys
from .display import DisplayEngine


class QuitSignal(Exception):
    """Raised to exit the entire interactive session."""


class BaseNavigator:
    """Interactive entity browser.

    Can be used directly by passing configuration to the constructor,
    or subclassed for more complex needs.

    Parameters
    ----------
    display : DisplayEngine
        The display engine with registered entity definitions.
    apis : dict[str, Any] | None
        Mapping of entity type to API object (must have a ``.get(ref)`` method).
        Auto-implements ``fetch_entity`` when provided.
    entity_ref_key : str
        Key used to extract the navigable reference from item dicts
        (e.g. ``"url"`` or ``"id"``).
    lazy_fetchers : dict[tuple[str, str], Callable] | None
        Mapping of ``(entity_type, section_key)`` to
        ``callable(api, entity) -> data`` for lazy sections.
    """

    def __init__(
        self,
        display: DisplayEngine,
        *,
        apis: dict[str, Any] | None = None,
        entity_ref_key: str = "url",
        lazy_fetchers: dict[tuple[str, str], Callable] | None = None,
    ):
        self.display = display
        self.apis = apis or {}
        self.entity_ref_key = entity_ref_key
        self._lazy_fetchers = lazy_fetchers or {}
        self._history: list[dict] = []

    # ── Overridable interface ─────────────────────────────────────────────

    def fetch_entity(self, entity_type: str, ref: str, **kwargs) -> dict | None:
        """Fetch a full entity by type and reference (URL or ID)."""
        api = self.apis.get(entity_type)
        if not api:
            return None
        with self.console.status("Fetching details..."):
            return api.get(ref, **kwargs)

    def get_entity_ref(self, item: dict) -> str | None:
        """Extract the navigable reference from an item dict."""
        return item.get(self.entity_ref_key)

    def get_lazy_fetcher(
        self, entity_type: str, section_key: str,
    ) -> Callable[[dict], Any] | None:
        """Return a callable(entity) -> data for lazy sections, or None."""
        fetcher = self._lazy_fetchers.get((entity_type, section_key))
        if not fetcher:
            return None
        api = self.apis.get(entity_type)
        if not api:
            return None
        return lambda entity: fetcher(api, entity)

    def get_navigable_items(
        self, entity_type: str, section_key: str, entity: dict,
    ) -> list | None:
        """Return navigable items for a section, or None if not navigable.

        Auto-derives from SectionDef:
        - If ``nav_items`` is set, calls it with the entity.
        - If the data is a ``dict``, flattens all group lists.
        - Otherwise, returns ``entity.get(section_key, [])``.
        """
        defn = self.display.get_def(entity_type)
        if not defn:
            return None
        sec = next((s for s in defn.sections if s.key == section_key), None)
        if not sec or not sec.navigable:
            return None

        if sec.nav_items:
            return sec.nav_items(entity)

        data = entity.get(section_key, [])
        if isinstance(data, dict):
            return [item for group in data.values() for item in group]

        return data

    def get_header_links(self, entity: dict) -> list[tuple[str, str, str]]:
        """Return [(display_label, entity_type, ref)] for header navigation.

        Auto-derives from EntityDef.header_links when defined.
        """
        defn = self.display.get_def(entity.get("_type", ""))
        if not defn or not defn.header_links:
            return []

        links = []
        for hl in defn.header_links:
            resolved = hl.resolve(entity)
            if resolved:
                display_label, ref = resolved
                links.append((display_label, hl.target_type, ref))
        return links

    # ── Core navigation ──────────────────────────────────────────────────

    @property
    def console(self):
        """Shortcut to the display engine's console."""
        return self.display.console

    def navigate(self, entity: dict) -> None:
        """Interactive display with section menu and back-navigation."""
        self._history.append(entity)
        try:
            self._interactive_loop(entity)
        finally:
            self._history.pop()

    def display_or_navigate(
        self,
        entity: dict,
        *,
        json_output: bool = False,
        full: bool = False,
    ) -> None:
        """Display an entity as JSON, full details, or interactive navigation.

        Dispatches based on output mode:
        - ``json_output``: print as JSON (internal keys stripped)
        - ``full``: show header + all sections, then return
        - otherwise: interactive ``navigate()``
        """
        if json_output:
            print(json.dumps(strip_internal_keys(entity), indent=2))
        elif full:
            self.display.details(entity)
        else:
            self.navigate(entity)

    def search_and_navigate(
        self,
        query: str,
        entity_types: list[str],
        *,
        exact_first: bool = True,
        json_output: bool = False,
        full: bool = False,
    ) -> None:
        """Search, select from results, fetch full entity, and display.

        Searches across all given entity types, optionally preferring exact
        name matches. Shows a selection list, fetches the full entity via
        ``fetch_entity``, and dispatches to ``display_or_navigate``.
        """
        all_results = []
        with self.console.status(f"Searching for [bold]{query}[/bold]..."):
            for t in entity_types:
                api = self.apis.get(t)
                if api:
                    all_results.extend(api.search(query, exact_match=False))

        if exact_first:
            exact = [r for r in all_results if r["name"].lower() == query.lower()]
            if exact:
                all_results = exact

        if not all_results:
            self.console.print("[yellow]No items found matching your criteria.[/yellow]")
            return

        selected = self.display.select_from_list(all_results)
        if not selected:
            return

        ref = self.get_entity_ref(selected)
        if not ref:
            self.console.print("[dim]This item is not navigable.[/dim]")
            return

        fetch_full = json_output or full
        entity = self.fetch_entity(selected["_type"], ref, full=fetch_full)
        if not entity:
            self.console.print("[red]Could not retrieve detailed information.[/red]")
            return

        self.display_or_navigate(entity, json_output=json_output, full=full)

    def browse(
        self,
        *,
        fetch_page: Callable[[int, int], tuple[list, int]],
        render_page: Callable[[list, int], None] | None = None,
        title: str | None = None,
        page_size: int = 25,
        full: bool = False,
        loop: bool = False,
    ) -> None:
        """Paginated item browsing with navigation.

        ``fetch_page(start, count)`` returns ``(results, total)``.
        ``render_page(results, start)``: custom page renderer (default: one-liners).
        """
        start = 0
        results, total = fetch_page(start, page_size)
        if not results:
            if not render_page:
                self.console.print("[yellow]No items found.[/yellow]")
            return

        def _render_default(page_results: list, page_start: int) -> None:
            if title:
                self.console.print(f"\n[bold]{title}[/bold]")
            for i, item in enumerate(page_results, page_start + 1):
                self.console.print(f"  [bold cyan]\\[{i}][/bold cyan] ", end="")
                self.display.summary(item)

        render = render_page or _render_default

        # Initial render (custom renderers may have already displayed)
        if not render_page:
            render(results, start)

        while True:
            end = min(start + len(results), total)
            total_pages = (total + page_size - 1) // page_size
            page = start // page_size

            self.console.print()
            if total_pages > 1:
                self.console.print(
                    f"[dim]Page {page + 1}/{total_pages} "
                    f"({start + 1}-{end} of {total})[/dim]"
                )

            hints = [f"[bold]{start + 1}-{end}[/bold] to select"]
            if page > 0:
                hints.extend(["[bold]f[/bold]irst", "[bold]p[/bold]rev"])
            if page < total_pages - 1:
                hints.extend(["[bold]n[/bold]ext", "[bold]l[/bold]ast"])
            self.console.print(f"[dim]{' | '.join(hints)}[/dim]")
            self.console.print(
                "[dim][bold]0[/bold] to go back | Ctrl+C to quit[/dim]"
            )

            try:
                raw = self.console.input("[bold]>[/bold] ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                raise QuitSignal()

            if not raw:
                continue
            if raw == "0":
                return

            # Page navigation
            new_start = None
            if raw == "n" and page < total_pages - 1:
                new_start = start + page_size
            elif raw == "p" and page > 0:
                new_start = max(0, start - page_size)
            elif raw == "f" and page > 0:
                new_start = 0
            elif raw == "l" and page < total_pages - 1:
                new_start = max(0, total - page_size)

            if new_start is not None:
                with self.console.status("Loading..."):
                    results, total = fetch_page(new_start, page_size)
                if not results:
                    self.console.print("[dim]No more results.[/dim]")
                    return
                start = new_start
                render(results, start)
                continue

            # Item selection
            try:
                choice = int(raw)
            except ValueError:
                continue

            idx = choice - 1 - start
            if not (0 <= idx < len(results)):
                continue

            item = results[idx]

            # Check if item is navigable
            if not item.get("_type"):
                self.console.print("[dim]This item is not navigable.[/dim]")
                continue

            ref = self.get_entity_ref(item)
            if ref:
                target = self.fetch_entity(item["_type"], ref)
                if not target:
                    self.console.print("[red]Could not fetch details.[/red]")
                    continue
            else:
                # Item is already a complete entity (e.g. inline song)
                target = item

            if full:
                self.display.details(target)
                return

            self.navigate(target)
            if not loop:
                return
            # Re-display after coming back
            render(results, start)

    def browse_sources(
        self,
        sources: list[tuple[str, Callable[[int, int], tuple[list, int]]]],
        *,
        full: bool = False,
    ) -> None:
        """Let the user pick from named browsable sources.

        If there is only one source, browses it directly.
        Otherwise shows a menu to choose, then browses the selected source.

        Each source is a ``(label, fetch_page)`` tuple where ``fetch_page``
        follows the same ``(start, count) -> (results, total)`` contract
        as ``browse()``.
        """
        if len(sources) == 1:
            label, fetch_page = sources[0]
            self.browse(fetch_page=fetch_page, title=label, full=full)
            return

        while True:
            self.console.print()
            for i, (label, _) in enumerate(sources, 1):
                self.console.print(f"  [bold cyan]\\[{i}][/bold cyan] {label}")
            self.console.print()
            self.console.print(
                "  [dim][bold]0[/bold] to go back | Ctrl+C to quit[/dim]"
            )

            try:
                raw = self.console.input("\n[bold]Choose:[/bold] ").strip()
            except (KeyboardInterrupt, EOFError):
                raise QuitSignal()

            if not raw:
                continue

            try:
                choice = int(raw)
            except ValueError:
                continue

            if choice == 0:
                return

            if 1 <= choice <= len(sources):
                label, fetch_page = sources[choice - 1]
                self.browse(fetch_page=fetch_page, title=label, full=full)

    # ── Interactive loop ─────────────────────────────────────────────────

    def _interactive_loop(self, entity: dict) -> None:
        """Section menu loop with lazy fetching and header link navigation."""
        self.display.header(entity)

        entity_type = entity["_type"]
        defn = self.display.get_def(entity_type)
        if not defn:
            return

        sections = defn.sections
        header_links = self.get_header_links(entity)

        if not sections and not header_links:
            return

        while True:
            self.console.print()
            for i, sec in enumerate(sections, 1):
                has_data = bool(entity.get(sec.key))
                is_lazy = sec.lazy
                is_nav = sec.navigable

                suffix = " [dim]\u2192[/dim]" if is_nav else ""

                if has_data or is_lazy:
                    self.console.print(
                        f"  [bold cyan]\\[{i}][/bold cyan] {sec.label}{suffix}"
                    )
                else:
                    self.console.print(
                        f"  [dim]\\[{i}] {sec.label} (empty)[/dim]"
                    )

            for j, (link_label, _link_type, _link_ref) in enumerate(header_links):
                idx = len(sections) + 1 + j
                self.console.print(
                    f"  [bold cyan]\\[{idx}][/bold cyan] {link_label} [dim]\u2192[/dim]"
                )

            self.console.print()
            back_label = "go back" if len(self._history) > 1 else "exit"
            self.console.print(
                f"  [dim][bold]0[/bold] to {back_label} | Ctrl+C to quit[/dim]"
            )

            try:
                raw = self.console.input("\n[bold]Choose:[/bold] ").strip()
            except (KeyboardInterrupt, EOFError):
                raise QuitSignal()

            if not raw:
                continue

            try:
                choice = int(raw)
            except ValueError:
                continue

            if choice == 0:
                break

            total_sections = len(sections)
            total_header_links = len(header_links)

            if 1 <= choice <= total_sections:
                sec = sections[choice - 1]

                # Lazy fetch if needed
                if not entity.get(sec.key) and sec.lazy:
                    fetcher = self.get_lazy_fetcher(entity_type, sec.key)
                    if fetcher:
                        with self.console.status(f"Fetching {sec.label}..."):
                            entity[sec.key] = fetcher(entity)

                self.display.section(entity, sec.key)

                # Offer navigation into section items
                if sec.navigable:
                    items = self.get_navigable_items(
                        entity_type, sec.key, entity,
                    )
                    if items:
                        n = len(items)
                        self._offer_navigation(
                            items,
                            title=sec.label,
                            page_size=n if n <= 100 else 25,
                            skip_render=bool(sec.columns),
                        )

            elif total_sections < choice <= total_sections + total_header_links:
                _, link_type, link_ref = header_links[
                    choice - total_sections - 1
                ]
                target = self.fetch_entity(link_type, link_ref)
                if target:
                    self.navigate(target)
                    self.display.header(entity)
                else:
                    self.console.print("[red]Could not fetch details.[/red]")
            else:
                self.console.print("[red]Invalid choice.[/red]")

    def _offer_navigation(
        self,
        items: list[dict],
        title: str = "",
        page_size: int = 25,
        skip_render: bool = False,
    ) -> None:
        """Paginated navigation through section items."""
        has_navigable = any(item.get("_type") for item in items)
        if not has_navigable:
            return

        page = 0
        total = len(items)
        total_pages = (total + page_size - 1) // page_size

        if not skip_render:
            if title:
                self.console.print()
                self.console.rule(title, style="dim")
            self.display.section_page(items, start=0, count=page_size)

        while True:
            start = page * page_size
            end = min(start + page_size, total)

            self.console.print()
            if total_pages > 1:
                self.console.print(
                    f"[dim]Page {page + 1}/{total_pages} "
                    f"(items {start + 1}-{end} of {total})[/dim]"
                )

            hints = [f"[bold]1-{total}[/bold] to select"]
            if page > 0:
                hints.extend(["[bold]f[/bold]irst page", "[bold]p[/bold]rev page"])
            if page < total_pages - 1:
                hints.extend(["[bold]n[/bold]ext page", "[bold]l[/bold]ast page"])

            self.console.print(f"[dim]{' | '.join(hints)}[/dim]")
            self.console.print()
            self.console.print(
                "[dim][bold]0[/bold] to go back | Ctrl+C to quit[/dim]"
            )

            try:
                raw = self.console.input("[bold]>[/bold] ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                raise QuitSignal()

            if not raw:
                continue
            if raw == "0":
                return

            new_page = page
            if raw == "n" and page < total_pages - 1:
                new_page = page + 1
            elif raw == "p" and page > 0:
                new_page = page - 1
            elif raw == "f" and page > 0:
                new_page = 0
            elif raw == "l" and page < total_pages - 1:
                new_page = total_pages - 1

            if new_page != page:
                page = new_page
                self.display.section_page(
                    items, start=page * page_size, count=page_size,
                )
                continue

            try:
                idx = int(raw) - 1
            except ValueError:
                continue

            if 0 <= idx < total:
                item = items[idx]
                if not item.get("_type"):
                    self.console.print("[dim]This item is not navigable.[/dim]")
                    continue

                ref = self.get_entity_ref(item)
                if ref:
                    target = self.fetch_entity(item["_type"], ref)
                else:
                    # Item is already a complete entity (e.g. inline song)
                    target = item

                if target:
                    self.navigate(target)
                    # Re-display current page after coming back
                    if title:
                        self.console.print()
                        self.console.rule(title, style="dim")
                    self.display.section_page(
                        items, start=page * page_size, count=page_size,
                    )
