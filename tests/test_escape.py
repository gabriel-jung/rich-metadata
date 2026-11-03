"""Data values must print as written, whatever brackets or control bytes they hold."""

from io import StringIO

from rich.console import Console

from rich_metadata import escape
from rich_metadata.display import (
    DisplayEngine,
    EntityDef,
    HeaderField,
    SectionDef,
    SummaryField,
    TableColumn,
)


def _engine(*defs):
    engine = DisplayEngine(Console(file=StringIO(), width=120))
    engine.register(*defs)
    return engine


def _out(engine) -> str:
    return engine.console.file.getvalue()


ALBUM = EntityDef(
    type_name="album",
    summary=[SummaryField(key="name", style="bold"), SummaryField(key="year", fallback="n/a")],
    header_fields=[
        HeaderField("Label", key="label"),
        HeaderField("Note", transform=lambda d: "[bold]ok[/bold]"),
    ],
    sections=[
        SectionDef("tracks", columns=[TableColumn("Title", "title")], group_key="disc"),
        SectionDef("notes"),
    ],
    footer=["url"],
)

TRICKY = "Live [bonus] / Split [w/ Foo] [/]"


def test_escape_keeps_text_and_drops_control_characters():
    escaped = escape("a [b] \x1b]52;c;evil\x07 c\nd\te")
    assert "\x1b" not in escaped and "\x07" not in escaped
    assert "\nd\te" in escaped  # newline and tab survive
    console = Console(file=StringIO(), width=120)
    console.print(escaped)
    assert "a [b] ]52;c;evil c" in console.file.getvalue()


def test_summary_header_table_text_and_footer_print_brackets_literally():
    entity = {
        "_type": "album",
        "name": TRICKY,
        "label": "[red]Label[/red]",
        "url": "https://x.test/[1]",
        "tracks": [{"title": TRICKY, "disc": "[cd 1]"}],
        "notes": "Recorded [live]",
    }
    engine = _engine(ALBUM)
    engine.summary(entity)
    engine.details(entity)
    out = _out(engine)
    assert out.count(TRICKY) >= 3  # summary, panel title, table cell
    assert "[red]Label[/red]" in out
    assert "https://x.test/[1]" in out
    assert "Recorded [live]" in out
    assert "[cd 1]" in out


def test_transform_output_is_still_markup():
    engine = _engine(ALBUM)
    engine.header({"_type": "album", "name": "X"})
    out = _out(engine)
    assert "ok" in out and "[bold]ok" not in out


def test_fallback_is_shown_when_value_missing():
    engine = _engine(ALBUM)
    engine.summary({"_type": "album", "name": "X"})
    assert "n/a" in _out(engine)


def test_unregistered_entity_name_is_escaped():
    engine = _engine()
    engine.summary({"_type": "other", "name": "[/]"})
    assert "[/]" in _out(engine)
