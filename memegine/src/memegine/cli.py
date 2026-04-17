from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

from . import copy_writer, prompt_engine, reference_lib, shot_list, style_codex
from .config import settings

app = typer.Typer(
    help="Memegine — director's assistant for elite photo/video content. "
         "Offline-first: prints assembled prompts for you to paste into Claude Code or Grok.",
    no_args_is_help=True,
)
console = Console()


def _print_prompt(system: str, user: str, title: str) -> None:
    console.print(Panel.fit(f"[bold cyan]{title}[/]", border_style="cyan"))
    console.print(Panel(system, title="SYSTEM", border_style="magenta"))
    console.print(Panel(user, title="USER (paste into Claude Code / Claude.ai)", border_style="green"))


@app.command("formats")
def list_formats() -> None:
    """List available formats from the library."""
    for f in prompt_engine.load_formats():
        console.print(f"[bold]{f.slug}[/]  [dim]({f.kind})[/]")
        console.print(f"  {f.description.splitlines()[0] if f.description else ''}")


@app.command("prompt")
def make_prompt(
    intent: str = typer.Argument(..., help="Rough operator intent, in quotes."),
    format: str = typer.Option(..., "--format", "-f", help="Format slug. Run `memegine formats` to list."),
    tags: Optional[str] = typer.Option(None, "--tags", help="Comma-separated tags to pull reference notes."),
) -> None:
    """Assemble a production-grade brief and print it for Claude Code / Claude.ai.

    You paste the SYSTEM + USER blocks into any Claude session; Claude returns the
    JSON brief; you paste the 'prompt' field into Grok Imagine.
    """
    settings.ensure_dirs()
    ref_tags = [t.strip() for t in tags.split(",")] if tags else None
    ref_notes = reference_lib.reference_notes_for_prompt(tags=ref_tags) if ref_tags else ""
    system, user = prompt_engine.assemble_offline_prompt(intent, format, reference_notes=ref_notes)
    _print_prompt(system, user, f"Prompt brief — format: {format}")


@app.command("shots")
def make_shots(
    intent: str = typer.Argument(..., help="Rough operator intent for the video."),
) -> None:
    """Assemble a shot-list brief for short video pieces."""
    settings.ensure_dirs()
    system, user = shot_list.assemble_offline_shot_list_prompt(intent)
    _print_prompt(system, user, "Shot list brief")


@app.command("copy")
def make_copy(
    concept: str = typer.Argument(..., help="Describe the piece (what's in the image/video)."),
    kind: str = typer.Option("image", "--kind", "-k", help="image | video"),
) -> None:
    """Assemble a caption-writer brief for the finished piece."""
    settings.ensure_dirs()
    system, user = copy_writer.assemble_offline_copy_prompt(concept, kind)
    _print_prompt(system, user, "X caption brief")


codex_app = typer.Typer(help="Read and update the style codex.")
app.add_typer(codex_app, name="codex")


@codex_app.command("show")
def codex_show() -> None:
    """Print the current style codex."""
    text = style_codex.read()
    if not text:
        console.print("[dim]Codex is empty. It lives at: " + str(settings.codex_path) + "[/]")
        return
    console.print(Syntax(text, "markdown", theme="monokai", word_wrap=True))


@codex_app.command("winner")
def codex_winner(
    prompt: str = typer.Argument(..., help="The prompt that worked."),
    why: str = typer.Argument(..., help="Why it worked — 1 line."),
) -> None:
    """Append a winning prompt pattern to the codex."""
    style_codex.log_winner(prompt, why)
    console.print(f"[green]Logged winner to[/] {settings.codex_path}")


@codex_app.command("flop")
def codex_flop(
    what: str = typer.Argument(..., help="What flopped."),
    why: str = typer.Argument(..., help="Why — 1 line."),
) -> None:
    """Append to the kill list."""
    style_codex.log_flop(what, why)
    console.print(f"[yellow]Logged flop to[/] {settings.codex_path}")


refs_app = typer.Typer(help="Manage the reference library.")
app.add_typer(refs_app, name="refs")


@refs_app.command("add")
def refs_add(
    image: Path = typer.Argument(..., exists=True, readable=True, help="Path to image file."),
    tags: Optional[str] = typer.Option(None, "--tags", help="Comma-separated tags."),
    source: str = typer.Option("", "--source", help="Where this came from, e.g. 'grok', 'shot'."),
    prompt: str = typer.Option("", "--prompt", help="Prompt that produced it, if known."),
    notes: str = typer.Option("", "--notes", help="Why it's a keeper."),
) -> None:
    tag_list = [t.strip() for t in tags.split(",")] if tags else []
    entry = reference_lib.add(image, tags=tag_list, source=source, prompt=prompt, notes=notes)
    console.print(f"[green]Added ref[/] {entry.id} → {entry.filename}")


@refs_app.command("search")
def refs_search(
    tags: Optional[str] = typer.Option(None, "--tags", help="Comma-separated tags (all must match)."),
    text: str = typer.Option("", "--text", help="Substring match across notes/prompt/tags."),
) -> None:
    tag_list = [t.strip() for t in tags.split(",")] if tags else None
    hits = reference_lib.search(tags=tag_list, text=text)
    if not hits:
        console.print("[dim]no matches[/]")
        return
    for e in hits:
        console.print(f"[bold]{e['id']}[/] {e['filename']}  tags=[{', '.join(e.get('tags', []))}]  {e.get('notes', '')[:80]}")


@refs_app.command("recent")
def refs_recent(n: int = typer.Option(10, "-n")) -> None:
    for e in reference_lib.recent(n):
        console.print(f"[bold]{e['id']}[/] {e['filename']}  {e.get('added_at', '')}  {e.get('notes', '')[:80]}")


if __name__ == "__main__":
    app()
