"""Tests for CLI scaffolding helpers."""

import argparse

from rich_metadata.cli import (
    resolve_entity_type,
    strip_internal_keys,
)


class TestStripInternalKeys:
    def test_removes_underscore_keys(self):
        data = {"name": "Test", "_art_data": b"binary", "_type": "band", "genre": "Metal"}
        result = strip_internal_keys(data)
        assert result == {"name": "Test", "genre": "Metal"}

    def test_nested(self):
        data = {"artist": {"name": "A", "_photo": b"x"}, "_id": 1}
        result = strip_internal_keys(data)
        assert result == {"artist": {"name": "A"}}

    def test_list(self):
        data = [{"name": "A", "_x": 1}, {"name": "B", "_y": 2}]
        result = strip_internal_keys(data)
        assert result == [{"name": "A"}, {"name": "B"}]


class TestResolveEntityType:
    def test_with_name(self):
        args = argparse.Namespace(band="Summoning", album=None)
        et, name = resolve_entity_type(args, ["band", "album"])
        assert et == "band"
        assert name == "Summoning"

    def test_flag_only(self):
        args = argparse.Namespace(band=None, album=True)
        et, name = resolve_entity_type(args, ["band", "album"])
        assert et == "album"
        assert name is None

    def test_none(self):
        args = argparse.Namespace(band=None, album=None)
        et, name = resolve_entity_type(args, ["band", "album"])
        assert et is None
        assert name is None
