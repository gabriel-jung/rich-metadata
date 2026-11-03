"""Terminal detection: hyperlink and inline-image lists must stay in step."""

import sys

import pytest

from rich_metadata import images, terminal
from rich_metadata.images import get_image_escape
from rich_metadata.terminal import links_line, supports_hyperlinks

_ENV_KEYS = [
    "FORCE_HYPERLINK",
    "NO_HYPERLINKS",
    "CI",
    "TEAMCITY_VERSION",
    "NETLIFY",
    "WT_SESSION",
    "KITTY_WINDOW_ID",
    "TERM",
    "DOMTERM",
    "KONSOLE_VERSION",
    "LC_TERMINAL",
    "CURSOR_TRACE_ID",
    "TERM_PROGRAM",
    "TERM_PROGRAM_VERSION",
    "VTE_VERSION",
]

# One environment per terminal that _detect_protocols knows about.
IMAGE_TERMINALS = {
    "kitty": {"TERM": "xterm-kitty"},
    "ghostty": {"TERM_PROGRAM": "ghostty"},
    "vscode-kitty": {"TERM_PROGRAM": "vscode", "TERM_PROGRAM_VERSION": "1.110.0"},
    "vscode-iterm2": {"TERM_PROGRAM": "vscode", "TERM_PROGRAM_VERSION": "1.80.0"},
    "iterm": {"TERM_PROGRAM": "iTerm.app", "TERM_PROGRAM_VERSION": "3.5.0"},
    "wezterm": {"TERM_PROGRAM": "WezTerm", "TERM_PROGRAM_VERSION": "20240203-110809-5046fc22"},
    "mintty": {"TERM_PROGRAM": "mintty"},
    "lc-iterm2": {"LC_TERMINAL": "iTerm2"},
    "konsole": {"KONSOLE_VERSION": "230800"},
    "cursor": {"CURSOR_TRACE_ID": "x"},
    "contour": {"TERM": "contour"},
}


@pytest.fixture
def term(monkeypatch):
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    terminal.supports_hyperlinks.cache_clear()
    yield monkeypatch
    terminal.supports_hyperlinks.cache_clear()


@pytest.mark.parametrize("name", sorted(IMAGE_TERMINALS))
def test_every_image_terminal_also_supports_hyperlinks(term, name):
    for key, value in IMAGE_TERMINALS[name].items():
        term.setenv(key, value)
    assert images._detect_protocols()
    assert supports_hyperlinks()


def test_plain_terminal_has_neither(term):
    term.setenv("TERM", "xterm-256color")
    assert images._detect_protocols() == ()
    assert not supports_hyperlinks()


def test_links_line_with_hyperlinks(term):
    term.setenv("FORCE_HYPERLINK", "1")
    line = links_line(("site", "https://a.test"), ("shop", None), ("wiki", "https://b.test"))
    assert line == "[bold]URL:[/bold] [link=https://a.test]site[/link]  |  [link=https://b.test]wiki[/link]"


def test_links_line_without_hyperlinks(term):
    term.setenv("FORCE_HYPERLINK", "0")
    line = links_line(("site", "https://a.test"), ("wiki", "https://b.test"))
    assert line == "[bold]Site:[/bold] https://a.test\n[bold]Wiki:[/bold] https://b.test"


def test_links_line_with_no_urls_is_none(term):
    assert links_line(("site", None)) is None


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16


def test_kitty_only_terminal_shows_png_but_not_jpeg(monkeypatch):
    monkeypatch.setattr(images, "_detect_protocols", lambda: ("kitty",))
    assert get_image_escape(PNG).startswith("\033_G")
    assert get_image_escape(JPEG) is None


def test_terminal_with_both_protocols_sends_jpeg_through_iterm2(monkeypatch):
    monkeypatch.setattr(images, "_detect_protocols", lambda: ("kitty", "iterm2"))
    assert get_image_escape(JPEG).startswith("\033]1337;File=")
    assert get_image_escape(PNG).startswith("\033_G")


def test_iterm2_shows_any_format(monkeypatch):
    monkeypatch.setattr(images, "_detect_protocols", lambda: ("iterm2",))
    assert get_image_escape(JPEG).startswith("\033]1337;File=")


def test_recent_vscode_speaks_both(term):
    term.setenv("TERM_PROGRAM", "vscode")
    term.setenv("TERM_PROGRAM_VERSION", "1.110.0")
    assert images._detect_protocols() == ("kitty", "iterm2")
