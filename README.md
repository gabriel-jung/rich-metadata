# rich-metadata

A Rich-based TUI toolkit for building metadata browsers.

Provides the shared display and navigation layer behind packages like [pymetallum](https://github.com/gabriel-jung/pymetallum). Define your entities declaratively, wire up your API, and get an interactive terminal browser with pagination, navigation, lazy loading, and image support.

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
band_def = EntityDef(
    type_name="band",
    summary=[
        SummaryField(key="name", style="bold"),
        SummaryField(key="country", style="dim"),
        SummaryField(key="genre"),
    ],
    header_fields=[
        HeaderField("Status", "status"),
        HeaderField("Genre", "genre"),
        HeaderField("Origin", transform=lambda d: d.get("country", "")),
    ],
    sections=[
        SectionDef(
            key="discography",
            label="Discography",
            navigable=True,
            columns=[
                TableColumn("Year", "year", width=6),
                TableColumn("Title", "name", style="bold"),
                TableColumn("Type", "type"),
            ],
        ),
        SectionDef(
            key="members",
            label="Members",
            columns=[
                TableColumn("Name", "name", style="bold"),
                TableColumn("Role", "role"),
            ],
        ),
        SectionDef(
            key="bio",
            label="Biography",
            lazy=True,
        ),
    ],
    header_links=[
        HeaderLink("Label: {label}", "label", ref_key="label_url"),
    ],
    footer=["url"],
)

# 2. Create a display engine and register definitions
engine = DisplayEngine()
engine.register(band_def)

# 3. Use the engine directly
entity = {"_type": "band", "name": "Summoning", "genre": "Epic Black Metal", ...}
engine.details(entity)    # render header + all sections
engine.summary(entity)    # one-line summary
engine.header(entity)     # header panel with image

# 4. Or wire up a navigator for interactive browsing
class MyAPI:
    def get(self, ref: str) -> dict:
        ...  # fetch entity by URL/ID, return dict with "_type" key

navigator = BaseNavigator(
    engine,
    apis={"band": MyAPI(), "album": MyAPI()},
    entity_ref_key="url",
    lazy_fetchers={
        ("band", "bio"): lambda api, entity: api.fetch_bio(entity["id"]),
    },
)
navigator.navigate(entity)  # interactive section menu
navigator.browse(fetch_page=my_search_fn)  # paginated results
```

## Core concepts

### Entity dicts

Entities are plain Python dicts with a `_type` key for routing:

```python
{"_type": "album", "name": "Minas Morgul", "band": "Summoning", "year": "1995"}
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

- Has `columns` → **table** (if data is a `list`, rows are flat; if `dict[str, list]`, rows are grouped with headers — e.g. "Current"/"Past" members, or "Disc 1"/"Disc 2" tracks)
- Has `custom_render` → **custom** rendering function
- Neither → **text** panel

Key options: `navigable` (items can be drilled into), `lazy` (fetched on demand), `duration_key` (sums and shows total duration for tracklists).

### SummaryField

One segment of a one-line entity summary. Supports `style`, `prefix` (text before the value), `fallback` (shown when key is missing), and `transform` (receives value if `key` is set, or the whole entity dict if not).

### HeaderField

A labeled row in the detail panel. Either reads from `key` directly, or computes via `transform` (receives value if `key` is set, or the whole entity dict if not).

### TableColumn

A column in a table section. Supports `style`, `justify`, `width`, and `transform`.

### HeaderLink

A navigable link shown in the section menu (e.g., "Band: Summoning →"). Uses `ref_key` to read a URL/ID from the entity dict, or `ref_fn(entity) -> str | None` for computed refs.

## DisplayEngine

The rendering engine. Key methods:

```python
engine = DisplayEngine()              # uses default Rich console
engine = DisplayEngine(my_console)    # custom console

engine.register(entity_def)           # register an EntityDef
engine.summary(entity)                # one-line summary
engine.header(entity)                 # detail panel with optional image
engine.section(entity, "discography") # render a single section
engine.details(entity)                # header + all non-lazy sections
engine.select_from_list(items)        # numbered selection prompt
```

## BaseNavigator

Interactive browser with pagination, back-navigation, and lazy fetching.

```python
navigator = BaseNavigator(
    engine,
    apis={"band": band_api, "album": album_api},
    entity_ref_key="url",
    lazy_fetchers={
        ("band", "description"): lambda api, entity: api.fetch_desc(entity["id"]),
    },
)
```

| Parameter | Purpose |
|-----------|---------|
| `apis` | `{type: api}` — each API must have a `.get(ref)` method |
| `entity_ref_key` | Key to extract the navigable ref from item dicts (default: `"url"`) |
| `lazy_fetchers` | `{(type, section): callable(api, entity) -> data}` for lazy sections |

Key methods:

- **`navigate(entity)`** — Interactive loop: shows header, section menu, lazy fetching, header link navigation, and back-navigation.
- **`browse(fetch_page=..., ...)`** — Paginated results with selection. `fetch_page(start, count)` returns `(results, total)`.

Items with `_type` but no ref (no `url` or whatever `entity_ref_key` is) are treated as **inline entities** — they are navigated directly without fetching. This is useful for items that already contain all their data or use lazy sections to load additional content.

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
