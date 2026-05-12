"""Terminal capability detection (OSC 8 hyperlinks)."""

import os
import sys
from functools import cache


def _parse_version(s: str) -> tuple[int, ...]:
    parts = []
    for chunk in (s or "").split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


@cache
def supports_hyperlinks() -> bool:
    """Detect OSC 8 hyperlink support. Mirrors npm `supports-hyperlinks` / gh cli."""
    env = os.environ

    force = env.get("FORCE_HYPERLINK")
    if force is not None:
        return force not in {"", "0"}
    if env.get("NO_HYPERLINKS"):
        return False

    if not sys.stdout.isatty():
        return False
    if env.get("CI") or env.get("TEAMCITY_VERSION"):
        return False
    if env.get("NETLIFY"):
        return True

    if env.get("WT_SESSION"):
        return True
    if env.get("KITTY_WINDOW_ID") or "kitty" in env.get("TERM", ""):
        return True
    if env.get("DOMTERM"):
        return True
    if env.get("KONSOLE_VERSION"):
        return True
    if env.get("LC_TERMINAL") == "iTerm2":
        return True

    if env.get("CURSOR_TRACE_ID"):  # Cursor (vscode fork) supports hyperlinks
        return True

    term_program = env.get("TERM_PROGRAM", "")
    version = _parse_version(env.get("TERM_PROGRAM_VERSION", ""))
    if term_program == "iTerm.app":
        return version >= (3, 1)
    if term_program == "WezTerm":
        return version >= (20200620,)
    if term_program == "vscode":
        return version >= (1, 72)
    if term_program in {"ghostty", "mintty", "zed"}:
        return True

    vte = env.get("VTE_VERSION")
    if vte and vte != "0.50.0":
        try:
            return int(vte) >= 5000
        except ValueError:
            return False

    return env.get("TERM") in {"alacritty", "foot", "contour"}


def link(label: str, url: str | None) -> str | None:
    """Render a clickable hyperlink, or raw URL on terminals without OSC 8."""
    if not url:
        return None
    return f"[link={url}]{label}[/link]" if supports_hyperlinks() else url
