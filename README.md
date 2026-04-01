# rich-metadata

A Rich-based TUI toolkit for building interactive metadata browsers.

Define your entities declaratively, wire up your API, and get an interactive terminal browser with pagination, navigation, lazy loading, and image support.

## Install

```bash
pip install rich-metadata
```

## Quick start

```python
from rich_metadata import (
    BaseNavigator,
    DisplayEngine,
    EntityDef,
    HeaderField,
    HeaderLink,
    SectionDef,
    SummaryField,
    TableColumn,
)

# 1. Define your entities
book_def = EntityDef(
    type_name="book",
    summary=[
        SummaryField(key="title", style="bold"),
        SummaryField(prefix="by ", key="author"),
        SummaryField(key="year", style="dim"),
    ],
    header_fields=[
        HeaderField("Author", key="author"),
        HeaderField("Year", key="year"),
        HeaderField("Genre", key="genre"),
        HeaderField("Pages", key="pages"),
        HeaderField("Publisher", key="publisher"),
    ],
    sections=[
        SectionDef(
            "chapters",
            navigable=True,
            columns=[
                TableColumn("#", "number", width=4),
                TableColumn("Title", "title", style="bold"),
                TableColumn("Pages", "pages"),
            ],
        ),
        SectionDef("description", lazy=True),
    ],
    header_links=[
        HeaderLink("Author: {author}", "author", ref_key="author_url"),
    ],
    footer=["url"],
)

# 2. Create a display engine and register definitions
engine = DisplayEngine()
engine.register(book_def)

# 3. Use the engine directly
entity = {"_type": "book", "title": "Dune", "author": "Frank Herbert", "year": "1965"}
engine.details(entity)    # render header + all sections
engine.summary(entity)    # one-line summary
engine.header(entity)     # header panel with image

# 4. Or wire up a navigator for interactive browsing
class BookAPI:
    def get(self, ref: str) -> dict:
        ...  # fetch entity by URL/ID, return dict with "_type" key

    def search(self, query: str) -> list[dict]:
        ...  # return list of entity dicts

navigator = BaseNavigator(
    engine,
    apis={"book": BookAPI(), "author": AuthorAPI()},
    entity_ref_key="url",
    lazy_fetchers={
        ("book", "description"): lambda api, entity: api.fetch_description(entity["id"]),
    },
)
navigator.navigate(entity)  # interactive section menu
navigator.browse(fetch_page=my_search_fn)  # paginated results
```

## Core concepts

### Entity dicts

Entities are plain Python dicts with a `_type` key for routing:

```python
{"_type": "book", "title": "Dune", "author": "Frank Herbert", "year": "1965"}
```

### EntityDef

Declares how an entity type is displayed. Each `EntityDef` configures:

| Field | Purpose |
|-------|---------|
| `type_name` | Entity type identifier (matches `_type` in dicts) |
| `summary` | One-line display fields (`SummaryField` list) |
| `header_fields` | Key-value pairs in the detail panel (`HeaderField` list) |
| `header_image_key` | Dict key holding image bytes for the header panel |
| `header_title` | Custom title callable `(dict) -> str` |
| `panel_border_style` | Rich style for the header panel border |
| `sections` | Expandable content sections (`SectionDef` list) |
| `header_links` | Navigable links shown in the section menu (`HeaderLink` list) |
| `footer` | Keys (strings) or callables for lines below the panel |

### SectionDef

Defines a content section. The rendering mode is auto-detected:

- Has `columns` -> **table** (if data is a `list`, rows are flat; if `dict[str, list]`, rows are grouped with headers)
- Has `custom_render` -> **custom** rendering function
- Neither -> **text** panel

Key options: `navigable` (items can be drilled into), `lazy` (fetched on demand), `duration_key` (sums and shows total duration).

### SummaryField

One segment of a one-line entity summary. Supports `style`, `prefix` (text before the value), `fallback` (shown when key is missing), and `transform` (receives value if `key` is set, or the whole entity dict if not).

### HeaderField

A labeled row in the detail panel. Either reads from `key` directly, or computes via `transform` (receives value if `key` is set, or the whole entity dict if not).

### TableColumn

A column in a table section. Supports `style`, `justify`, `width`, and `transform`.

### HeaderLink

A navigable link shown in the section menu (e.g., "Author: Frank Herbert ->"). Uses `ref_key` to read a URL/ID from the entity dict, or `ref_fn(entity) -> str | None` for computed refs.

## DisplayEngine

The rendering engine. Key methods:

```python
engine = DisplayEngine()              # uses default Rich console
engine = DisplayEngine(my_console)    # custom console

engine.register(entity_def)           # register an EntityDef
engine.summary(entity)                # one-line summary
engine.header(entity)                 # detail panel with optional image
engine.section(entity, "chapters")    # render a single section
engine.details(entity)                # header + all non-lazy sections
engine.select_from_list(items)        # numbered selection prompt
```

## BaseNavigator

Interactive browser with pagination, back-navigation, and lazy fetching.

```python
navigator = BaseNavigator(
    engine,
    apis={"book": book_api, "author": author_api},
    entity_ref_key="url",
    lazy_fetchers={
        ("book", "description"): lambda api, entity: api.fetch_desc(entity["id"]),
    },
)
```

| Parameter | Purpose |
|-----------|---------|
| `apis` | `{type: api}` -- each API must have a `.get(ref)` method |
| `entity_ref_key` | Key to extract the navigable ref from item dicts (default: `"url"`) |
| `lazy_fetchers` | `{(type, section): callable(api, entity) -> data}` for lazy sections |

Key methods:

- **`navigate(entity)`** -- Interactive loop: shows header, section menu, lazy fetching, header link navigation, and back-navigation.
- **`search_and_navigate(query, types)`** -- Search, select from results, and navigate. Re-shows the results list on back.
- **`browse(fetch_page=..., ...)`** -- Paginated results with selection. `fetch_page(start, count)` returns `(results, total)`.
- **`browse_sources(sources)`** -- Pick from named browsable sources, then browse the selected one.

Items with `_type` but no ref (no `url` or whatever `entity_ref_key` is) are treated as **inline entities** -- navigated directly without fetching.

## CLI helpers

Shared CLI utilities:

```python
from rich_metadata import (
    configure_logging,     # loguru setup (debug if verbose, else warnings)
    resolve_entity_type,   # extract (type, query) from parsed args
    strip_internal_keys,   # remove _prefixed keys for JSON output
    list_fetcher,          # wrap a list into a fetch_page callable for browse()
    page_fetcher,          # adapt page-number APIs to browse()'s offset interface
    parse_date,            # parse 'YYYY-MM-DD' string to date
    parse_date_args,       # parse --from/--to argparse flags into dates
    months_in_range,       # list of 'YYYY-MM' strings covering a date range
)
```

`list_fetcher` and `page_fetcher` are adapters for `BaseNavigator.browse()`:

```python
# Wrap a pre-fetched list
navigator.browse(fetch_page=list_fetcher(my_items))

# Adapt a page-number API (fetch(page) -> (results, has_more))
navigator.browse(fetch_page=page_fetcher(api.search, first_page=initial_results))
```

## Image support

Terminal image rendering for iTerm2 and Kitty:

```python
from rich_metadata import get_image_escape, show_image_beside

# Get raw escape sequence for image bytes
escape = get_image_escape(image_bytes, width=20, height=10)

# Show an image beside a Rich renderable
show_image_beside(console, image_bytes, my_panel, img_width=20)
```

## Duration helpers

```python
from rich_metadata import parse_duration, format_duration

parse_duration("3:45")      # 225 (seconds)
parse_duration("1:02:30")   # 3750
format_duration(225)         # "3:45"
format_duration(3750)        # "1:02:30"
```

## License

MIT
