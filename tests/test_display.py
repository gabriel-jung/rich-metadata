"""Tests for the display engine."""

from io import StringIO

from rich.console import Console

from rich_metadata.display import (
    DisplayEngine,
    EntityDef,
    HeaderField,
    SectionDef,
    SummaryField,
    TableColumn,
    format_duration,
    info_grid,
    parse_duration,
)


def _make_console() -> Console:
    return Console(file=StringIO(), force_terminal=True, width=120)


def _capture(console: Console) -> str:
    console.file.seek(0)
    return console.file.read()


# ── Duration helpers ─────────────────────────────────────────────────────


class TestParseDuration:
    def test_mm_ss(self):
        assert parse_duration("3:45") == 225

    def test_h_mm_ss(self):
        assert parse_duration("1:02:30") == 3750

    def test_invalid(self):
        assert parse_duration("abc") is None

    def test_empty(self):
        assert parse_duration("") is None

    def test_single_part(self):
        assert parse_duration("42") is None


class TestFormatDuration:
    def test_mm_ss(self):
        assert format_duration(225) == "3:45"

    def test_h_mm_ss(self):
        assert format_duration(3750) == "1:02:30"

    def test_zero(self):
        assert format_duration(0) == "0:00"


# ── Info grid ────────────────────────────────────────────────────────────


def test_info_grid_filters_empty():
    grid = info_grid([("A", "hello"), ("B", ""), ("C", "world")])
    assert grid.row_count == 2


# ── DisplayEngine ────────────────────────────────────────────────────────


def _band_def() -> EntityDef:
    return EntityDef(
        type_name="band",
        summary=[
            SummaryField(key="name", style="bold"),
            SummaryField(key="country", style="dim", fallback="Unknown"),
            SummaryField(key="genre"),
        ],
        header_fields=[
            HeaderField("Status", "status"),
            HeaderField("Genre", "genre"),
            HeaderField("Origin", transform=lambda d: d.get("country", "")),
        ],
        header_image_key="_logo_data",
        sections=[
            SectionDef(
                "discography", navigable=True,
                columns=[
                    TableColumn("Year", "year", width=6),
                    TableColumn("Title", "name", style="bold"),
                    TableColumn("Type", "type"),
                ],
            ),
            SectionDef("description", lazy=True),
            SectionDef(
                "members",
                columns=[
                    TableColumn("Name", "name", style="bold"),
                    TableColumn("Role", "role"),
                ],
            ),
        ],
        footer=["url"],
    )


def _make_engine() -> tuple[DisplayEngine, Console]:
    console = _make_console()
    engine = DisplayEngine(console)
    engine.register(_band_def())
    return engine, console


class TestSummary:
    def test_renders_fields(self):
        engine, console = _make_engine()
        entity = {"_type": "band", "name": "Summoning", "country": "AT", "genre": "Epic Black Metal"}
        engine.summary(entity)
        output = _capture(console)
        assert "Summoning" in output
        assert "AT" in output
        assert "Epic Black Metal" in output

    def test_fallback(self):
        engine, console = _make_engine()
        entity = {"_type": "band", "name": "Test"}
        engine.summary(entity)
        output = _capture(console)
        assert "Unknown" in output

    def test_unknown_type(self):
        engine, console = _make_engine()
        entity = {"_type": "unknown", "name": "Foo"}
        engine.summary(entity)
        output = _capture(console)
        assert "Foo" in output


class TestHeader:
    def test_renders_panel(self):
        engine, console = _make_engine()
        entity = {
            "_type": "band",
            "name": "Summoning",
            "status": "Active",
            "genre": "Epic Black Metal",
            "country": "Austria",
            "url": "https://example.com",
        }
        engine.header(entity)
        output = _capture(console)
        assert "Summoning" in output
        assert "Active" in output
        assert "Epic Black Metal" in output
        assert "https://example.com" in output

    def test_entity_transform(self):
        engine, console = _make_engine()
        entity = {"_type": "band", "name": "Test", "country": "Norway"}
        engine.header(entity)
        output = _capture(console)
        assert "Norway" in output


class TestTableSection:
    def test_renders_table(self):
        engine, console = _make_engine()
        entity = {
            "_type": "band",
            "name": "Test",
            "discography": [
                {"name": "Album One", "year": "1999", "type": "Full-length"},
                {"name": "Album Two", "year": "2003", "type": "EP"},
            ],
        }
        engine.section(entity, "discography")
        output = _capture(console)
        assert "Album One" in output
        assert "1999" in output
        assert "Album Two" in output

    def test_empty_section(self):
        engine, console = _make_engine()
        entity = {"_type": "band", "name": "Test", "discography": []}
        engine.section(entity, "discography")
        output = _capture(console)
        assert output.strip() == ""


class TestGroupedTable:
    def test_renders_groups(self):
        engine, console = _make_engine()
        entity = {
            "_type": "band",
            "name": "Test",
            "members": {
                "Current": [
                    {"name": "Alice", "role": "Vocals"},
                    {"name": "Bob", "role": "Guitar"},
                ],
                "Past": [
                    {"name": "Charlie", "role": "Bass"},
                ],
            },
        }
        engine.section(entity, "members")
        output = _capture(console)
        assert "Alice" in output
        assert "Bob" in output
        assert "Charlie" in output
        assert "Current" in output
        assert "Past" in output


class TestTextSection:
    def test_renders_text(self):
        engine, console = _make_engine()
        entity = {
            "_type": "band",
            "name": "Test",
            "description": "A great band from the north.",
        }
        engine.section(entity, "description")
        output = _capture(console)
        assert "A great band from the north." in output

    def test_missing_text(self):
        engine, console = _make_engine()
        entity = {"_type": "band", "name": "Test"}
        engine.section(entity, "description")
        output = _capture(console)
        assert "not available" in output.lower() or "no description" in output.lower()


class TestDetails:
    def test_renders_header_and_non_lazy_sections(self):
        engine, console = _make_engine()
        entity = {
            "_type": "band",
            "name": "Summoning",
            "status": "Active",
            "genre": "Epic",
            "country": "AT",
            "discography": [
                {"name": "Oath Bound", "year": "2006", "type": "Full-length"},
            ],
            "members": {
                "Current": [{"name": "Silenius", "role": "Vocals"}],
            },
        }
        engine.details(entity)
        output = _capture(console)
        assert "Summoning" in output
        assert "Oath Bound" in output
        assert "Silenius" in output
        # description is lazy and not fetched, should not appear
        assert "not available" not in output.lower()

    def test_lazy_section_rendered_when_data_present(self):
        engine, console = _make_engine()
        entity = {
            "_type": "band",
            "name": "Summoning",
            "status": "Active",
            "genre": "Epic",
            "country": "AT",
            "discography": [],
            "description": "Austrian atmospheric black metal duo.",
        }
        engine.details(entity)
        output = _capture(console)
        assert "Austrian atmospheric black metal duo." in output

    def test_lazy_section_skipped_when_no_data(self):
        engine, console = _make_engine()
        entity = {
            "_type": "band",
            "name": "Summoning",
            "status": "Active",
            "genre": "Epic",
            "country": "AT",
        }
        engine.details(entity)
        output = _capture(console)
        # Lazy description not fetched — should not show "no description available"
        assert "no description" not in output.lower()


class TestDurationTotal:
    def test_total_shown(self):
        console = _make_console()
        engine = DisplayEngine(console)
        engine.register(
            EntityDef(
                type_name="album",
                sections=[
                    SectionDef(
                        "tracklist", duration_key="duration",
                        columns=[
                            TableColumn("Title", "name"),
                            TableColumn("Duration", "duration", justify="right"),
                        ],
                    ),
                ],
            )
        )
        entity = {
            "_type": "album",
            "tracklist": [
                {"name": "Track 1", "duration": "3:00"},
                {"name": "Track 2", "duration": "4:30"},
            ],
        }
        engine.section(entity, "tracklist")
        output = _capture(console)
        assert "7:30" in output
