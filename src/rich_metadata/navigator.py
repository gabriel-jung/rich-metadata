"""Base navigator with interactive browsing, pagination, and back-navigation."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from loguru import logger

from .cli import strip_internal_keys
from .display import DisplayEngine, SectionDef, escape


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
        Mapping of entity type to API object. Each needs
        ``.get(ref, *, full=False, **kwargs)``; ``full=True`` is passed only
        when the caller asked for every section (``--json`` / ``--full``).
        ``search_and_navigate`` also needs ``.search(query, exact_match=...)``.
        Auto-implements ``fetch_entity`` when provided.
    entity_ref_key : str
        Key used to extract the navigable reference from item dicts
        (e.g. ``"url"`` or ``"id"``).
    lazy_fetchers : dict[tuple[str, str], Callable] | None
        Mapping of ``(entity_type, section_key)`` to
        ``callable(api, entity) -> data`` for lazy sections.

    Inside the interactive views, a fetch that raises (``.get``, a lazy
    fetcher, a later page) is logged and shown as "Could not fetch", and the
    user stays where they were. ``fetch_entity`` itself, the first search or
    page, and the fetch in ``search_and_navigate``'s ``json_output`` / ``full``
    modes let errors propagate. Ctrl+C during any fetch raises ``QuitSignal``,
    like Ctrl+C at a navigator prompt.
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
        self._depth = 0  # how many navigate() calls are open

    # ── Overridable interface ─────────────────────────────────────────────

    def fetch_entity(self, entity_type: str, ref: str, **kwargs) -> dict | None:
        """Fetch a full entity by type and reference (URL or ID).

        Returns None when there is no API for the type. Errors from the API
        propagate; the interactive views catch them, direct callers see them.
        """
        api = self.apis.get(entity_type)
        if not api:
            return None
        with self.console.status("Fetching details..."):
            return api.get(ref, **kwargs)

    def get_entity_ref(self, item: dict) -> str | None:
        """Extract the navigable reference from an item dict."""
        return item.get(self.entity_ref_key)

    def get_lazy_fetcher(
        self,
        entity_type: str,
        section_key: str,
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
        self,
        entity_type: str,
        section_key: str,
        entity: dict,
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

    def _input(self, prompt: str, *, lower: bool = True) -> str:
        """Read a line from the console, raising ``QuitSignal`` on Ctrl+C / EOF."""
        try:
            raw = self.console.input(prompt).strip()
        except (KeyboardInterrupt, EOFError):
            raise QuitSignal()
        return raw.lower() if lower else raw

    def navigate(
        self,
        entity: dict,
        *,
        siblings: list[dict] | None = None,
        sibling_index: int = 0,
        can_go_back: bool = False,
    ) -> None:
        """Interactive display with section menu and back-navigation."""
        self._depth += 1
        try:
            self.display.header(entity)
            defn = self.display.get_def(entity["_type"])
            if not defn or (not defn.sections and not self.get_header_links(entity)):
                return
            loop = self._auto_full_loop if defn.auto_full else self._section_menu
            loop(entity, siblings=siblings, sibling_index=sibling_index, can_go_back=can_go_back)
        finally:
            self._depth -= 1

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
            self._print_json(entity)
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
    ) -> bool:
        """Search, select from results, fetch full entity, and display.

        Searches across all given entity types, optionally preferring exact
        name matches. Shows a selection list, fetches the full entity via
        ``fetch_entity`` (passing ``full=True`` only for ``json_output`` or
        ``full``), and dispatches to ``display_or_navigate``. With a single
        result there is no list to return to, so going back ends the search.

        ``json_output`` and ``full`` are script modes: a fetch error
        propagates, and a pick that cannot be shown ends the search instead of
        returning to the list. Returns False when nothing was found or the
        picked entity could not be shown, so a CLI can set its exit status.
        """

        def run_search() -> list:
            found = []
            for t in entity_types:
                api = self.apis.get(t)
                if api:
                    found.extend(api.search(query, exact_match=False))
            return found

        all_results = self._interruptible(run_search, f"Searching for [bold]{escape(query)}[/bold]...")

        if exact_first:
            q = query.lower()
            exact = [r for r in all_results if r.get("name", "").lower() == q]
            if exact:
                all_results = exact

        if not all_results:
            self.console.print("[yellow]No items found matching your criteria.[/yellow]")
            return False

        single = len(all_results) == 1
        script = json_output or full
        options = {"full": True} if script else {}
        while True:
            selected = self.display.select_from_list(all_results)
            if not selected:
                return False

            entity = self._resolve_item(selected, inline=False, propagate=script, **options)
            if entity:
                if json_output:
                    self._print_json(entity)
                    return True
                if full:
                    self.display.details(entity)
                    return True
                self.navigate(entity, can_go_back=not single)
            elif script:
                return False

            if single:
                return entity is not None

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

        ``fetch_page(start, count)`` returns ``(results, total)``; ``start`` is
        always a multiple of ``page_size``.
        ``render_page(results, start)``: custom page renderer (default: one-liners).
        ``loop=False`` returns after the first item is viewed; ``loop=True``
        shows the page again instead.
        """
        start = 0
        results, total = self._interruptible(lambda: fetch_page(0, page_size))
        cap: int | None = None  # where the data is known to end, if a page proved it
        if 0 < len(results) < page_size:
            cap = len(results)
            total = min(total, cap)
        if not results:
            if not render_page:
                self.console.print("[yellow]No items found.[/yellow]")
            return

        def _render_default(page_results: list, page_start: int) -> None:
            if title:
                self.console.print(f"\n[bold]{escape(title)}[/bold]")
            for i, item in enumerate(page_results, page_start + 1):
                self.console.print(f"  [bold cyan]\\[{i}][/bold cyan] ", end="")
                self.display.summary(item)

        render = render_page or _render_default

        # Initial render (custom renderers may have already displayed)
        if not render_page:
            render(results, start)

        options = {"full": True} if full else {}
        while True:
            page = start // page_size
            total_pages = max(1, -(-total // page_size))
            end = min(start + len(results), total)
            cmd = self._pager_prompt(
                page=page,
                total_pages=total_pages,
                status=f"Page {page + 1}/{total_pages} ({start + 1}-{end} of {total})",
                select_hint=f"[bold]{start + 1}-{end}[/bold] to select",
            )

            if isinstance(cmd, int):
                new_start = cmd * page_size
                ok, fetched = self._try(
                    lambda s=new_start: fetch_page(s, page_size),
                    status="Loading...",
                    failure="Could not load that page.",
                )
                if not ok:
                    continue
                new_results, new_total = fetched
                if not new_results:
                    # The source promised more than it serves: stay on this
                    # page and stop offering pages from new_start on.
                    if new_start > start:
                        self.console.print("[dim]No more results.[/dim]")
                        cap = new_start if cap is None else min(cap, new_start)
                        total = min(total, cap)
                    else:
                        self.console.print("[dim]That page came back empty.[/dim]")
                    continue
                start, results = new_start, new_results
                if len(results) < page_size:  # a short page proves where the data ends
                    end_seen = start + len(results)
                    cap = end_seen if cap is None else min(cap, end_seen)
                total = new_total if cap is None else min(new_total, cap)
                render(results, start)
                continue

            if cmd == "0":
                return

            try:
                idx = int(cmd) - 1 - start
            except ValueError:
                continue
            if not (0 <= idx < len(results)):
                continue

            target = self._resolve_item(results[idx], **options)
            if not target:
                continue
            if full:
                self.display.details(target)
            else:
                self.navigate(target, siblings=results, sibling_index=idx)
            if not loop:
                return
            render(results, start)

    def browse_sources(
        self,
        sources: list[tuple[str, Callable[[int, int], tuple[list, int]]]],
        *,
        full: bool = False,
        loop: bool = True,
    ) -> None:
        """Let the user pick from named browsable sources.

        If there is only one source, browses it directly.
        Otherwise shows a menu to choose, then browses the selected source.

        Each source is a ``(label, fetch_page)`` tuple where ``fetch_page``
        follows the same ``(start, count) -> (results, total)`` contract
        as ``browse()``. ``loop`` is passed to ``browse()``; by default going
        back from an item returns to its list.
        """
        if len(sources) == 1:
            label, fetch_page = sources[0]
            self.browse(fetch_page=fetch_page, title=label, full=full, loop=loop)
            return

        while True:
            self.console.print()
            for i, (label, _) in enumerate(sources, 1):
                self.console.print(f"  [bold cyan]\\[{i}][/bold cyan] {escape(label)}")
            self.console.print()
            self.console.print("  [dim][bold]0[/bold] to go back | Ctrl+C to quit[/dim]")

            raw = self._input("\n[bold]Choose:[/bold] ")
            try:
                choice = int(raw)
            except ValueError:
                continue

            if choice == 0:
                return

            if 1 <= choice <= len(sources):
                label, fetch_page = sources[choice - 1]
                self.browse(fetch_page=fetch_page, title=label, full=full, loop=loop)

    # ── Shared helpers ───────────────────────────────────────────────────

    def _print_json(self, entity: dict) -> None:
        print(json.dumps(strip_internal_keys(entity), indent=2))

    def _resolve_item(
        self, item: dict, *, inline: bool = True, propagate: bool = False, **options
    ) -> dict | None:
        """Turn a list item into an entity to show, saying why when it can't.

        Items without ``_type`` are not navigable. Items with a ref are
        fetched (``options`` go to ``fetch_entity``); items without one are
        complete inline entities when ``inline`` is set, else not navigable.
        A fetch error is reported and gives None, unless ``propagate`` is set.
        """
        item_type = item.get("_type")
        ref = self.get_entity_ref(item) if item_type else None
        if not item_type or (not ref and not inline):
            self.console.print("[dim]This item is not navigable.[/dim]")
            return None
        if not ref:
            return item
        return self._fetch_or_report(item_type, ref, propagate=propagate, **options)

    def _fetch_or_report(
        self, entity_type: str, ref: str, *, propagate: bool = False, **options
    ) -> dict | None:
        """``fetch_entity`` with a message on failure.

        Returns None (after a message) when the fetch fails or finds nothing.
        With ``propagate`` an exception from the fetch is raised instead.
        """

        def fetch() -> dict | None:
            return self.fetch_entity(entity_type, ref, **options)

        if propagate:
            target = self._interruptible(fetch)
        else:
            ok, target = self._try(fetch, status=None, failure="Could not fetch details.")
            if not ok:
                return None
        if not target:
            self.console.print("[red]Could not fetch details.[/red]")
        return target

    def _interruptible(self, fn: Callable[[], Any], status: str | None = None) -> Any:
        """Run ``fn`` (behind a spinner when ``status`` is given); Ctrl+C becomes ``QuitSignal``."""
        try:
            if status is None:
                return fn()
            with self.console.status(status):
                return fn()
        except KeyboardInterrupt:
            raise QuitSignal() from None

    def _try(self, fn: Callable[[], Any], *, status: str | None, failure: str) -> tuple[bool, Any]:
        """Run ``fn`` like ``_interruptible``; on an error print ``failure`` and its reason.

        Returns ``(True, value)``, or ``(False, None)`` after an error so the
        caller can stay where it is.
        """
        try:
            return True, self._interruptible(fn, status)
        except QuitSignal:
            raise
        except Exception as exc:
            logger.debug(f"{failure} {type(exc).__name__}: {exc}")
            reason = f" [dim]{escape(exc)}[/dim]" if str(exc) else ""
            self.console.print(f"[red]{failure}[/red]{reason}")
            return False, None

    def _load_lazy(self, entity: dict, sec: SectionDef) -> bool:
        """Fetch a lazy section into ``entity`` if it is missing and has a fetcher.

        Returns False only when the fetch failed (already reported).
        """
        if not sec.lazy or entity.get(sec.key):
            return True
        fetcher = self.get_lazy_fetcher(entity["_type"], sec.key)
        if not fetcher:
            return True
        ok, data = self._try(
            lambda: fetcher(entity),
            status=f"Fetching {escape(sec.label)}...",
            failure=f"Could not fetch {escape(sec.label)}.",
        )
        if ok:
            entity[sec.key] = data
        return ok

    def _pager_prompt(
        self,
        *,
        page: int,
        total_pages: int,
        status: str,
        select_hint: str,
    ) -> int | str:
        """Print the page footer and read one command.

        Returns the target page index for a usable n/p/f/l, otherwise the
        lowercased input (``"0"``, a number, or anything else).
        """
        self.console.print()
        if total_pages > 1:
            self.console.print(f"[dim]{status}[/dim]")
        hints = [select_hint]
        if page > 0:
            hints.extend(["[bold]f[/bold]irst page", "[bold]p[/bold]rev page"])
        if page < total_pages - 1:
            hints.extend(["[bold]n[/bold]ext page", "[bold]l[/bold]ast page"])
        self.console.print(f"[dim]{' | '.join(hints)}[/dim]")
        self.console.print("[dim][bold]0[/bold] to go back | Ctrl+C to quit[/dim]")

        raw = self._input("[bold]>[/bold] ")
        target = {"n": page + 1, "p": page - 1, "f": 0, "l": total_pages - 1}.get(raw)
        if target is not None and target != page and 0 <= target < total_pages:
            return target
        return raw

    def _rule(self, title: str) -> None:
        if title:
            self.console.print()
            self.console.rule(escape(title), style="dim")

    # ── Entity views ─────────────────────────────────────────────────────

    def _back_prompt(self, siblings: list[dict] | None, can_go_back: bool) -> None:
        """Print the '0 to go back | Ctrl+C to quit' line."""
        back = self._depth > 1 or siblings or can_go_back
        label = "go back" if back else "exit"
        self.console.print(f"  [dim][bold]0[/bold] to {label} | Ctrl+C to quit[/dim]")

    @staticmethod
    def _neighbour(siblings: list[dict] | None, idx: int, step: int) -> int | None:
        """Index of the nearest navigable sibling in direction ``step``, or None."""
        if not siblings:
            return None
        i = idx + step
        while 0 <= i < len(siblings):
            if siblings[i].get("_type"):
                return i
            i += step
        return None

    def _sibling_hints(
        self,
        entity_type: str,
        siblings: list[dict] | None,
        idx: int,
    ) -> tuple[int | None, int | None]:
        """Print prev/next hints; return the (prev, next) navigable sibling indexes."""
        prev_idx = self._neighbour(siblings, idx, -1)
        next_idx = self._neighbour(siblings, idx, 1)
        hints = []
        if prev_idx is not None:
            hints.append(f"[bold]p[/bold]rev {escape(entity_type)}")
        if next_idx is not None:
            hints.append(f"[bold]n[/bold]ext {escape(entity_type)}")
        if hints:
            self.console.print(f"  [dim]{' | '.join(hints)}[/dim]")
        return prev_idx, next_idx

    def _sibling_step(
        self,
        raw: str,
        siblings: list[dict] | None,
        neighbours: tuple[int | None, int | None],
    ) -> tuple[int, dict | None] | None:
        """Handle n/p in an entity view.

        Returns None when ``raw`` is not a usable step, otherwise the target
        index and its entity, or None for the entity when the fetch failed (a
        message has been shown and the caller stays on the current entity).
        """
        prev_idx, next_idx = neighbours
        target = {"n": next_idx, "p": prev_idx}.get(raw)
        if target is None or not siblings:
            return None
        return target, self._resolve_item(siblings[target])

    def _auto_full_loop(
        self,
        entity: dict,
        *,
        siblings: list[dict] | None = None,
        sibling_index: int = 0,
        can_go_back: bool = False,
    ) -> None:
        """Display all sections inline, with optional prev/next navigation."""
        idx = sibling_index
        redraw = True

        while True:
            if redraw:
                defn = self.display.get_def(entity["_type"])
                for sec in defn.sections if defn else []:
                    self._load_lazy(entity, sec)
                    if entity.get(sec.key):
                        self.display.section(entity, sec.key)
            redraw = True

            self.console.print()
            neighbours = self._sibling_hints(entity["_type"], siblings, idx)
            self._back_prompt(siblings, can_go_back)

            raw = self._input("\n[bold]>[/bold] ")
            step = self._sibling_step(raw, siblings, neighbours)
            if step is None:
                return
            new_idx, sibling = step
            if not sibling:
                redraw = False
                continue
            idx, entity = new_idx, sibling
            self.display.header(entity)

    def _section_menu(
        self,
        entity: dict,
        *,
        siblings: list[dict] | None = None,
        sibling_index: int = 0,
        can_go_back: bool = False,
    ) -> None:
        """Interactive section menu with lazy fetching and header link navigation."""
        idx = sibling_index
        defn = self.display.get_def(entity["_type"])
        header_links = self.get_header_links(entity)

        while True:
            sections = defn.sections
            self.console.print()
            for i, sec in enumerate(sections, 1):
                suffix = " [dim]→[/dim]" if sec.navigable else ""
                if entity.get(sec.key) or sec.lazy:
                    self.console.print(f"  [bold cyan]\\[{i}][/bold cyan] {escape(sec.label)}{suffix}")
                else:
                    self.console.print(f"  [dim]\\[{i}] {escape(sec.label)} (empty)[/dim]")

            for j, (link_label, _link_type, _link_ref) in enumerate(header_links):
                menu_idx = len(sections) + 1 + j
                self.console.print(
                    f"  [bold cyan]\\[{menu_idx}][/bold cyan] {escape(link_label)} [dim]→[/dim]"
                )

            self.console.print()
            neighbours = self._sibling_hints(entity["_type"], siblings, idx)
            self._back_prompt(siblings, can_go_back)

            raw = self._input("\n[bold]Choose:[/bold] ")
            step = self._sibling_step(raw, siblings, neighbours)
            if step is not None:
                new_idx, sibling = step
                if sibling:
                    new_defn = self.display.get_def(sibling["_type"])
                    if not new_defn:
                        return
                    idx, entity, defn = new_idx, sibling, new_defn
                    header_links = self.get_header_links(entity)
                    self.display.header(entity)
                continue

            try:
                choice = int(raw)
            except ValueError:
                continue

            if choice == 0:
                return

            if 1 <= choice <= len(sections):
                sec = sections[choice - 1]
                if not self._load_lazy(entity, sec):
                    continue
                self.display.section(entity, sec.key)

                if sec.navigable:
                    items = self.get_navigable_items(entity["_type"], sec.key, entity)
                    if items:
                        n = len(items)
                        self._offer_navigation(
                            items,
                            title=sec.label,
                            page_size=n if n <= 100 else 25,
                            skip_render=bool(sec.columns),
                        )
                        self.display.header(entity)

            elif len(sections) < choice <= len(sections) + len(header_links):
                _, link_type, link_ref = header_links[choice - len(sections) - 1]
                target = self._fetch_or_report(link_type, link_ref)
                if target:
                    self.navigate(target)
                    self.display.header(entity)
            else:
                self.console.print("[red]Invalid choice.[/red]")

    def _offer_navigation(
        self,
        items: list[dict],
        *,
        title: str,
        page_size: int,
        skip_render: bool,
    ) -> None:
        """Paginated navigation through section items."""
        if not any(item.get("_type") for item in items):
            return

        page = 0
        total = len(items)
        total_pages = max(1, -(-total // page_size))

        def show_page() -> None:
            self.display.section_page(items, start=page * page_size, count=page_size)

        if not skip_render:
            self._rule(title)
            show_page()

        while True:
            start = page * page_size
            end = min(start + page_size, total)
            cmd = self._pager_prompt(
                page=page,
                total_pages=total_pages,
                status=f"Page {page + 1}/{total_pages} (items {start + 1}-{end} of {total})",
                select_hint=f"[bold]1-{total}[/bold] to select",
            )

            if isinstance(cmd, int):
                page = cmd
                show_page()
                continue

            if cmd == "0":
                return

            try:
                idx = int(cmd) - 1
            except ValueError:
                continue
            if not (0 <= idx < total):
                continue

            target = self._resolve_item(items[idx])
            if target:
                self.navigate(target, siblings=items, sibling_index=idx)
                self._rule(title)
                show_page()
