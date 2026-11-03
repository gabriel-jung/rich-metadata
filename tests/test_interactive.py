"""Scripted-input tests for the navigator's interactive loops."""

from io import StringIO

import pytest
from rich.console import Console

from rich_metadata.display import (
    DisplayEngine,
    EntityDef,
    HeaderField,
    HeaderLink,
    SectionDef,
    TableColumn,
)
from rich_metadata.navigator import BaseNavigator, QuitSignal


class Script:
    """Feeds prompt answers in order and fails if the loop asks for more."""

    def __init__(self, *answers: str):
        self.answers = list(answers)

    def __call__(self, prompt: str = "") -> str:
        if not self.answers:
            raise AssertionError(f"unexpected extra prompt: {prompt!r}")
        return self.answers.pop(0)

    @property
    def done(self) -> bool:
        return not self.answers


class FakeAPI:
    """Records get() calls; ``entities`` maps ref -> entity (missing -> None)."""

    def __init__(self, entities=None, results=None, error=None):
        self.entities = entities or {}
        self.results = results or []
        self.error = error
        self.calls = []

    def get(self, ref, **kwargs):
        self.calls.append((ref, kwargs))
        if self.error:
            raise self.error
        return self.entities.get(ref)

    def search(self, query, exact_match=True):
        return list(self.results)


def band(name, ref=None, **extra):
    entity = {"_type": "band", "name": name, **extra}
    if ref:
        entity["url"] = ref
    return entity


def make_nav(*answers, api=None, defs=(), **kwargs):
    engine = DisplayEngine(Console(file=StringIO(), width=120))
    engine.register(*defs)
    script = Script(*answers)
    engine.console.input = script
    nav = BaseNavigator(engine, apis={"band": api} if api else {}, **kwargs)
    return nav, script


def output(nav) -> str:
    return nav.console.file.getvalue()


BAND_DEF = EntityDef(
    type_name="band",
    header_fields=[HeaderField("Genre", key="genre")],
    sections=[
        SectionDef(
            "albums",
            navigable=True,
            columns=[TableColumn("Title", "name")],
        ),
        SectionDef("bio", lazy=True),
    ],
)


def pages(items, total=None, empty_from=None, calls=None):
    """fetch_page over ``items``; ``total`` may overstate; pages at ``empty_from`` on are empty."""

    def fetch(start, count):
        if calls is not None:
            calls.append(start)
        if empty_from is not None and start >= empty_from:
            return [], total if total is not None else len(items)
        return items[start : start + count], total if total is not None else len(items)

    return fetch


# ── search_and_navigate ──────────────────────────────────────────────────


def test_single_result_back_ends_the_search():
    api = FakeAPI(entities={"u1": band("Solo", "u1")}, results=[band("Solo", "u1")])
    nav, script = make_nav("0", api=api, defs=[BAND_DEF])
    nav.search_and_navigate("solo", ["band"])
    assert script.done
    assert len(api.calls) == 1
    assert "0 to exit" in output(nav)


def test_single_result_failed_fetch_returns_instead_of_looping():
    api = FakeAPI(entities={}, results=[band("Gone", "u1")])
    nav, _ = make_nav(api=api, defs=[BAND_DEF])  # no answers: any prompt fails
    assert nav.search_and_navigate("gone", ["band"]) is False
    assert len(api.calls) == 1
    assert "Could not fetch details." in output(nav)


def test_search_passes_full_only_when_asked():
    api = FakeAPI(entities={"u1": band("Solo", "u1")}, results=[band("Solo", "u1")])
    nav, _ = make_nav("0", api=api, defs=[BAND_DEF])
    nav.search_and_navigate("solo", ["band"])
    nav.search_and_navigate("solo", ["band"], full=True)
    assert [kwargs for _, kwargs in api.calls] == [{}, {"full": True}]


def test_search_query_with_brackets_does_not_break_the_status_line():
    api = FakeAPI(results=[])
    nav, _ = make_nav(api=api)
    nav.search_and_navigate("[/]", ["band"])
    assert "No items found" in output(nav)


# ── browse ───────────────────────────────────────────────────────────────


def test_browse_full_forwards_full():
    api = FakeAPI(entities={"u1": band("A", "u1")})
    nav, script = make_nav("1", api=api, defs=[BAND_DEF])
    nav.browse(fetch_page=pages([band("A", "u1")]), full=True)
    assert script.done
    assert api.calls == [("u1", {"full": True})]


def test_browse_interactive_does_not_pass_full():
    api = FakeAPI(entities={"u1": band("A", "u1")})
    nav, script = make_nav("1", "0", api=api, defs=[BAND_DEF])
    nav.browse(fetch_page=pages([band("A", "u1")]))
    assert script.done
    assert api.calls == [("u1", {})]


def test_browse_last_lands_on_a_page_boundary():
    calls = []
    items = [band(f"B{i}") for i in range(60)]
    nav, script = make_nav("l", "n", "0", defs=[BAND_DEF])
    nav.browse(fetch_page=pages(items, calls=calls), page_size=25)
    assert script.done
    assert calls == [0, 50]  # 'n' on the last page is not offered, so it fetches nothing
    assert "Page 3/3 (51-60 of 60)" in output(nav)


def test_browse_short_page_caps_the_total():
    calls = []
    items = [band(f"B{i}") for i in range(30)]
    nav, script = make_nav("n", "0", defs=[BAND_DEF])
    nav.browse(fetch_page=pages(items, total=100, calls=calls), page_size=25)
    assert script.done
    assert calls == [0, 25]
    assert "Page 2/2 (26-30 of 30)" in output(nav)  # no third fetch, no phantom total


def test_browse_empty_page_clamp_survives_later_pages():
    calls = []
    items = [band(f"B{i}") for i in range(50)]
    # Claims 100, serves exactly two full pages. Each empty page lowers the cap; pages fetched
    # later (which still claim 100) must not lift it again.
    nav, script = make_nav("l", "n", "l", "f", "l", "0", defs=[BAND_DEF])
    nav.browse(fetch_page=pages(items, total=100, empty_from=50, calls=calls), page_size=25)
    assert script.done
    assert calls == [0, 75, 25, 50, 0, 25]  # the last 'l' stops at the page that exists


def test_browse_empty_page_stays_on_the_current_page():
    calls = []
    items = [band(f"B{i}") for i in range(50)]
    nav, script = make_nav("n", "n", "0", defs=[BAND_DEF])
    # Claims 75, serves two full pages: the third comes back empty.
    nav.browse(fetch_page=pages(items, total=75, empty_from=50, calls=calls), page_size=25)
    assert script.done
    assert calls == [0, 25, 50]
    out = output(nav)
    assert "No more results." in out
    assert "Page 2/2" in out  # total clamped to what was actually served


def test_browse_survives_a_fetch_that_raises():
    api = FakeAPI(error=RuntimeError("blocked"))
    nav, script = make_nav("1", "0", api=api, defs=[BAND_DEF])
    nav.browse(fetch_page=pages([band("A", "u1")]))
    assert script.done
    assert "Could not fetch details." in output(nav)


def test_ctrl_c_during_a_fetch_is_a_quit_signal():
    api = FakeAPI(error=KeyboardInterrupt())
    nav, _ = make_nav("1", api=api, defs=[BAND_DEF])
    with pytest.raises(QuitSignal):
        nav.browse(fetch_page=pages([band("A", "u1")]))


def test_browse_page_fetch_that_raises_keeps_the_list():
    def fetch(start, count):
        if start:
            raise RuntimeError("timeout")
        return [band(f"B{i}") for i in range(25)], 50

    nav, script = make_nav("n", "0", defs=[BAND_DEF])
    nav.browse(fetch_page=fetch, page_size=25)
    assert script.done
    assert "Could not load that page." in output(nav)


def test_browse_sources_returns_to_the_list_after_an_item():
    inline = {"_type": "band", "name": "Inline"}  # no ref: shown without fetching
    sources = [("New", pages([inline])), ("Old", pages([inline]))]
    # source 1, item 1 (no def, so navigate returns at once), back to list, back to menu, exit
    nav, script = make_nav("1", "1", "0", "0")
    nav.browse_sources(sources)
    assert script.done


# ── entity views ─────────────────────────────────────────────────────────


def test_sibling_step_skips_non_navigable_and_stays_on_failed_fetch():
    a = band("Alpha")
    siblings = [a, {"name": "plain row"}, band("Gamma", "u3")]
    api = FakeAPI(entities={})  # u3 cannot be fetched
    nav, script = make_nav("n", "0", api=api, defs=[BAND_DEF])
    nav.navigate(a, siblings=siblings, sibling_index=0)
    assert script.done
    assert api.calls == [("u3", {})]  # the untyped row was skipped
    assert "Could not fetch details." in output(nav)


def test_sibling_step_moves_to_the_next_entity():
    a = band("Alpha")
    siblings = [a, band("Gamma", "u3")]
    api = FakeAPI(entities={"u3": band("Gamma", "u3")})
    nav, script = make_nav("n", "0", api=api, defs=[BAND_DEF])
    nav.navigate(a, siblings=siblings, sibling_index=0)
    assert script.done
    assert "Gamma" in output(nav)


def test_section_list_selection_reports_a_failed_fetch():
    entity = band("Alpha", albums=[{"_type": "band", "name": "Dead", "url": "u9"}])
    api = FakeAPI(entities={})
    # section 1, item 1 (fails), back out of the list, exit
    nav, script = make_nav("1", "1", "0", "0", api=api, defs=[BAND_DEF])
    nav.navigate(entity)
    assert script.done
    assert "Could not fetch details." in output(nav)


def test_lazy_fetcher_that_raises_is_reported_and_the_menu_stays():
    def boom(api, entity):
        raise RuntimeError("timeout")

    api = FakeAPI()
    nav, script = make_nav(
        "2",
        "0",
        api=api,
        defs=[BAND_DEF],
        lazy_fetchers={("band", "bio"): boom},
    )
    nav.navigate(band("Alpha"))
    assert script.done
    assert "Could not fetch Bio." in output(nav)


def test_fetch_entity_lets_errors_reach_direct_callers():
    class Blocked(Exception):
        pass

    nav, _ = make_nav(api=FakeAPI(error=Blocked("challenge")))
    with pytest.raises(Blocked):
        nav.fetch_entity("band", "u1")


def test_search_row_without_ref_is_not_navigable():
    api = FakeAPI(results=[band("No link"), band("Other")])
    nav, script = make_nav("1", api=api, defs=[BAND_DEF])
    assert nav.search_and_navigate("x", ["band"], json_output=True) is False
    assert script.done
    assert api.calls == []
    assert "not navigable" in output(nav)


@pytest.mark.parametrize("answer", ["-1", "-3", "99"])
def test_out_of_range_menu_choices_are_rejected(answer):
    linked = EntityDef(
        type_name="band",
        sections=[SectionDef("bio")],
        header_links=[HeaderLink("Label: {label}", "band", ref_key="label_url")],
    )
    api = FakeAPI()
    nav, script = make_nav(answer, "0", api=api, defs=[linked])
    nav.navigate(band("Alpha", label="L", label_url="u2"))
    assert script.done
    assert api.calls == []
    assert "Invalid choice." in output(nav)


def test_search_json_mode_lets_a_failed_fetch_reach_the_caller():
    class Down(Exception):
        pass

    api = FakeAPI(results=[band("Solo", "u1")], error=Down("upstream down"))
    nav, _ = make_nav(api=api, defs=[BAND_DEF])
    with pytest.raises(Down):
        nav.search_and_navigate("solo", ["band"], json_output=True)


def test_interactive_failure_shows_the_reason():
    api = FakeAPI(error=RuntimeError("challenged, retry in 2 minutes"))
    nav, script = make_nav("1", "0", api=api, defs=[BAND_DEF])
    nav.browse(fetch_page=pages([band("A", "u1")]))
    assert script.done
    out = output(nav)
    assert "Could not fetch details." in out
    assert "challenged, retry in 2 minutes" in out


def test_failed_lazy_section_is_not_rendered_empty():
    def boom(api, entity):
        raise RuntimeError("timeout")

    nav, script = make_nav("2", "0", api=FakeAPI(), defs=[BAND_DEF], lazy_fetchers={("band", "bio"): boom})
    nav.navigate(band("Alpha"))
    assert script.done
    assert "No bio available." not in output(nav)


def test_search_json_mode_does_not_fall_back_to_the_picker():
    api = FakeAPI(entities={}, results=[band("A", "u1"), band("B", "u2")])
    nav, script = make_nav("1", api=api, defs=[BAND_DEF])  # one pick, then no more prompts
    assert nav.search_and_navigate("x", ["band"], json_output=True) is False
    assert script.done


def test_input_keeps_case_on_request():
    nav, _ = make_nav("MiXeD")
    assert nav._input("> ", lower=False) == "MiXeD"
