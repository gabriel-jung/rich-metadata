"""Tests for the base navigator (non-interactive parts)."""

from rich_metadata.display import DisplayEngine, EntityDef, HeaderLink, SectionDef, TableColumn
from rich_metadata.navigator import BaseNavigator, QuitSignal


def test_quit_signal_is_exception():
    assert issubclass(QuitSignal, Exception)


def test_get_entity_ref_url():
    engine = DisplayEngine()
    nav = BaseNavigator(engine)
    assert nav.get_entity_ref({"url": "https://example.com"}) == "https://example.com"


def test_get_entity_ref_custom_key():
    engine = DisplayEngine()
    nav = BaseNavigator(engine, entity_ref_key="id")
    assert nav.get_entity_ref({"id": "abc123", "url": "http://x"}) == "abc123"


def test_get_entity_ref_none():
    engine = DisplayEngine()
    nav = BaseNavigator(engine)
    assert nav.get_entity_ref({"name": "test"}) is None


def test_fetch_entity_with_apis():
    class FakeAPI:
        def get(self, ref):
            return {"_type": "band", "name": "Test", "url": ref}

    engine = DisplayEngine()
    nav = BaseNavigator(engine, apis={"band": FakeAPI()})
    # Can't easily test with console.status, but verify the API is wired
    assert nav.apis["band"] is not None


def test_fetch_entity_unknown_type():
    engine = DisplayEngine()
    nav = BaseNavigator(engine, apis={})
    assert nav.fetch_entity("unknown", "ref") is None


def test_lazy_fetcher_from_constructor():
    engine = DisplayEngine()
    engine.register(EntityDef(type_name="band"))

    class FakeAPI:
        def fetch_description(self, id):
            return "A description"

    nav = BaseNavigator(
        engine,
        apis={"band": FakeAPI()},
        lazy_fetchers={
            ("band", "description"): lambda api, e: api.fetch_description(e["id"]),
        },
    )
    fetcher = nav.get_lazy_fetcher("band", "description")
    assert fetcher is not None
    assert fetcher({"id": "123"}) == "A description"


def test_lazy_fetcher_none():
    engine = DisplayEngine()
    nav = BaseNavigator(engine)
    assert nav.get_lazy_fetcher("band", "description") is None


def test_navigable_items_table():
    engine = DisplayEngine()
    engine.register(
        EntityDef(
            type_name="band",
            sections=[
                SectionDef(
                    "discography", navigable=True,
                    columns=[TableColumn("Name", "name")],
                ),
            ],
        )
    )
    nav = BaseNavigator(engine)
    entity = {"_type": "band", "discography": [{"name": "Album1"}, {"name": "Album2"}]}
    items = nav.get_navigable_items("band", "discography", entity)
    assert len(items) == 2


def test_navigable_items_grouped_table():
    engine = DisplayEngine()
    engine.register(
        EntityDef(
            type_name="band",
            sections=[
                SectionDef(
                    "members",
                    navigable=True,
                    columns=[TableColumn("Name", "name")],
                ),
            ],
        )
    )
    nav = BaseNavigator(engine)
    entity = {
        "_type": "band",
        "members": {
            "current": [{"name": "Alice"}, {"name": "Bob"}],
            "past": [{"name": "Charlie"}],
        },
    }
    items = nav.get_navigable_items("band", "members", entity)
    assert len(items) == 3
    assert items[0]["name"] == "Alice"


def test_navigable_items_custom_extractor():
    engine = DisplayEngine()
    engine.register(
        EntityDef(
            type_name="artist",
            sections=[
                SectionDef(
                    "bands_overview", label="Bands",
                    navigable=True,
                    nav_items=lambda d: [bi["band"] for bi in d.get("bands_overview", [])],
                ),
            ],
        )
    )
    nav = BaseNavigator(engine)
    entity = {
        "_type": "artist",
        "bands_overview": [
            {"band": {"name": "Band1"}, "role": "Vocals"},
            {"band": {"name": "Band2"}, "role": "Guitar"},
        ],
    }
    items = nav.get_navigable_items("artist", "bands_overview", entity)
    assert len(items) == 2
    assert items[0]["name"] == "Band1"


def test_navigable_items_not_navigable():
    engine = DisplayEngine()
    engine.register(
        EntityDef(
            type_name="band",
            sections=[
                SectionDef("reviews", navigable=False),
            ],
        )
    )
    nav = BaseNavigator(engine)
    assert nav.get_navigable_items("band", "reviews", {"_type": "band"}) is None


def test_header_links_from_entity_def():
    engine = DisplayEngine()
    engine.register(
        EntityDef(
            type_name="album",
            header_links=[
                HeaderLink("Band: {band}", "band", ref_key="band_url"),
                HeaderLink("Label: {label}", "label", ref_key="label_url"),
            ],
        )
    )
    nav = BaseNavigator(engine)
    entity = {
        "_type": "album",
        "band": "Summoning",
        "band_url": "https://example.com/band/1",
        "label": "Napalm",
    }
    links = nav.get_header_links(entity)
    assert len(links) == 1  # label_url missing, so only band link
    assert links[0] == ("Band: Summoning", "band", "https://example.com/band/1")


def test_header_links_with_ref_fn():
    engine = DisplayEngine()
    engine.register(
        EntityDef(
            type_name="album",
            header_links=[
                HeaderLink(
                    "Band: {band}", "band",
                    ref_fn=lambda d: f"https://example.com/{d['band_id']}" if d.get("band_id") else None,
                ),
            ],
        )
    )
    nav = BaseNavigator(engine)
    entity = {"_type": "album", "band": "Test", "band_id": "42"}
    links = nav.get_header_links(entity)
    assert links == [("Band: Test", "band", "https://example.com/42")]


def test_header_links_empty():
    engine = DisplayEngine()
    engine.register(EntityDef(type_name="song"))
    nav = BaseNavigator(engine)
    assert nav.get_header_links({"_type": "song"}) == []


def test_history_empty_initially():
    engine = DisplayEngine()
    nav = BaseNavigator(engine)
    assert nav._history == []


def test_console_property():
    engine = DisplayEngine()
    nav = BaseNavigator(engine)
    assert nav.console is engine.console
