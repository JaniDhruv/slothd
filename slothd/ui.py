"""Terminal presentation layer for slothd.

Everything visual lives here so cli.py stays about *what* happens, not how it looks.

Design rules (borrowed from the Vercel / Vite / Next.js CLIs):
  1. A compact one-line header on every command; the big logo only for bare `slothd`.
  2. One glyph per state:  ◆ working   ✔ done   ▲ warning   ✖ error   ➜ link
  3. No grid borders. Align with whitespace and dim the secondary text.
  4. Every step shows how long it took.
  5. End with the one or two commands the user most likely wants next.
"""

from __future__ import annotations

import logging
import os
import shlex
import socket
import sys
import time
from collections.abc import Generator, Iterable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler
from rich.markup import escape
from rich.padding import Padding
from rich.table import Table
from rich.text import Text
from rich.theme import Theme
from rich.tree import Tree

# --------------------------------------------------------------------------- #
# Console setup (UTF-8 first, so box-drawing / block characters survive on
# Windows PowerShell and cmd).
# --------------------------------------------------------------------------- #

for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if callable(_reconfigure):
        try:
            _reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

THEME = Theme(
    {
        "brand": "bold #86efac",
        "accent": "#5eead4",
        "ok": "bold #4ade80",
        "warn": "bold #fbbf24",
        "err": "bold #f87171",
        "muted": "dim",
        "key": "#94a3b8",
        "path": "#7dd3fc",
        "num": "bold white",
        "track": "grey35",
    }
)

console = Console(theme=THEME, highlight=False)
err_console = Console(theme=THEME, stderr=True, highlight=False)

UNICODE = (console.encoding or "").lower().replace("-", "").startswith("utf")
EMOJI = UNICODE and not console.legacy_windows


class G:
    """Glyphs, with ASCII fallbacks for terminals that can't render them."""

    work = "◆" if UNICODE else "*"
    ok = "✔" if UNICODE else "+"
    warn = "▲" if UNICODE else "!"
    err = "✖" if UNICODE else "x"
    arrow = "➜" if UNICODE else ">"
    bullet = "›" if UNICODE else ">"
    dot = "·" if UNICODE else "-"
    left = "←" if UNICODE else "<-"
    full = "█" if UNICODE else "#"
    empty = "░" if UNICODE else "-"
    partial = " ▏▎▍▌▋▊▉" if UNICODE else "  "


# --------------------------------------------------------------------------- #
# Formatting helpers
# --------------------------------------------------------------------------- #


def fmt_size(num_bytes: float) -> str:
    """1536 -> '1.5 KB'."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def fmt_duration(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}m {secs:02d}s"


def tilde(path: str | Path) -> str:
    """Shorten the home directory to ~ for display."""
    text = str(path)
    home = str(Path.home())
    if text == home:
        return "~"
    if text.startswith(home + os.sep):
        return "~" + text[len(home) :]
    return text


def plural(n: int, word: str, many: str | None = None) -> str:
    return f"{n:,} {word if n == 1 else (many or word + 's')}"


def shell_arg(text: str) -> str:
    """Quote only when needed, and keep a leading ~ usable."""
    if text.startswith("~/") and " " not in text:
        return text
    return shlex.quote(text) if os.name != "nt" else (f'"{text}"' if " " in text else text)


# --------------------------------------------------------------------------- #
# Banner and header
# --------------------------------------------------------------------------- #

_WORDMARK = {
    "S": ["███████╗", "██╔════╝", "███████╗", "╚════██║", "███████║", "╚══════╝"],
    "L": ["██╗     ", "██║     ", "██║     ", "██║     ", "███████╗", "╚══════╝"],
    "O": [" ██████╗ ", "██╔═══██╗", "██║   ██║", "██║   ██║", "╚██████╔╝", " ╚═════╝ "],
    "T": ["████████╗", "╚══██╔══╝", "   ██║   ", "   ██║   ", "   ██║   ", "   ╚═╝   "],
    "H": ["██╗  ██╗", "██║  ██║", "███████║", "██╔══██║", "██║  ██║", "╚═╝  ╚═╝"],
    "D": ["██████╗ ", "██╔══██╗", "██║  ██║", "██║  ██║", "██████╔╝", "╚═════╝ "],
}

_SLOTH = [
    "   ╭─────────╮  z",
    "  ╱ ◥▇◣   ◢▇◤ ╲  z",
    " │   ●     ●   │  Z",
    " │      ▾      │",
    "  ╲    ╰─╯    ╱",
    "   ╰─────────╯",
]


def _wordmark_lines(word: str = "SLOTHD") -> list[str]:
    rows = [""] * 6
    for letter in word:
        glyph = _WORDMARK[letter]
        width = max(len(line) for line in glyph)
        for i, line in enumerate(glyph):
            rows[i] += line.ljust(width)
    return rows


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> str:
    r, g, bl = (round(x + (y - x) * t) for x, y in zip(a, b, strict=True))
    return f"#{r:02x}{g:02x}{bl:02x}"


def _gradient(lines: Sequence[str], start: tuple[int, int, int], end: tuple[int, int, int]) -> Text:
    """Diagonal colour sweep across a block of ASCII art."""
    width = max(len(line) for line in lines)
    span = width + len(lines) * 2 - 1
    out = Text(no_wrap=True)
    for row, line in enumerate(lines):
        for col, ch in enumerate(line):
            if ch == " ":
                out.append(ch)
            else:
                out.append(ch, style=_lerp(start, end, (col + row * 2) / span))
        if row < len(lines) - 1:
            out.append("\n")
    return out


MOSS = (134, 239, 172)  # #86efac
TEAL = (45, 212, 191)  # #2dd4bf
SKY = (125, 211, 252)  # #7dd3fc


def banner(version: str) -> None:
    """Full logo. Used only for bare `slothd`."""
    width = console.width
    if not UNICODE or width < 56:
        header(None, version)
        return

    word = _gradient(_wordmark_lines(), MOSS, SKY)
    if width >= 74:
        face = _gradient(_SLOTH, (190, 160, 120), (150, 120, 90))
        layout = Table.grid(padding=(0, 3))
        layout.add_column(no_wrap=True)
        layout.add_column(no_wrap=True)
        layout.add_row(face, word)
        console.print(Padding(layout, (1, 0, 0, 2)))
    else:
        console.print(Padding(word, (1, 0, 0, 2)))

    tagline = Text.assemble(
        ("local-first ", "accent"),
        (G.dot + " ", "muted"),
        ("air-gapped ", "accent"),
        (G.dot + " ", "muted"),
        ("idle AI", "accent"),
        ("      ", ""),
        (f"v{version}", "muted"),
    )
    console.print(Padding(tagline, (1, 0, 1, 2)))


def header(command: str | None, version: str) -> None:
    """One compact line, shown on every subcommand."""
    line = Text()
    line.append(" ")
    if EMOJI:
        line.append("🦥 ")
    line.append("slothd", style="brand")
    line.append(f" v{version}", style="muted")
    if command:
        line.append(f"  {G.dot}  ", style="muted")
        line.append(command, style="num")
    console.print()
    console.print(line)
    console.print()


# --------------------------------------------------------------------------- #
# Steps (spinner while running, tidy line with timing when done)
# --------------------------------------------------------------------------- #


def _line(glyph: str, style: str, text: str | Text, right: str = "") -> None:
    grid = Table.grid(expand=True, padding=(0, 1))
    grid.add_column(width=1, no_wrap=True)
    grid.add_column(ratio=1, no_wrap=True, overflow="ellipsis")
    grid.add_column(justify="right", no_wrap=True)
    body = Text.from_markup(text) if isinstance(text, str) else text
    grid.add_row(Text(glyph, style=style), body, Text(right, style="muted"))
    console.print(Padding(grid, (0, 1, 0, 1)))


@dataclass
class StepResult:
    """Filled in by the code inside a `with step(...)` block."""

    message: str | None = None
    state: str = "ok"  # ok | warn

    def done(self, message: str, *, warn: bool = False) -> None:
        self.message = message
        self.state = "warn" if warn else "ok"


@contextmanager
def step(label: str) -> Generator[StepResult, None, None]:
    """Run a unit of work behind a slow, sloth-paced spinner."""
    result = StepResult()
    started = time.perf_counter()
    status = console.status(
        Text(f"{label}…" if UNICODE else f"{label}...", style="muted"),
        spinner="dots" if UNICODE else "line",
        spinner_style="accent",
        speed=0.6,
    )
    status.start()
    try:
        yield result
    except KeyboardInterrupt:
        status.stop()
        _line(G.warn, "warn", f"{escape(label)} [muted](cancelled)[/]", fmt_duration(time.perf_counter() - started))
        raise
    except BaseException:
        status.stop()
        _line(G.err, "err", f"{escape(label)} [err]failed[/]", fmt_duration(time.perf_counter() - started))
        raise
    status.stop()
    glyph, style = (G.warn, "warn") if result.state == "warn" else (G.ok, "ok")
    _line(glyph, style, result.message or escape(label), fmt_duration(time.perf_counter() - started))


def info(message: str) -> None:
    _line(G.work, "accent", message)


def success(message: str, elapsed: float | None = None) -> None:
    _line(G.ok, "ok", message, fmt_duration(elapsed) if elapsed is not None else "")


def warn(message: str) -> None:
    _line(G.warn, "warn", message)


def fail(message: str, hint: str | None = None) -> None:
    """Vercel-style error: one red line, one actionable hint."""
    err_console.print(Text.assemble((f" {G.err} ", "err"), ("Error: ", "err"), message))
    if hint:
        err_console.print(Text.assemble((f"   {G.arrow} ", "muted"), (hint, "")))


def friendly_error(exc: BaseException) -> tuple[str, str]:
    """Map common failures to a message + hint. Falls back to the raw message."""
    name = type(exc).__name__
    text = str(exc) or name
    if name in {"ConnectError", "ConnectionError", "ConnectionRefusedError", "ConnectTimeout"}:
        return (
            "Couldn't reach a local service.",
            "Is Ollama running? Try `ollama serve`, or re-run without --ai.",
        )
    if isinstance(exc, PermissionError):
        return (f"Permission denied: {text}", "Check the folder permissions, or pick another directory.")
    if isinstance(exc, FileNotFoundError):
        return (text, "Check the path and try again.")
    return (text, "Re-run with -vv for the full traceback.")


# --------------------------------------------------------------------------- #
# Blocks: key/value, sections, bars, trees, results, hints
# --------------------------------------------------------------------------- #


def section(title: str) -> None:
    console.print()
    console.print(Text(f"  {title.upper()}", style="key"))


def kv(rows: Iterable[tuple[str, str | Text]], indent: int = 3) -> None:
    rows = list(rows)
    width = max(len(k) for k, _ in rows)
    for key, value in rows:
        text = value if isinstance(value, Text) else Text(value)
        console.print(Text.assemble((" " * indent + key.ljust(width) + "   ", "key"), text))


def badge(label: str, fg: str = "black", bg: str = "#fbbf24") -> Text:
    return Text(f" {label} ", style=f"bold {fg} on {bg}")


def toggle(label: str, enabled: bool, detail: str = "") -> Text:
    text = Text()
    text.append(f"{G.ok} on" if enabled else f"{G.dot} off", style="ok" if enabled else "muted")
    if enabled and detail:
        text.append(f"  {detail}", style="muted")
    return text


def next_steps(commands: Sequence[tuple[str, str]]) -> None:
    """The 'what now?' block that closes every command."""
    width = max(len(cmd) for cmd, _ in commands)
    console.print()
    console.print(Text("  Next", style="key"))
    for cmd, why in commands:
        console.print(
            Text.assemble(
                (f"   {G.bullet} ", "muted"),
                (cmd.ljust(width), "accent"),
                (f"   {why}", "muted"),
            )
        )
    console.print()


def _bar(fraction: float, width: int = 22, color: str = "accent") -> Text:
    fraction = max(0.0, min(1.0, fraction))
    exact = fraction * width
    full = int(exact)
    filled = G.full * full
    level = int((exact - full) * (len(G.partial) - 1))
    if full < width and level > 0:
        filled += G.partial[level]
    out = Text(filled, style=color)
    out.append(G.empty * (width - len(filled)), style="track")
    return out


_PALETTE = ["#5eead4", "#7dd3fc", "#a5b4fc", "#f0abfc", "#fcd34d", "#fdba74", "#86efac"]


def category_chart(rows: Sequence[tuple[str, int, int]]) -> None:
    """rows: (category, file_count, total_bytes) sorted however the caller likes."""
    total = sum(count for _, count, _ in rows) or 1
    name_w = max(len(name) for name, _, _ in rows)
    top = max(count for _, count, _ in rows) or 1
    for i, (name, count, size) in enumerate(rows):
        color = _PALETTE[i % len(_PALETTE)]
        line = Text("   ")
        line.append(name.ljust(name_w), style=color)
        line.append("  ")
        line.append_text(_bar(count / top, color=color))
        line.append(f"  {count:>5,}", style="num")
        line.append(f"  {fmt_size(size):>9}", style="muted")
        line.append(f"  {count / total:>4.0%}", style="muted")
        console.print(line)


def duplicates_block(dupes: dict[str, list], limit: int = 5) -> None:
    wasted = sum(sum(f.size_bytes for f in files[1:]) for files in dupes.values())
    warn(f"{plural(len(dupes), 'duplicate set')} {G.dot} {fmt_size(wasted)} reclaimable")
    for digest, files in list(dupes.items())[:limit]:
        names = ", ".join(f.name for f in files[:3])
        extra = f" +{len(files) - 3}" if len(files) > 3 else ""
        console.print(Text.assemble(("     ", ""), (digest[:8], "muted"), ("  ", ""), (names, "path"), (extra, "muted")))
    if len(dupes) > limit:
        console.print(Text(f"     … and {len(dupes) - limit} more sets", style="muted"))


@dataclass
class _Node:
    count: int = 0
    kids: dict[str, _Node] = field(default_factory=dict)
    files: list = field(default_factory=list)


def _render_tree(node: _Node, tree: Tree, limit: int, max_kids: int, samples: int) -> None:
    kids = sorted(node.kids.items(), key=lambda item: -item[1].count)
    for name, child in kids[:limit]:
        # collapse single-child chains: Documents/ -> 2026/ becomes Documents/2026/
        while len(child.kids) == 1 and not child.files:
            (sub_name, sub), = child.kids.items()
            name, child = f"{name}/{sub_name}", sub
        branch = tree.add(
            Text.assemble((name.replace(os.sep, "/") + "/", "accent"), (f"   {plural(child.count, 'file')}", "muted"))
        )
        _render_tree(child, branch, max_kids, max_kids, samples)
    if len(kids) > limit:
        rest = sum(child.count for _, child in kids[limit:])
        tree.add(Text(f"… {plural(len(kids) - limit, 'more folder')} ({rest} files)", style="muted"))
    for move in node.files[:samples]:
        tree.add(Text.assemble((move.file_name, ""), (f"   {move.reason}", "muted")))
    if len(node.files) > samples:
        tree.add(Text(f"… +{len(node.files) - samples} more", style="muted"))


def moves_tree(moves: Sequence, base_dir: Path, max_top: int = 4, max_kids: int = 2, samples: int = 1) -> None:
    """Show the plan as a nested folder tree (counts + a couple of sample files),
    instead of a 50-row table."""
    root = _Node()
    for move in moves:
        folder = Path(move.destination).parent
        try:
            parts: tuple[str, ...] = folder.relative_to(base_dir).parts
        except ValueError:
            parts = (str(folder),)
        node = root
        node.count += 1
        for part in parts:
            node = node.kids.setdefault(part, _Node())
            node.count += 1
        node.files.append(move)

    tree = Tree(Text(tilde(base_dir), style="path"), guide_style="track")
    _render_tree(root, tree, max_top, max_kids, samples)
    console.print(Padding(tree, (0, 0, 0, 3)))


def search_results(hits: Sequence) -> None:
    """Ranked result cards instead of a 5-column table."""
    for rank, hit in enumerate(hits, start=1):
        score = hit.similarity_score
        color = "#4ade80" if score >= 0.75 else "#fbbf24" if score >= 0.5 else "#94a3b8"
        top = Text("   ")
        top.append(f"{rank:>2}  ", style="muted")
        top.append(f"{score:>4.0%} ", style=f"bold {color}")
        top.append_text(_bar(score, width=10, color=color))
        top.append(f"  {hit.file_name}", style="num")
        console.print(top)
        meta = [hit.category, hit.vendor or None, str(hit.file_date) if hit.file_date else None]
        console.print(Text("          " + f" {G.dot} ".join(m for m in meta if m), style="accent"))
        console.print(Text("          " + tilde(hit.file_path), style="muted"))
        console.print()


# --------------------------------------------------------------------------- #
# Dev-server banner (Vite style)
# --------------------------------------------------------------------------- #


def _lan_ip() -> str | None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("10.255.255.255", 1))  # UDP connect: nothing is actually sent
        return sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()


def server_ready(host: str, port: int, version: str, *, started: float | None = None) -> None:
    ready = f"  ready in {fmt_duration(time.perf_counter() - started)}" if started else ""
    console.print(Text.assemble(("  SLOTHD ", "brand"), (f"v{version}", "muted"), (ready, "muted")))
    console.print()
    local_host = "localhost" if host in {"0.0.0.0", "127.0.0.1", "::"} else host
    rows = [("Local:", f"http://{local_host}:{port}/")]
    if host == "0.0.0.0":
        ip = _lan_ip()
        if ip:
            rows.append(("Network:", f"http://{ip}:{port}/"))
        else:
            rows.append(("Network:", "available"))
    else:
        rows.append(("Network:", "use --host 0.0.0.0 to expose"))
    for label, value in rows:
        style = "path" if value.startswith("http") else "muted"
        console.print(Text.assemble((f"  {G.arrow}  ", "ok"), (label.ljust(9), "key"), (value, style)))
    console.print(Text.assemble((f"  {G.arrow}  ", "muted"), ("press ", "muted"), ("ctrl+c", "num"), (" to stop", "muted")))
    console.print()


# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #


def setup_logging(verbosity: int) -> None:
    """0 -> warnings only, -v -> info, -vv -> debug (with rich tracebacks)."""
    level = logging.WARNING if verbosity == 0 else logging.INFO if verbosity == 1 else logging.DEBUG
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%H:%M:%S]",
        handlers=[RichHandler(console=err_console, show_path=False, rich_tracebacks=True, markup=False)],
        force=True,
    )
