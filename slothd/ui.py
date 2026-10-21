"""Terminal presentation layer for slothd.

Everything visual lives here so cli.py stays about *what* happens, not how it looks.

Design rules (inspired by Claude Code, Vercel, Vite, Clack CLIs):
  1. A compact one-line header on every command; the big logo only for bare `slothd`.
  2. Left-aligned guide rails (│ ┌ ├ └) connect steps vertically.
  3. One glyph per state:  ◆ working   ✔ done   ▲ warning   ✖ error   ➜ link
  4. Gradient dividers and subtle animations for premium feel.
  5. Every step shows how long it took with micro-timing.
  6. End with the one or two commands the user most likely wants next.
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
from typing import Any

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
        "brand.dim": "#4ade80",
        "accent": "#5eead4",
        "accent.bright": "bold #5eead4",
        "ok": "bold #4ade80",
        "warn": "bold #fbbf24",
        "err": "bold #f87171",
        "muted": "dim",
        "muted.bright": "#64748b",
        "key": "#94a3b8",
        "path": "#7dd3fc",
        "num": "bold white",
        "track": "grey35",
        "rail": "#374151",
        "rail.active": "#5eead4",
        "badge.live": "bold black on #4ade80",
        "badge.dry": "bold black on #fbbf24",
        "badge.info": "bold white on #3b82f6",
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
    # Guide rails (Claude Code / Clack style)
    rail_top = "┌" if UNICODE else "+"
    rail_mid = "│" if UNICODE else "|"
    rail_branch = "├" if UNICODE else "+"
    rail_end = "└" if UNICODE else "+"
    rail_tee = "┬" if UNICODE else "+"
    rail_dash = "─" if UNICODE else "-"
    # Selection
    pointer = "❯" if UNICODE else ">"
    circle = "●" if UNICODE else "o"
    circle_empty = "○" if UNICODE else " "
    diamond = "◇" if UNICODE else "*"


# --------------------------------------------------------------------------- #
# Gradient helpers
# --------------------------------------------------------------------------- #

MOSS = (134, 239, 172)  # #86efac
TEAL = (45, 212, 191)   # #2dd4bf
SKY = (125, 211, 252)   # #7dd3fc
AMBER = (251, 191, 36)  # #fbbf24
VIOLET = (167, 139, 250)  # #a78bfa

_GRADIENT_COLORS = [
    "#5eead4", "#6ee7b7", "#86efac", "#a7f3d0",
    "#7dd3fc", "#93c5fd", "#a5b4fc", "#c4b5fd",
]


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


def gradient_bar(width: int | None = None) -> None:
    """Print a subtle gradient separator bar (Claude Code style)."""
    w = width or min(console.width - 4, 72)
    text = Text()
    for i in range(w):
        t = i / max(w - 1, 1)
        color = _lerp(TEAL, SKY, t)
        text.append(G.rail_dash, style=color)
    console.print(Padding(text, (0, 0, 0, 2)))


def dim_bar(width: int | None = None) -> None:
    """Print a dim horizontal rule."""
    w = width or min(console.width - 4, 72)
    console.print(Padding(Text(G.rail_dash * w, style="rail"), (0, 0, 0, 2)))


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
    """One compact line, shown on every subcommand. Claude Code style."""
    console.print()
    # Gradient accent line
    accent_w = min(console.width - 4, 48)
    accent = Text()
    for i in range(accent_w):
        t = i / max(accent_w - 1, 1)
        color = _lerp(MOSS, SKY, t)
        accent.append("━", style=color)
    console.print(Padding(accent, (0, 0, 0, 2)))

    line = Text()
    line.append(" ")
    if EMOJI:
        line.append("🦥 ")
    line.append("slothd", style="brand")
    line.append(f" v{version}", style="muted")
    if command:
        line.append(f"  {G.dot}  ", style="muted")
        line.append(command, style="accent.bright")
    console.print(line)
    console.print()


# --------------------------------------------------------------------------- #
# Steps — guide-rail connected, with spinner and micro-timings
# --------------------------------------------------------------------------- #


def _line(glyph: str, style: str, text: str | Text, right: str = "") -> None:
    grid = Table.grid(expand=True, padding=(0, 1))
    grid.add_column(width=1, no_wrap=True)
    grid.add_column(width=1, no_wrap=True)
    grid.add_column(ratio=1, no_wrap=True, overflow="ellipsis")
    grid.add_column(justify="right", no_wrap=True)
    body = Text.from_markup(text) if isinstance(text, str) else text
    grid.add_row(
        Text(G.rail_mid, style="rail"),
        Text(glyph, style=style),
        body,
        Text(right, style="muted"),
    )
    console.print(Padding(grid, (0, 0, 0, 1)))


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
    """Run a unit of work behind a slow, sloth-paced spinner with guide rails."""
    result = StepResult()
    started = time.perf_counter()

    # Print the "working" line with rail connector
    status = console.status(
        Text.assemble(
            (G.rail_mid, "rail"),
            (" ", ""),
            (G.work, "accent"),
            (" ", ""),
            (f"{label}…" if UNICODE else f"{label}...", "muted"),
        ),
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


def step_open(label: str) -> None:
    """Print a rail opening line (┌) for a logical group."""
    text = Text()
    text.append(f"  {G.rail_top}", style="rail")
    text.append(f" {label}", style="key")
    console.print(text)


def step_close() -> None:
    """Print a rail closing line (└)."""
    console.print(Text(f"  {G.rail_end}", style="rail"))


def info(message: str) -> None:
    _line(G.work, "accent", message)


def success(message: str, elapsed: float | None = None) -> None:
    _line(G.ok, "ok", message, fmt_duration(elapsed) if elapsed is not None else "")


def warn(message: str) -> None:
    _line(G.warn, "warn", message)


def fail(message: str, hint: str | None = None) -> None:
    """Claude Code-style error: one red line with rail, one actionable hint."""
    err_console.print(
        Text.assemble(
            (f"  {G.rail_mid} ", "rail"),
            (f"{G.err} ", "err"),
            ("Error: ", "err"),
            (message, ""),
        )
    )
    if hint:
        err_console.print(
            Text.assemble(
                (f"  {G.rail_end} ", "rail"),
                (f"{G.arrow} ", "muted"),
                (hint, ""),
            )
        )


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
    text = Text()
    text.append(f"  {G.rail_mid} ", style="rail")
    text.append(title.upper(), style="key")
    console.print(text)


def kv(rows: Iterable[tuple[str, str | Text]], indent: int = 3) -> None:
    rows = list(rows)
    width = max(len(k) for k, _ in rows)
    for key, value in rows:
        text = value if isinstance(value, Text) else Text(value)
        line = Text()
        line.append(f"  {G.rail_mid} ", style="rail")
        line.append(key.ljust(width) + "  ", style="key")
        line.append_text(text)
        console.print(line)


def badge(label: str, fg: str = "black", bg: str = "#fbbf24") -> Text:
    return Text(f" {label} ", style=f"bold {fg} on {bg}")


def toggle(label: str, enabled: bool, detail: str = "") -> Text:
    text = Text()
    text.append(f"{G.ok} on" if enabled else f"{G.dot} off", style="ok" if enabled else "muted")
    if enabled and detail:
        text.append(f"  {detail}", style="muted")
    return text


def _flush_stdin() -> None:
    """Flush any pending keystrokes in the console input buffer."""
    try:
        import msvcrt

        while msvcrt.kbhit():
            msvcrt.getch()
    except Exception:
        pass


def prompt_press_enter(message: str = "Press Enter to return to main menu...") -> None:
    """Pause execution until user presses Enter so they can review task results."""
    import sys

    if not sys.stdin.isatty():
        return

    _flush_stdin()
    console.print()
    try:
        from InquirerPy import get_style, inquirer

        inquirer.text(
            message=message,
            qmark=f"  {G.bullet}",
            amark=f"  {G.ok}",
            style=get_style({"question": "#94a3b8", "input": "#5eead4"}),
            transformer=lambda _: "",
        ).execute()
    except (KeyboardInterrupt, EOFError, Exception):
        pass


def next_steps(commands: Sequence[tuple[str, str]]) -> None:
    """Claude Code-style 'what now?' block that closes every command."""
    width = max(len(cmd) for cmd, _ in commands)
    console.print()
    console.print(Text.assemble(("  ", ""), (G.rail_mid, "rail"), (" ", ""), ("Suggested next actions:", "key")))
    for i, (cmd, why) in enumerate(commands):
        rail = G.rail_end if i == len(commands) - 1 else G.rail_branch
        console.print(
            Text.assemble(
                ("  ", ""),
                (rail, "rail"),
                (" ", ""),
                (G.arrow, "ok"),
                (" ", ""),
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
        line = Text()
        line.append(f"  {G.rail_mid} ", style="rail")
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
        line = Text()
        line.append(f"  {G.rail_mid}   ", style="rail")
        line.append(digest[:8], style="muted")
        line.append("  ")
        line.append(names, style="path")
        line.append(extra, style="muted")
        console.print(line)
    if len(dupes) > limit:
        console.print(
            Text.assemble(
                (f"  {G.rail_mid}   ", "rail"),
                (f"… and {len(dupes) - limit} more sets", "muted"),
            )
        )


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
    """Claude Code-style ranked result cards."""
    for rank, hit in enumerate(hits, start=1):
        score = hit.similarity_score
        color = "#4ade80" if score >= 0.75 else "#fbbf24" if score >= 0.5 else "#94a3b8"

        # Rank + score + bar
        top = Text()
        top.append(f"  {G.rail_mid} ", style="rail")
        top.append(f"{rank:>2}  ", style="muted")
        top.append(f"{score:>4.0%} ", style=f"bold {color}")
        top.append_text(_bar(score, width=10, color=color))
        top.append(f"  {hit.file_name}", style="num")
        console.print(top)

        # Metadata line
        meta = [hit.category, hit.vendor or None, str(hit.file_date) if hit.file_date else None]
        meta_line = Text()
        meta_line.append(f"  {G.rail_mid}       ", style="rail")
        meta_line.append(f" {G.dot} ".join(m for m in meta if m), style="accent")
        console.print(meta_line)

        # Path line
        path_line = Text()
        path_line.append(f"  {G.rail_mid}       ", style="rail")
        path_line.append(tilde(hit.file_path), style="muted")
        console.print(path_line)
        console.print()


def anomalies_table(result: Any, limit: int = 10) -> None:
    """Render TabPFN tabular prediction and clutter anomaly detection results."""
    anomalies = getattr(result, "anomalies", [])
    model_used = getattr(result, "model_used", "TabPFN")
    clutter_ratio = getattr(result, "clutter_ratio", 0.0)

    section(f"Prior Labs TabPFN Anomaly Report ({model_used})")

    # Overview kv
    kv([
        ("Clutter Ratio", f"{clutter_ratio:.1%} ({len(anomalies)} anomalies flagged)"),
        ("Model Engine", model_used),
    ])
    console.print()

    if not anomalies:
        console.print(
            Text.assemble(
                (f"  {G.rail_mid} ", "rail"),
                (G.ok, "ok"),
                (" ", ""),
                ("No disk clutter or abnormal size outliers detected. Directory looks clean!", "muted"),
            )
        )
        return

    for item in anomalies[:limit]:
        risk_color = (
            "bold white on #ef4444"
            if item.risk_level == "CRITICAL"
            else "bold black on #fbbf24"
            if item.risk_level == "WARNING"
            else "bold white on #3b82f6"
        )
        risk_badge = Text(f" {item.risk_level} ", style=risk_color)

        # Header: rail + badge + filename + size + score
        top = Text()
        top.append(f"  {G.rail_mid} ", style="rail")
        top.append_text(risk_badge)
        top.append(f"  {item.file_name} ", style="num")
        top.append(f"({fmt_size(item.size_bytes)})", style="muted")
        top.append(f"  [score: {item.anomaly_score:.0%}]", style="accent")
        console.print(top)

        # Detail: reason -> suggested action
        detail = Text()
        detail.append(f"  {G.rail_mid}       ", style="rail")
        detail.append(item.reason, style="warn")
        detail.append(f"  {G.arrow}  ", style="muted")
        detail.append(item.suggested_action, style="ok")
        console.print(detail)

        # Path: file path
        path_line = Text()
        path_line.append(f"  {G.rail_mid}       ", style="rail")
        path_line.append(tilde(item.file_path), style="muted")
        console.print(path_line)
        console.print()

    if len(anomalies) > limit:
        console.print(
            Text.assemble(
                (f"  {G.rail_mid} ", "rail"),
                (f"… and {len(anomalies) - limit} more anomalies.", "muted"),
            )
        )


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
    console.print()
    gradient_bar()
    console.print()

    ready = f"  ready in {fmt_duration(time.perf_counter() - started)}" if started else ""
    console.print(Text.assemble(("  ", ""), ("SLOTHD ", "brand"), (f"v{version}", "muted"), (ready, "muted")))
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
        console.print(Text.assemble(
            (f"  {G.rail_mid} ", "rail"),
            (f"{G.arrow}  ", "ok"),
            (label.ljust(9), "key"),
            (value, style),
        ))
    console.print(
        Text.assemble(
            (f"  {G.rail_end} ", "rail"),
            ("press ", "muted"),
            ("ctrl+c", "num"),
            (" to stop", "muted"),
        )
    )
    console.print()


# --------------------------------------------------------------------------- #
# Interactive command picker (Clack/Claude Code style via InquirerPy)
# --------------------------------------------------------------------------- #


def interactive_picker(version: str, *, show_banner: bool = True) -> str | None:
    """Show an interactive command picker with InquirerPy.

    Returns the selected command string, or None if cancelled.
    """
    try:
        from InquirerPy import get_style, inquirer
        from InquirerPy.separator import Separator
    except ImportError:
        warn("Install InquirerPy for interactive mode: pip install InquirerPy")
        return None

    # Show banner on first run, or gradient divider on subsequent loops
    if show_banner:
        banner(version)
    gradient_bar()
    console.print()

    prompt_label = "What would you like to do?" if show_banner else "What would you like to do next?"
    console.print(
        Text.assemble(
            ("  ", ""),
            (G.diamond, "accent"),
            (" ", ""),
            (prompt_label, "num"),
        )
    )
    console.print()

    choices = [
        {"name": f"  {G.ok}  Scan a directory             Inspect files, categories & duplicates", "value": "scan"},
        {"name": f"  {G.work}  Organize files (dry-run)    Preview where files will be moved", "value": "organize"},
        {"name": f"  {G.arrow}  Organize files (live)       Move files & index for search", "value": "organize-go"},
        Separator(line=f"  {'─' * 56}"),
        {"name": f"  {G.diamond}  TabPFN anomaly predictor    Spot clutter & size outliers with TabPFN", "value": "predict"},
        {"name": f"  {G.left}  Undo last batch             Reverse the most recent organization", "value": "undo"},
        {"name": "  ◈  Semantic search             Find files by meaning, not filename", "value": "search"},
        Separator(line=f"  {'─' * 56}"),
        {"name": "  ⏳  Start idle daemon           Run in background, activate when idle", "value": "daemon"},
        {"name": "  🌐  Launch web dashboard        Start the FastAPI glassmorphic UI", "value": "serve"},
        {"name": "  🎙  Voice briefing              Hear the sloth summarize your files", "value": "briefing"},
        Separator(line=f"  {'─' * 56}"),
        {"name": f"  {G.err}  Exit                        Quit interactive session", "value": "exit"},
    ]

    choice_labels = {
        "scan": "Scan a directory",
        "organize": "Organize files (dry-run)",
        "organize-go": "Organize files (live)",
        "predict": "TabPFN anomaly predictor",
        "undo": "Undo last batch",
        "search": "Semantic search",
        "daemon": "Start idle daemon",
        "serve": "Launch web dashboard",
        "briefing": "Voice briefing",
        "exit": "Exit",
    }

    _flush_stdin()
    try:
        result = inquirer.select(
            message="",
            choices=choices,
            pointer=G.pointer,
            default=None,
            style=get_style(
                {
                    "questionmark": "#5eead4",
                    "answermark": "#4ade80",
                    "answer": "#86efac",
                    "input": "#ffffff",
                    "question": "",
                    "answered_question": "",
                    "instruction": "#64748b",
                    "long_instruction": "#64748b",
                    "pointer": "#5eead4 bold",
                    "checkbox": "#5eead4",
                    "separator": "#374151",
                    "skipped": "#64748b",
                    "validator": "",
                    "marker": "#5eead4",
                    "fuzzy_prompt": "#5eead4",
                    "fuzzy_info": "#64748b",
                    "fuzzy_border": "#374151",
                    "fuzzy_match": "#86efac bold",
                }
            ),
            qmark="",
            amark=f"  {G.ok}",
            instruction="(↑/↓ to navigate, enter to select, ctrl+c to exit)",
            transformer=lambda x: f"  {choice_labels.get(x, x)}",
        ).execute()
        return result
    except (KeyboardInterrupt, EOFError):
        console.print()
        console.print(Text.assemble(("  ", ""), (G.dot, "muted"), (" ", ""), ("Cancelled.", "muted")))
        console.print()
        return None


def prompt_directory(message: str = "Which directory?", default: str | None = None) -> str | None:
    """Prompt user for a directory path with InquirerPy fuzzy file path completion."""
    try:
        from InquirerPy import get_style, inquirer
    except ImportError:
        return None

    try:
        result = inquirer.filepath(
            message=message,
            default=default or str(Path.cwd()),
            only_directories=True,
            qmark=f"  {G.diamond}",
            amark=f"  {G.ok}",
            style=get_style(
                {
                    "questionmark": "#5eead4",
                    "answermark": "#4ade80",
                    "answer": "#7dd3fc",
                    "input": "#ffffff",
                    "question": "#94a3b8",
                }
            ),
        ).execute()
        return result
    except (KeyboardInterrupt, EOFError):
        return None


def prompt_source_directory(message: str = "Which directory would you like to use?") -> Path | None:
    """Prompt user to select a source directory via presets or custom path entry."""
    try:
        from InquirerPy import get_style, inquirer
        from InquirerPy.separator import Separator
    except ImportError:
        return None

    home = Path.home()
    candidates = [
        ("Downloads", home / "Downloads"),
        ("Desktop", home / "Desktop"),
        ("Documents", home / "Documents"),
        ("Current folder", Path.cwd()),
    ]

    choices = []
    for label, p in candidates:
        if p.exists() and p.is_dir():
            choices.append(
                {
                    "name": f"  📂  {label:<16} {tilde(p)}",
                    "value": str(p),
                }
            )

    choices.append(Separator(line=f"  {'─' * 56}"))
    choices.append(
        {
            "name": "  🔍  Custom directory...  (type or browse any path)",
            "value": "__custom__",
        }
    )

    console.print()
    console.print(
        Text.assemble(
            ("  ", ""),
            (G.diamond, "accent"),
            (" ", ""),
            (message, "num"),
        )
    )
    console.print()

    _flush_stdin()
    try:
        choice = inquirer.select(
            message="",
            choices=choices,
            pointer=G.pointer,
            default=choices[0]["value"] if choices else None,
            style=get_style(
                {
                    "questionmark": "#5eead4",
                    "answermark": "#4ade80",
                    "answer": "#7dd3fc",
                    "pointer": "#5eead4 bold",
                    "separator": "#374151",
                    "instruction": "#64748b",
                }
            ),
            qmark="",
            amark=f"  {G.ok}",
            instruction="(↑/↓ to navigate, enter to select, ctrl+c to cancel)",
            transformer=lambda x: f"  {tilde(x)}" if x != "__custom__" else "  Custom directory...",
        ).execute()

        if not choice:
            return None

        if choice == "__custom__":
            custom_path = prompt_directory("Enter directory path:", default=str(Path.cwd()))
            if not custom_path:
                return None
            p = Path(custom_path).expanduser().resolve()
            if not p.exists():
                warn(f"Directory {tilde(p)} does not exist.")
                return None
            return p

        return Path(choice).resolve()
    except (KeyboardInterrupt, EOFError):
        return None


def prompt_destination_directory(source_dir: Path) -> tuple[bool, Path | None]:
    """Prompt user for where organized files should be stored.

    Returns:
        (True, None) for in-place organization.
        (True, Path(...)) for custom or dedicated output folder.
        (False, None) if cancelled by user.
    """
    try:
        from InquirerPy import get_style, inquirer
        from InquirerPy.separator import Separator
    except ImportError:
        return False, None

    organized_home = Path.home() / "Organized"
    source_organized = source_dir / "Organized"

    choices = [
        {
            "name": f"  📁  In-place              Sort into {tilde(source_dir)}/ (Documents, Images, etc.)",
            "value": "__in_place__",
        },
        {
            "name": f"  📦  Subfolder in source   Move into {tilde(source_organized)}/",
            "value": str(source_organized),
        },
        {
            "name": f"  🏠  Home folder (~/Organized) Move into {tilde(organized_home)}/",
            "value": str(organized_home),
        },
        Separator(line=f"  {'─' * 56}"),
        {
            "name": "  🔍  Custom destination    Specify another folder path",
            "value": "__custom__",
        },
    ]

    console.print()
    console.print(
        Text.assemble(
            ("  ", ""),
            (G.diamond, "accent"),
            (" ", ""),
            ("Where should organized files be stored?", "num"),
        )
    )
    console.print()

    _flush_stdin()
    try:
        choice = inquirer.select(
            message="",
            choices=choices,
            pointer=G.pointer,
            default="__in_place__",
            style=get_style(
                {
                    "questionmark": "#5eead4",
                    "answermark": "#4ade80",
                    "answer": "#86efac",
                    "pointer": "#5eead4 bold",
                    "separator": "#374151",
                    "instruction": "#64748b",
                }
            ),
            qmark="",
            amark=f"  {G.ok}",
            instruction="(↑/↓ to navigate, enter to select, ctrl+c to cancel)",
            transformer=lambda x: "  In-place" if x == "__in_place__" else ("  Custom destination..." if x == "__custom__" else f"  {tilde(x)}"),
        ).execute()

        if not choice:
            return False, None

        if choice == "__in_place__":
            return True, None

        if choice == "__custom__":
            custom_path = prompt_directory("Destination directory:", default=str(source_dir))
            if not custom_path:
                return False, None
            p = Path(custom_path).expanduser().resolve()
            p.mkdir(parents=True, exist_ok=True)
            return True, p

        p = Path(choice).expanduser().resolve()
        p.mkdir(parents=True, exist_ok=True)
        return True, p

    except (KeyboardInterrupt, EOFError):
        return False, None


def prompt_text(message: str, default: str = "") -> str | None:
    """Prompt user for text input with InquirerPy."""
    import sys

    if not sys.stdin.isatty():
        return None

    try:
        from InquirerPy import get_style, inquirer
    except ImportError:
        return None

    try:
        result = inquirer.text(
            message=message,
            default=default,
            qmark=f"  {G.diamond}",
            amark=f"  {G.ok}",
            style=get_style(
                {
                    "questionmark": "#5eead4",
                    "answermark": "#4ade80",
                    "answer": "#86efac",
                    "input": "#ffffff",
                    "question": "#94a3b8",
                }
            ),
        ).execute()
        return result
    except (KeyboardInterrupt, EOFError, Exception):
        return None


def prompt_confirm(message: str, default: bool = True) -> bool | None:
    """Prompt user for yes/no confirmation with InquirerPy."""
    import sys

    if not sys.stdin.isatty():
        return None

    _flush_stdin()
    try:
        from InquirerPy import get_style, inquirer
    except ImportError:
        return None

    try:
        result = inquirer.confirm(
            message=message,
            default=default,
            qmark=f"  {G.diamond}",
            amark=f"  {G.ok}",
            style=get_style(
                {
                    "questionmark": "#5eead4",
                    "answermark": "#4ade80",
                    "answer": "#86efac",
                    "input": "#ffffff",
                    "question": "#94a3b8",
                }
            ),
            transformer=lambda x: "  Yes" if x else "  No",
        ).execute()
        return result
    except (KeyboardInterrupt, EOFError, Exception):
        return None


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
