"""Inline terminal image display using iTerm2/Kitty protocols. No extra dependencies."""

import base64
import os
import sys

from loguru import logger
from rich.console import Console
from rich.panel import Panel

from .terminal import _parse_version

IMAGE_ROWS = 8
IMAGE_COLS = 22
MIN_PANEL_WIDTH = 40


def _detect_protocols() -> tuple[str, ...]:
    """Inline image protocols the terminal supports, preferred first."""
    if not sys.stdout.isatty():
        return ()

    env = os.environ
    term = env.get("TERM", "")
    term_program = env.get("TERM_PROGRAM", "")
    lc_terminal = env.get("LC_TERMINAL", "")

    if "kitty" in term or term_program == "ghostty":
        return ("kitty",)

    if term_program == "vscode":
        vscode_version = _parse_version(env.get("TERM_PROGRAM_VERSION", ""))
        if vscode_version >= (1, 110):
            return ("kitty", "iterm2")
        if vscode_version >= (1, 80):
            return ("iterm2",)
        return ()

    if term_program in {"iTerm.app", "WezTerm", "mintty"}:
        return ("iterm2",)
    if lc_terminal == "iTerm2":
        return ("iterm2",)
    if env.get("KONSOLE_VERSION"):
        return ("iterm2",)
    if env.get("CURSOR_TRACE_ID"):
        return ("iterm2",)
    if term == "contour":
        return ("iterm2",)

    return ()


def _iterm2_image(data: bytes, width: str = "auto", height: str = "8") -> str:
    """Generate iTerm2 inline image escape sequence."""
    b64 = base64.b64encode(data).decode("ascii")
    return f"\033]1337;File=inline=1;width={width};height={height}:{b64}\a"


def _kitty_image(data: bytes, rows: int = 8, cols: int = 20) -> str:
    """Generate Kitty inline image escape sequence."""
    b64 = base64.b64encode(data).decode("ascii")
    chunks = [b64[i : i + 4096] for i in range(0, len(b64), 4096)]
    result = []
    for i, chunk in enumerate(chunks):
        is_last = i == len(chunks) - 1
        m = 0 if is_last else 1
        if i == 0:
            result.append(f"\033_Ga=T,f=100,m={m},r={rows},c={cols};{chunk}\033\\")
        else:
            result.append(f"\033_Gm={m};{chunk}\033\\")
    return "".join(result)


_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def get_image_escape(data: bytes, height: int = 8, width: int = 20) -> str | None:
    """Return the raw escape sequence string for an inline image, or None.

    The iTerm2 protocol takes any image format the terminal can decode. The
    Kitty protocol is sent as PNG (``f=100``), so other formats (JPEG cover
    art, for instance) use the next protocol the terminal supports, or are
    skipped rather than sent as a sequence the terminal cannot show.
    """
    is_png = data.startswith(_PNG_SIGNATURE)
    protocols = _detect_protocols()
    for protocol in protocols:
        if protocol == "iterm2":
            return _iterm2_image(data, width=str(width), height=str(height))
        if protocol == "kitty" and is_png:
            return _kitty_image(data, rows=height, cols=width)
    if protocols:
        logger.debug("Image skipped: the terminal's image protocol needs PNG data")
    return None


def show_image_beside(
    console: Console,
    image_data: bytes | None,
    panel: Panel,
) -> None:
    """Display image and panel side by side, or panel only if images unsupported."""
    escape = get_image_escape(image_data, height=IMAGE_ROWS, width=IMAGE_COLS) if image_data else None

    wide_enough = escape and console.width >= IMAGE_COLS + 2 + MIN_PANEL_WIDTH

    if not wide_enough:
        if escape:
            sys.stdout.write(escape + "\n")
            sys.stdout.flush()
        console.print(panel)
        return

    # Render panel to fit beside image
    panel_width = console.width - IMAGE_COLS - 2
    temp = Console(width=panel_width, force_terminal=True, highlight=False)
    with temp.capture() as cap:
        temp.print(panel)
    panel_lines = cap.get().rstrip("\n").split("\n")

    # Reserve vertical space so the image doesn't overlap previous output
    total_lines = max(IMAGE_ROWS, len(panel_lines))
    sys.stdout.write("\n" * total_lines)
    sys.stdout.write(f"\033[{total_lines}A")

    # Print image top-aligned with the panel
    # iTerm2/Kitty place the cursor on the line below the image after rendering
    sys.stdout.write(escape)
    sys.stdout.write(f"\033[{IMAGE_ROWS}A")

    # Print panel lines from top
    for i in range(total_lines):
        sys.stdout.write(f"\r\033[{IMAGE_COLS + 2}C")
        if i < len(panel_lines):
            sys.stdout.write(panel_lines[i])
        sys.stdout.write("\n")

    sys.stdout.flush()
