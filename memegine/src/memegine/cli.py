from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

from . import (
    archive,
    audio as audio_mod,
    auto_codex,
    batch as batch_mod,
    caption_linter,
    codex_audit,
    copy_writer,
    deep_linter,
    discord_webhook,
    doctor,
    editor,
    export as export_mod,
    format_suggest,
    fragments,
    grading,
    idea_grader,
    image_ops,
    journal as journal_mod,
    linter,
    music_edit,
    next_action,
    performance,
    pipeline as pipeline_mod,
    prompt_engine,
    reference_lib,
    reverse_engineer,
    scheduler,
    session as session_mod,
    shot_list,
    stats as stats_mod,
    style_codex,
    topics,
    transitions as transitions_mod,
    variants as variants_mod,
    x_post,
)
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
    archive.save(kind="prompt", intent=intent, system=system, user=user, format_=format)
    _print_prompt(system, user, f"Prompt brief — format: {format}")


@app.command("pipeline")
def run_pipeline(
    intent: str = typer.Argument(..., help="Rough operator intent for the piece."),
    kind: str = typer.Option(..., "--kind", "-k", help="image | video"),
    format: Optional[str] = typer.Option(None, "--format", "-f", help="Required for kind=image."),
    no_copy: bool = typer.Option(False, "--no-copy", help="Skip the X caption brief."),
) -> None:
    """One command, one folder, every brief for a whole piece.

    For kind=image: produces prompt brief + copy brief.
    For kind=video: produces shot-list brief + copy brief (the shot-list already
    contains per-shot still + motion prompts).
    """
    settings.ensure_dirs()
    bundle = pipeline_mod.build(
        intent,
        kind=kind,
        format_slug=format,
        include_copy=not no_copy,
    )
    console.print(Panel.fit(f"[bold green]Bundle {bundle.id}[/]  kind={bundle.kind}", border_style="green"))
    console.print(f"folder: [cyan]{bundle.folder}[/]")
    for name in bundle.briefs:
        console.print(f"  - {name} brief -> [dim]{name in bundle.briefs}[/]")
    console.print("\nOpen each `.md` in order and paste into Claude Code.")


@app.command("variants")
def make_variants(
    winner_prompt: str = typer.Argument(..., help="The winning prompt string to vary."),
    n: int = typer.Option(6, "-n", help="How many variants to produce."),
) -> None:
    """Assemble a brief that asks Claude to vary a winning prompt along taxonomy axes."""
    settings.ensure_dirs()
    vb = variants_mod.build_variant_brief(winner_prompt, n_variants=n)
    archive.save(kind="variants", intent=winner_prompt, system=vb.system, user=vb.user, extra={"n": n})
    _print_prompt(vb.system, vb.user, f"Variants brief — n={n}")


@app.command("reverse")
def reverse_brief(
    image: Path = typer.Argument(..., help="Path to an image you want the 'look' of."),
    context: str = typer.Option("", "--context", "-c", help="Optional operator note about what you liked."),
) -> None:
    """Generate a brief that asks Claude to analyze an image and produce a recreate-the-look prompt."""
    settings.ensure_dirs()
    system, user = reverse_engineer.build_reverse_brief(image, context=context)
    archive.save(kind="reverse", intent=str(image), system=system, user=user, extra={"context": context})
    _print_prompt(system, user, f"Reverse brief — {image.name}")


@app.command("lint")
def lint_prompt(
    prompt: str = typer.Argument(..., help="The prompt string to lint (paste in quotes)."),
    motion: bool = typer.Option(False, "--motion", help="Lint as a motion prompt (requires camera move)."),
) -> None:
    """Run the prompt linter. Fails with non-zero exit on banned words."""
    result = linter.lint(prompt, kind="motion" if motion else "image")
    console.print(result.as_text())
    if not result.ok:
        raise typer.Exit(code=1)


@app.command("shots")
def make_shots(
    intent: str = typer.Argument(..., help="Rough operator intent for the video."),
) -> None:
    """Assemble a shot-list brief for short video pieces."""
    settings.ensure_dirs()
    system, user = shot_list.assemble_offline_shot_list_prompt(intent)
    archive.save(kind="shots", intent=intent, system=system, user=user)
    _print_prompt(system, user, "Shot list brief")


@app.command("copy")
def make_copy(
    concept: str = typer.Argument(..., help="Describe the piece (what's in the image/video)."),
    kind: str = typer.Option("image", "--kind", "-k", help="image | video"),
) -> None:
    """Assemble a caption-writer brief for the finished piece."""
    settings.ensure_dirs()
    system, user = copy_writer.assemble_offline_copy_prompt(concept, kind)
    archive.save(kind="copy", intent=concept, system=system, user=user)
    _print_prompt(system, user, "X caption brief")


history_app = typer.Typer(help="Browse the brief archive.")
app.add_typer(history_app, name="history")


@history_app.command("recent")
def history_recent(n: int = typer.Option(10, "-n")) -> None:
    """Show the N most recent briefs."""
    rows = archive.read_recent(n)
    if not rows:
        console.print("[dim]no briefs yet[/]")
        return
    for r in rows:
        fmt = r.get("format") or "-"
        console.print(
            f"[bold]{r['id']}[/] {r['created_at'][:19]}  kind={r['kind']:<8} fmt={fmt:<24} intent={r['intent'][:70]}"
        )


@history_app.command("show")
def history_show(brief_id: str = typer.Argument(..., help="Brief id (prefix)")) -> None:
    """Print a single archived brief by id."""
    rec = archive.find(brief_id)
    if rec is None:
        # also try prefix match
        for candidate in archive.read_recent(200):
            if candidate["id"].startswith(brief_id):
                rec = candidate
                break
    if rec is None:
        console.print(f"[red]not found:[/] {brief_id}")
        raise typer.Exit(code=1)
    console.print(Panel.fit(f"[bold]{rec['id']}[/] {rec['created_at']}", border_style="cyan"))
    console.print(f"kind: {rec['kind']}  format: {rec.get('format') or '-'}")
    console.print(f"intent: {rec['intent']}")
    console.print(Panel(rec["system"], title="SYSTEM", border_style="magenta"))
    console.print(Panel(rec["user"], title="USER", border_style="green"))


@history_app.command("search")
def history_search(text: str = typer.Argument(..., help="Substring to search in intent/user body.")) -> None:
    """Search archived briefs by substring."""
    for r in archive.search(text):
        console.print(f"[bold]{r['id']}[/] {r['created_at'][:19]}  {r['intent'][:90]}")


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


edit_app = typer.Typer(help="FFmpeg-backed video editing (no CapCut).")
app.add_typer(edit_app, name="edit")


@edit_app.command("aspect")
def edit_aspect(
    src: Path = typer.Argument(..., exists=True, readable=True),
    dst: Path = typer.Argument(...),
    ratio: str = typer.Option("9:16", "--ratio", "-r", help="9:16, 1:1, 16:9, 4:5"),
    fit: str = typer.Option("cover", "--fit", help="cover (crop) | contain (pad)"),
) -> None:
    """Reframe a clip or still to a target aspect ratio."""
    if src.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
        out = image_ops.to_aspect(src, ratio, dst, fit=fit)  # type: ignore[arg-type]
    else:
        out = editor.to_aspect(src, ratio, dst, fit=fit)  # type: ignore[arg-type]
    console.print(f"[green]wrote[/] {out}")


@edit_app.command("kenburns")
def edit_kenburns(
    image: Path = typer.Argument(..., exists=True, readable=True),
    dst: Path = typer.Argument(...),
    duration: float = typer.Option(4.0, "--duration", "-d"),
    ratio: str = typer.Option("9:16", "--ratio", "-r"),
    zoom_start: float = typer.Option(1.0),
    zoom_end: float = typer.Option(1.15),
) -> None:
    """Turn a still into a Ken Burns video."""
    out = editor.ken_burns(image, dst, duration=duration, ratio=ratio, zoom_start=zoom_start, zoom_end=zoom_end)  # type: ignore[arg-type]
    console.print(f"[green]wrote[/] {out}")


@edit_app.command("concat")
def edit_concat(
    dst: Path = typer.Argument(...),
    clips: list[Path] = typer.Argument(..., help="Clips in order"),
) -> None:
    """Stitch clips with hard cuts."""
    out = editor.concat(clips, dst)
    console.print(f"[green]wrote[/] {out}")


@edit_app.command("caption")
def edit_caption(
    src: Path = typer.Argument(..., exists=True, readable=True),
    dst: Path = typer.Argument(...),
    text: str = typer.Argument(...),
    position: str = typer.Option("bottom", "--pos", help="top | bottom | center"),
    size: int = typer.Option(0, "--size", help="Font size. 0 = auto from image width."),
) -> None:
    """Burn a caption onto a still or video."""
    if src.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
        fs = size or None
        out = image_ops.caption(src, dst, text, position=position, font_size=fs)  # type: ignore[arg-type]
    else:
        fs = size or 64
        out = editor.drawtext(src, dst, text, position=position, font_size=fs)  # type: ignore[arg-type]
    console.print(f"[green]wrote[/] {out}")


@edit_app.command("grade")
def edit_grade(
    src: Path = typer.Argument(..., exists=True, readable=True),
    dst: Path = typer.Argument(...),
    preset: str = typer.Option(..., "--preset", "-p", help="e.g. portra_400, cinestill_800t"),
) -> None:
    """Apply a color-grading preset."""
    out = grading.apply_preset(src, dst, preset)
    console.print(f"[green]wrote[/] {out}")


@edit_app.command("presets")
def edit_presets() -> None:
    """List available grading presets."""
    for p in grading.list_presets():
        console.print(f"  {p}")


@edit_app.command("speed")
def edit_speed(
    src: Path = typer.Argument(..., exists=True, readable=True),
    dst: Path = typer.Argument(...),
    factor: float = typer.Argument(..., help="e.g. 2.0 = 2x speed, 0.5 = half"),
) -> None:
    """Speed ramp a clip (keeps audio pitch-corrected)."""
    out = editor.speed(src, dst, factor)
    console.print(f"[green]wrote[/] {out}")


@edit_app.command("audio")
def edit_audio(
    src: Path = typer.Argument(..., exists=True, readable=True),
    audio: Path = typer.Argument(..., exists=True, readable=True),
    dst: Path = typer.Argument(...),
    mode: str = typer.Option("mix", "--mode", help="mix | replace"),
    volume: float = typer.Option(1.0, "--volume"),
) -> None:
    """Attach an audio track (mix with existing, or replace)."""
    out = editor.add_audio(src, audio, dst, mode=mode, volume=volume)  # type: ignore[arg-type]
    console.print(f"[green]wrote[/] {out}")


@edit_app.command("grid")
def edit_grid(
    dst: Path = typer.Argument(...),
    images: list[Path] = typer.Argument(..., help="Images to grid together"),
    cols: int = typer.Option(2, "--cols"),
) -> None:
    """Pack images into a grid (for Grok variant sheets)."""
    out = image_ops.grid(images, dst, cols=cols)
    console.print(f"[green]wrote[/] {out}")


@edit_app.command("two-panel")
def edit_two_panel(
    top: Path = typer.Argument(..., exists=True, readable=True),
    bottom: Path = typer.Argument(..., exists=True, readable=True),
    dst: Path = typer.Argument(...),
) -> None:
    """Stack two images into a meme two-panel layout (4:5)."""
    out = image_ops.two_panel(top, bottom, dst)
    console.print(f"[green]wrote[/] {out}")


music_app = typer.Typer(help="Music-synced edits. Beat detection + template rendering.")
app.add_typer(music_app, name="music")


@music_app.command("plan")
def music_plan(
    audio_file: Path = typer.Argument(..., exists=True, readable=True),
    intent: str = typer.Argument(..., help="Rough intent for the edit."),
    clips: list[Path] = typer.Argument(..., help="Available clip files, in order."),
) -> None:
    """Assemble a music-edit planning brief (paste into Claude Code / Claude.ai).

    Analyzes the audio, reads the clip list, and prints the SYSTEM + USER
    blocks that ask Claude to plan the whole edit (template, segments,
    transitions, text overlays, exact CLI command).
    """
    from . import music_brief
    settings.ensure_dirs()
    grid = audio_mod.analyze(audio_file)
    drop = audio_mod.find_drop(grid)
    clip_descs = [str(c) for c in clips]
    system, user = music_brief.build_music_brief(
        intent,
        music_metadata={
            "path": str(audio_file),
            "tempo_bpm": grid.tempo_bpm,
            "duration_sec": grid.duration,
            "beats": grid.beats,
            "drop_sec": drop,
        },
        clips_description=clip_descs,
    )
    archive.save(kind="music_plan", intent=intent, system=system, user=user, extra={"clips": clip_descs})
    _print_prompt(system, user, "Music-edit plan brief")


@music_app.command("beats")
def music_beats(
    audio_file: Path = typer.Argument(..., exists=True, readable=True, help="Audio file (mp3/wav/m4a)."),
) -> None:
    """Print detected BPM + beat timestamps."""
    grid = audio_mod.analyze(audio_file)
    console.print(f"[bold]{audio_file.name}[/]")
    console.print(f"  tempo: [cyan]{grid.tempo_bpm:.1f} BPM[/]  duration: {grid.duration:.2f}s  beats: {len(grid.beats)}")
    console.print(f"  avg interval: {grid.avg_beat_interval:.3f}s")
    console.print(f"  first 12 beats: {[f'{t:.2f}' for t in grid.beats[:12]]}")
    drop = audio_mod.find_drop(grid)
    if drop is not None:
        console.print(f"  estimated drop: [yellow]{drop:.2f}s[/]")


@music_app.command("hardcut")
def music_hardcut(
    dst: Path = typer.Argument(...),
    music: Path = typer.Argument(..., exists=True, readable=True),
    clips: list[Path] = typer.Argument(..., help="Clips in order (will be cycled if fewer than beats allow)."),
    beats_per_cut: int = typer.Option(1, "--bpc", help="Beats between cuts (1 = cut every beat; 2 = every 2 beats)."),
    start_beat: int = typer.Option(0, "--start", help="Which beat index to begin on."),
) -> None:
    """Hard-cut montage: one cut per beat (or per N beats). Music carried through."""
    out = music_edit.hard_cut_montage(
        clips, music, dst, beats_per_cut=beats_per_cut, start_beat=start_beat,
    )
    console.print(f"[green]wrote[/] {out}")


@music_app.command("build")
def music_build(
    dst: Path = typer.Argument(...),
    music: Path = typer.Argument(..., exists=True, readable=True),
    clips: list[Path] = typer.Argument(...),
    start_beat: int = typer.Option(0, "--start"),
    start_per_cut: int = typer.Option(4, "--start-per-cut"),
    end_per_cut: int = typer.Option(1, "--end-per-cut"),
) -> None:
    """Rhythmic build: cuts accelerate from long to short."""
    out = music_edit.rhythmic_build(
        clips, music, dst,
        start_beat=start_beat, start_per_cut=start_per_cut, end_per_cut=end_per_cut,
    )
    console.print(f"[green]wrote[/] {out}")


@music_app.command("slam")
def music_slam(
    dst: Path = typer.Argument(...),
    music: Path = typer.Argument(..., exists=True, readable=True),
    clip: Path = typer.Argument(..., exists=True, readable=True),
    slam: float = typer.Option(-1.0, "--slam", help="Time of the slam beat in seconds. Negative = auto-detect drop."),
    ramp_in: float = typer.Option(1.5, "--ramp-in", help="Seconds of slow-mo before the slam."),
    slow: float = typer.Option(0.4, "--slow", help="Slow-mo factor (0.4 = 40% speed)."),
    post: float = typer.Option(1.0, "--post", help="Seconds at normal speed after the slam."),
) -> None:
    """Slow-mo speed ramp into a beat, snap to normal speed on the beat."""
    slam_val = None if slam < 0 else slam
    out = music_edit.speed_ramp_slam(
        clip, music, dst,
        slam_beat_sec=slam_val, ramp_in_sec=ramp_in, slow_factor=slow, post_slam_sec=post,
    )
    console.print(f"[green]wrote[/] {out}")


@music_app.command("impact")
def music_impact(
    dst: Path = typer.Argument(...),
    music: Path = typer.Argument(..., exists=True, readable=True),
    clips: list[Path] = typer.Argument(...),
    flash: str = typer.Option("white", "--flash", help="white | black"),
    flash_frames: int = typer.Option(2, "--frames"),
    beats_per_cut: int = typer.Option(1, "--bpc"),
) -> None:
    """Hard cuts between clips with a N-frame flash on each transition."""
    out = music_edit.impact_frame_chain(
        clips, music, dst,
        flash_color=flash, flash_frames=flash_frames, beats_per_cut=beats_per_cut,
    )
    console.print(f"[green]wrote[/] {out}")


@music_app.command("reveal")
def music_reveal(
    dst: Path = typer.Argument(...),
    music: Path = typer.Argument(..., exists=True, readable=True),
    clip: Path = typer.Argument(..., exists=True, readable=True),
    duration: float = typer.Option(8.0, "--duration", "-d"),
    audio_start: float = typer.Option(0.0, "--audio-start"),
) -> None:
    """One clip or still, slow push-in, music underneath. The 'vibe' template."""
    out = music_edit.aesthetic_slow_reveal(
        clip, music, dst, duration=duration, audio_start=audio_start,
    )
    console.print(f"[green]wrote[/] {out}")


@music_app.command("trailer")
def music_trailer(
    dst: Path = typer.Argument(...),
    music: Path = typer.Argument(..., exists=True, readable=True),
    clips: list[Path] = typer.Argument(..., help="Last clip is the hero held through the slam."),
    slam: float = typer.Option(-1.0, "--slam", help="Slam time in seconds. Negative = auto-detect."),
    pre_build: float = typer.Option(6.0, "--pre-build"),
    post_slam: float = typer.Option(2.0, "--post-slam"),
) -> None:
    """Trailer: long cuts -> accelerating -> slam -> held hero shot."""
    slam_val = None if slam < 0 else slam
    out = music_edit.trailer_build(
        clips, music, dst,
        slam_beat_sec=slam_val, pre_build_seconds=pre_build, post_slam_seconds=post_slam,
    )
    console.print(f"[green]wrote[/] {out}")


@music_app.command("transitions")
def music_list_transitions() -> None:
    """List available transition presets."""
    console.print("[bold]Transition presets[/]")
    for p in transitions_mod.list_presets():
        cfg = transitions_mod.TRANSITION_PRESETS[p]
        console.print(f"  {p}  ({cfg['type']}, {cfg['duration']}s)")
    console.print("\n[bold]Raw xfade types[/]")
    console.print("  " + ", ".join(transitions_mod.list_transitions()))


@music_app.command("transition")
def music_transition(
    dst: Path = typer.Argument(...),
    clip_a: Path = typer.Argument(..., exists=True, readable=True),
    clip_b: Path = typer.Argument(..., exists=True, readable=True),
    preset: str = typer.Option(..., "--preset", "-p", help="e.g. flash_white, whip_left, zoom_punch"),
) -> None:
    """Apply a single transition between two clips (preview / testing use)."""
    out = transitions_mod.apply_preset(clip_a, clip_b, dst, preset)
    console.print(f"[green]wrote[/] {out}")


refs_app = typer.Typer(help="Manage the reference library.")
app.add_typer(refs_app, name="refs")


@refs_app.command("add")
def refs_add(
    image: Path = typer.Argument(..., exists=True, readable=True, help="Path to image file."),
    tags: Optional[str] = typer.Option(None, "--tags", help="Comma-separated tags."),
    source: str = typer.Option("", "--source", help="Where this came from, e.g. 'grok', 'shot'."),
    prompt: str = typer.Option("", "--prompt", help="Prompt that produced it, if known."),
    notes: str = typer.Option("", "--notes", help="Why it's a keeper."),
    winner: bool = typer.Option(
        False, "--winner", help="Mark as a winner + auto-extract patterns into the codex."
    ),
) -> None:
    tag_list = [t.strip() for t in tags.split(",")] if tags else []
    entry = reference_lib.add(
        image, tags=tag_list, source=source, prompt=prompt, notes=notes, winner=winner
    )
    console.print(f"[green]Added ref[/] {entry.id} → {entry.filename}")
    if winner and prompt:
        patterns = auto_codex.extract(prompt)
        if not patterns.is_empty():
            console.print(f"[cyan]extracted patterns:[/] {patterns.as_codex_line()}")


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


# ---------------------------------------------------------------------------
# Topic queue — drop intents / trends into a file, drain them in batches.
# ---------------------------------------------------------------------------

topics_app = typer.Typer(help="Topic queue: drop intents/trends, drain in batches.")
app.add_typer(topics_app, name="topics")


@topics_app.command("add")
def topics_add(
    text: str = typer.Argument(..., help="Intent / topic text."),
    tags: Optional[str] = typer.Option(None, "--tags", help="Comma-separated tags."),
    kind: str = typer.Option("any", "--kind", help="image | video | any"),
    format_hint: Optional[str] = typer.Option(None, "--format", help="Force a format slug."),
    priority: int = typer.Option(3, "--priority", "-p", help="1 (low) .. 5 (urgent)"),
) -> None:
    """Append a topic to the queue."""
    tag_list = [t.strip() for t in tags.split(",")] if tags else []
    t = topics.add(
        text, tags=tag_list, kind=kind, format_hint=format_hint, priority=priority
    )
    console.print(f"[green]queued[/] {t.id} (priority {t.priority}): {t.text}")


@topics_app.command("list")
def topics_list(
    n: int = typer.Option(20, "-n"),
    status: str = typer.Option("queued", "--status", help="queued | used | skipped"),
) -> None:
    rows = topics.list_queued(limit=n, status=status)
    if not rows:
        console.print("[dim]none[/]")
        return
    for t in rows:
        console.print(
            f"[bold]{t['id']}[/] p={t.get('priority', 3)}  "
            f"kind={t.get('kind', 'any')}  {t.get('text', '')[:80]}"
        )


@topics_app.command("pop")
def topics_pop(
    n: int = typer.Option(1, "-n"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Don't mark as used."),
) -> None:
    picked = topics.pop(n=n, mark_used=not dry_run)
    if not picked:
        console.print("[dim]queue empty[/]")
        return
    for t in picked:
        console.print(f"[bold]{t['id']}[/]  {t.get('text', '')[:100]}")


@topics_app.command("remove")
def topics_remove(topic_id: str = typer.Argument(...)) -> None:
    if topics.remove(topic_id):
        console.print(f"[yellow]removed[/] {topic_id}")
    else:
        console.print(f"[red]not found[/] {topic_id}")
        raise typer.Exit(code=1)


@topics_app.command("stats")
def topics_stats() -> None:
    st = topics.stats()
    console.print(
        f"total={st['total']}  queued={st.get('queued', 0)}  "
        f"used={st.get('used', 0)}  skipped={st.get('skipped', 0)}"
    )


# ---------------------------------------------------------------------------
# Scheduler — cron-style automated brief batches.
# ---------------------------------------------------------------------------

schedule_app = typer.Typer(help="Scheduler: automated brief batches.")
app.add_typer(schedule_app, name="schedule")


@schedule_app.command("add")
def schedule_add(
    name: str = typer.Argument(..., help="Human-readable job name."),
    hour: int = typer.Option(..., "--hour", help="0-23 local hour."),
    minute: int = typer.Option(0, "--minute"),
    days: Optional[str] = typer.Option(
        None, "--days", help="Comma-separated 0-6 (Mon-Sun). Default: daily.",
    ),
    action: str = typer.Option("daily_batch", "--action", help="daily_batch | weekly_distill"),
    n_topics: int = typer.Option(3, "--n", help="Topics per fire (daily_batch only)."),
    kind: str = typer.Option("any", "--kind"),
    delivery: str = typer.Option("file", "--delivery", help="file | telegram | stdout"),
) -> None:
    dow = [int(d) for d in days.split(",")] if days else None
    job = scheduler.add(
        name=name, hour=hour, minute=minute, days_of_week=dow,
        action=action, n_topics=n_topics, kind=kind, delivery=delivery,
    )
    console.print(f"[green]scheduled[/] {job.id} {job.name} at {job.hour:02d}:{job.minute:02d}")


@schedule_app.command("list")
def schedule_list() -> None:
    rows = scheduler.list_jobs()
    if not rows:
        console.print("[dim]no jobs[/]")
        return
    for j in rows:
        on = "on " if j.get("enabled", True) else "OFF"
        console.print(
            f"[bold]{j['id']}[/] {on}  {j.get('hour', 0):02d}:{j.get('minute', 0):02d}  "
            f"{j.get('action', '-'):<16} n={j.get('n_topics', '-')} kind={j.get('kind', 'any')}  {j['name']}"
        )


@schedule_app.command("remove")
def schedule_remove(job_id: str = typer.Argument(...)) -> None:
    if scheduler.remove(job_id):
        console.print(f"[yellow]removed[/] {job_id}")
    else:
        console.print(f"[red]not found[/] {job_id}")
        raise typer.Exit(code=1)


@schedule_app.command("enable")
def schedule_enable(job_id: str = typer.Argument(...)) -> None:
    if scheduler.set_enabled(job_id, True):
        console.print(f"[green]enabled[/] {job_id}")
    else:
        raise typer.Exit(code=1)


@schedule_app.command("disable")
def schedule_disable(job_id: str = typer.Argument(...)) -> None:
    if scheduler.set_enabled(job_id, False):
        console.print(f"[yellow]disabled[/] {job_id}")
    else:
        raise typer.Exit(code=1)


@schedule_app.command("fire")
def schedule_fire(job_id: str = typer.Argument(...)) -> None:
    """Fire a job manually (use from cron / Task Scheduler)."""
    res = scheduler.fire(job_id)
    console.print(
        f"[green]fired[/] {res.job_id}  bundles={res.bundles}  note={res.note}"
    )


@schedule_app.command("run")
def schedule_run(
    poll: int = typer.Option(30, "--poll", help="Seconds between checks."),
    telegram_notify: bool = typer.Option(
        False, "--telegram", help="Also push results to the configured telegram chat."
    ),
) -> None:
    """Blocking scheduler loop. Runs jobs as their time comes around."""
    deliver = None
    if telegram_notify:
        from . import telegram_bot
        cfg = telegram_bot.BotConfig.from_env()
        deliver = lambda job, result: telegram_bot.send_scheduler_result(cfg, job, result)
    console.print(f"[bold]scheduler running[/] poll={poll}s telegram_notify={telegram_notify}")
    scheduler.run_loop(poll_seconds=poll, deliver=deliver)


# ---------------------------------------------------------------------------
# Format suggest — intent → ranked format slugs.
# ---------------------------------------------------------------------------


@app.command("suggest")
def suggest_cmd(
    intent: str = typer.Argument(...),
    kind: Optional[str] = typer.Option(None, "--kind", help="image | video (filter)"),
    top_n: int = typer.Option(3, "-n"),
) -> None:
    """Suggest the top-N format slugs for a rough intent."""
    console.print(f"inferred kind: [cyan]{format_suggest.infer_kind(intent)}[/]")
    for p in format_suggest.suggest(intent, top_n=top_n, kind=kind):
        console.print(
            f"  [bold]{p.slug}[/]  ({p.kind})  score=[yellow]{p.score}[/]  hits={p.reasons}"
        )


# ---------------------------------------------------------------------------
# Deep lint — score a prompt 0-100 for craft coverage.
# ---------------------------------------------------------------------------


@app.command("score")
def score_cmd(
    prompt: str = typer.Argument(...),
    motion: bool = typer.Option(False, "--motion"),
) -> None:
    """Score a prompt 0-100 for craft coverage with line-by-line breakdown."""
    sc = deep_linter.score(prompt, kind="motion" if motion else "image")
    grade = deep_linter.grade(sc.score)
    console.print(f"[bold]grade {grade}[/]")
    console.print(sc.as_text())
    if sc.banned:
        raise typer.Exit(code=1)


@app.command("grade-idea")
def grade_idea_cmd(
    intent: str = typer.Argument(..., help="The rough intent / topic text."),
) -> None:
    """Grade an intent 0-100 for landability (specificity, emotion, format-fit)."""
    g = idea_grader.grade(intent)
    console.print(f"[bold]{g.letter}  {g.score}/100[/]")
    console.print(g.as_text())
    if g.format_hits:
        console.print(f"[cyan]matching formats:[/] {', '.join(g.format_hits)}")


@app.command("execute")
def execute_cmd(
    intent: str = typer.Argument(..., help="Rough operator intent."),
    format: Optional[str] = typer.Option(None, "--format", "-f", help="Format slug (auto-picks if omitted)."),
    model: Optional[str] = typer.Option(None, "--model", help="Override Anthropic model id."),
) -> None:
    """Run the brief through Claude and return the finished prompt + variants.

    Requires ANTHROPIC_API_KEY and `pip install -e '.[online]'`.
    """
    from . import executor as ex
    if not ex.api_key_available():
        console.print("[red]ANTHROPIC_API_KEY not set[/] — use `memegine prompt` for offline mode.")
        raise typer.Exit(code=1)
    slug = format or format_suggest.best(intent, kind="image")
    brief = ex.execute_prompt_brief(intent, slug, model=model)
    console.print(f"[green]executed[/] format={slug} model={brief.model}")
    console.print(Panel(brief.prompt or "(no prompt)", title="PROMPT", border_style="cyan"))
    if brief.variants:
        console.print(Panel("\n".join(f"- {v}" for v in brief.variants), title="VARIANTS"))
    if brief.captions:
        lines = []
        for c in brief.captions[:5]:
            lines.append(
                f"[{c.get('length', '?')}] {c.get('text', '')}" if isinstance(c, dict) else str(c)
            )
        console.print(Panel("\n".join(lines), title="CAPTIONS"))


# ---------------------------------------------------------------------------
# Post / export — pack a finished piece into a post-ready folder.
# ---------------------------------------------------------------------------

post_app = typer.Typer(help="Post-ready export bundles.")
app.add_typer(post_app, name="post")


@post_app.command("build")
def post_build(
    media: Path = typer.Argument(..., exists=True, readable=True, help="Final media file."),
    caption: str = typer.Option(..., "--caption", "-c", help="Post body text."),
    alt_text: str = typer.Option("", "--alt", help="Accessibility description."),
    reply_hook: str = typer.Option("", "--reply", help="Optional follow-up reply."),
    tags: Optional[str] = typer.Option(None, "--tags"),
    from_bundle: Optional[str] = typer.Option(None, "--from-bundle", help="Source pipeline bundle id."),
    from_ref: Optional[str] = typer.Option(None, "--from-ref", help="Source reference id."),
) -> None:
    tag_list = [t.strip() for t in tags.split(",")] if tags else None
    bundle = export_mod.build(
        media_path=media, caption=caption, alt_text=alt_text, reply_hook=reply_hook,
        tags=tag_list, source_bundle_id=from_bundle, source_ref_id=from_ref,
    )
    console.print(f"[green]post bundle[/] {bundle.id} → {bundle.folder}")


@post_app.command("list")
def post_list(n: int = typer.Option(20, "-n")) -> None:
    for b in export_mod.list_recent(n):
        console.print(f"[bold]{b.get('id')}[/]  {b.get('caption', '')[:70]}")


# ---------------------------------------------------------------------------
# Codex — extended with auto-extract winners.
# ---------------------------------------------------------------------------


@codex_app.command("distill")
def codex_distill(
    n_briefs: int = typer.Option(200, "--n", help="How many recent archived briefs to scan."),
    min_frequency: int = typer.Option(2, "--min", help="Keep only patterns seen >= N times."),
) -> None:
    """Mine recent briefs for common craft patterns and write to codex."""
    recent = archive.read_recent(n=n_briefs)
    prompts = [r.get("user", "") for r in recent]
    dist = auto_codex.distill_to_codex(prompts, min_frequency=min_frequency)
    for cat, items in dist.items():
        if items:
            console.print(f"{cat}: " + ", ".join(f"{v}×{c}" for v, c in items[:5]))


@codex_app.command("auto-winner")
def codex_auto_winner(
    prompt: str = typer.Argument(..., help="The winning prompt."),
    why: str = typer.Argument(..., help="Why it worked."),
) -> None:
    """Log a winner AND auto-extract named patterns (lens, film, lighting, etc.)."""
    patterns = auto_codex.record_winner(prompt, why)
    if patterns.is_empty():
        console.print("[yellow]no extractable craft tokens — codex got the raw line only[/]")
    else:
        console.print(f"[green]logged[/] → {patterns.as_codex_line()}")


# ---------------------------------------------------------------------------
# Telegram bot.
# ---------------------------------------------------------------------------

bot_app = typer.Typer(help="Telegram bot: brief delivery to your phone.")
app.add_typer(bot_app, name="bot")


@bot_app.command("run")
def bot_run() -> None:
    """Blocking poll-mode bot. Set MEMEGINE_TELEGRAM_BOT_TOKEN and MEMEGINE_TELEGRAM_ALLOWED_USER_IDS."""
    from . import telegram_bot  # lazy, optional dep
    cfg = telegram_bot.BotConfig.from_env()
    console.print(
        f"[bold cyan]bot starting[/] allowlist={sorted(cfg.allowed_user_ids)} "
        f"scheduler_chat={cfg.chat_id_for_scheduler}"
    )
    telegram_bot.run_bot(cfg)


@bot_app.command("config-check")
def bot_config_check() -> None:
    """Verify env vars are set without starting the bot."""
    from . import telegram_bot
    cfg = telegram_bot.BotConfig.from_env()
    token_state = "SET" if cfg.token else "MISSING"
    console.print(
        f"token: [bold]{token_state}[/]\n"
        f"allowlist: {sorted(cfg.allowed_user_ids) or 'EMPTY (bot will refuse to start)'}\n"
        f"scheduler_chat: {cfg.chat_id_for_scheduler or 'not set'}"
    )


# ---------------------------------------------------------------------------
# Batch — N briefs across varied formats for one theme.
# ---------------------------------------------------------------------------


@app.command("batch")
def batch_cmd(
    theme: str = typer.Argument(..., help="The piece theme."),
    n: int = typer.Option(4, "-n", help="How many briefs to generate."),
    formats: Optional[str] = typer.Option(
        None, "--formats", help="Comma-separated format slugs (overrides default rotation)."
    ),
    by_perf: bool = typer.Option(
        False, "--by-perf",
        help="Rank formats by recorded engagement (requires performance history).",
    ),
) -> None:
    """Generate N briefs for one theme across different visual registers."""
    slugs = [f.strip() for f in formats.split(",")] if formats else None
    result = batch_mod.build(theme, n=n, formats=slugs, by_performance=by_perf)
    console.print(f"[green]batch {result.id}[/] → {result.folder}")
    for i, item in enumerate(result.items, 1):
        console.print(f"  {i:02d}. {item.format_slug}  → {Path(item.brief_path).name}")


# ---------------------------------------------------------------------------
# Caption lint — validates X captions.
# ---------------------------------------------------------------------------


@app.command("caption-lint")
def caption_lint_cmd(
    caption: str = typer.Argument(..., help="Caption text to validate."),
) -> None:
    """Validate an X caption (no emojis, no hashtags, no banned phrases)."""
    result = caption_linter.lint(caption)
    console.print(result.as_text())
    if not result.ok:
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# Stats — daily / weekly activity report.
# ---------------------------------------------------------------------------


@app.command("stats")
def stats_cmd(
    window: str = typer.Argument("daily", help="daily | weekly | all"),
) -> None:
    """Print a memegine activity report for the given window."""
    report = stats_mod.compute(window=window)
    console.print(report.as_text())


# ---------------------------------------------------------------------------
# Discord webhook test.
# ---------------------------------------------------------------------------


@app.command("discord-test")
def discord_test_cmd(
    message: str = typer.Argument("memegine discord webhook test", help="Message to send."),
) -> None:
    """Send a test message to the configured Discord webhook."""
    cfg = discord_webhook.DiscordConfig.from_env()
    if not cfg.webhook_url:
        console.print("[red]MEMEGINE_DISCORD_WEBHOOK_URL is not set[/]")
        raise typer.Exit(code=1)
    status = discord_webhook.send(message, cfg=cfg)
    console.print(f"[{'green' if status < 400 else 'red'}]status {status}[/]")


# ---------------------------------------------------------------------------
# Pipeline build-from-topic — convenience for turning a queued topic into a bundle.
# ---------------------------------------------------------------------------


@app.command("from-topic")
def from_topic_cmd(
    topic_id: str = typer.Argument(..., help="Topic id from `memegine topics list`."),
    kind: Optional[str] = typer.Option(None, "--kind", help="image | video — overrides topic's kind."),
    format: Optional[str] = typer.Option(None, "--format", help="Override format slug."),
) -> None:
    """Build a pipeline bundle for a specific queued topic and mark it used."""
    bundle = pipeline_mod.build_from_topic(
        topic_id, kind_override=kind, format_override=format
    )
    console.print(f"[green]bundle {bundle.id}[/]  kind={bundle.kind}  → {bundle.folder}")


# ---------------------------------------------------------------------------
# Codex graduate — promote frequent patterns to Core Patterns.
# ---------------------------------------------------------------------------


@codex_app.command("graduate")
def codex_graduate_cmd(
    threshold: int = typer.Option(5, "--threshold", help="Minimum occurrences to promote."),
    n_briefs: int = typer.Option(500, "--n", help="Recent briefs to scan."),
) -> None:
    """Promote patterns seen >= threshold times into the 'Core Patterns' codex section."""
    recent = archive.read_recent(n=n_briefs)
    prompts = [r.get("user", "") for r in recent]
    promoted = auto_codex.graduate_patterns(prompts, promotion_threshold=threshold)
    if not promoted:
        console.print("[yellow]no patterns crossed the threshold[/]")
        return
    for cat, items in promoted.items():
        console.print(f"{cat}: " + ", ".join(f"{v}×{c}" for v, c in items[:5]))


# ---------------------------------------------------------------------------
# Doctor — health check.
# ---------------------------------------------------------------------------


@app.command("doctor")
def doctor_cmd() -> None:
    """Run the memegine health check."""
    report = doctor.run()
    console.print(report.as_text())
    if not report.ok:
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# Variants from last winner — 1-command compounding shortcut.
# ---------------------------------------------------------------------------


@app.command("variants-last")
def variants_last_cmd(
    n: int = typer.Option(6, "-n", help="Number of variants."),
    axes: Optional[str] = typer.Option(
        None, "--axes",
        help="Comma-separated axes to vary (default: TIME_OF_DAY,LENS,FILM_STOCK,LIGHTING,COMPOSITION,MOOD).",
    ),
) -> None:
    """Pull the most recent winner prompt and build a variant brief from it."""
    axis_list = [a.strip() for a in axes.split(",")] if axes else None
    try:
        vb = variants_mod.build_from_last_winner(n_variants=n, axes=axis_list)
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(code=1)
    archive.save(kind="variants_last", intent="last_winner", system=vb.system, user=vb.user, extra={"n": n})
    _print_prompt(vb.system, vb.user, f"Variants-from-last-winner  n={n}")


# ---------------------------------------------------------------------------
# Fragments — named reusable craft snippets.
# ---------------------------------------------------------------------------

fragments_app = typer.Typer(help="Named reusable craft snippets (LENS.35mm_1_4, LIGHTING.harsh_window, ...).")
app.add_typer(fragments_app, name="fragments")


@fragments_app.command("list")
def fragments_list(
    category: Optional[str] = typer.Argument(None, help="If given, list fragments in this category only."),
) -> None:
    if category:
        names = fragments.list_names(category)
        if not names:
            console.print(f"[dim]no fragments in category {category}[/]")
            return
        for n in names:
            body = fragments.get(category, n)
            console.print(f"  [bold]{category}.{n}[/]  [dim]{body[:80]}[/]")
    else:
        for cat in fragments.list_categories():
            names = fragments.list_names(cat)
            console.print(f"[bold]{cat}[/]  ({len(names)})  {', '.join(names)}")


@fragments_app.command("show")
def fragments_show(
    token: str = typer.Argument(..., help="CATEGORY.name — e.g. LIGHTING.harsh_window"),
) -> None:
    if "." not in token:
        console.print("[red]expected CATEGORY.name[/]")
        raise typer.Exit(code=1)
    cat, name = token.split(".", 1)
    body = fragments.get(cat, name)
    if body is None:
        console.print(f"[red]not found: {token}[/]")
        raise typer.Exit(code=1)
    console.print(f"[bold]{cat}.{name}[/]")
    console.print(body)


@fragments_app.command("expand")
def fragments_expand(
    text: str = typer.Argument(..., help="Text with fragment tokens to expand."),
    missing: str = typer.Option("keep", "--missing", help="keep | drop | error"),
) -> None:
    try:
        expanded = fragments.expand(text, missing=missing)
    except KeyError as exc:
        console.print(f"[red]unknown fragment: {exc}[/]")
        raise typer.Exit(code=1)
    console.print(expanded)


@fragments_app.command("validate")
def fragments_validate(
    text: str = typer.Argument(..., help="Text to check for unknown fragment tokens."),
) -> None:
    unknown = fragments.validate(text)
    if not unknown:
        console.print("[green]all fragment tokens resolve[/]")
        return
    for cat, name in unknown:
        console.print(f"  [yellow]unknown:[/] {cat}.{name}")
    raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# Performance tracking.
# ---------------------------------------------------------------------------

perf_app = typer.Typer(help="Log post engagement and query performance by format/pattern/hour.")
app.add_typer(perf_app, name="perf")


@perf_app.command("log")
def perf_log(
    likes: int = typer.Option(0, "--likes"),
    reposts: int = typer.Option(0, "--rt", help="Reposts / retweets."),
    replies: int = typer.Option(0, "--replies"),
    quotes: int = typer.Option(0, "--quotes"),
    impressions: int = typer.Option(0, "--impressions"),
    bookmarks: int = typer.Option(0, "--bookmarks"),
    format: Optional[str] = typer.Option(None, "--format"),
    post_bundle: Optional[str] = typer.Option(None, "--bundle"),
    url: str = typer.Option("", "--url"),
    posted_at: str = typer.Option("", "--posted-at", help="ISO timestamp of when the post went live."),
    window: str = typer.Option("24h", "--window", help="24h | 7d | 30d"),
    patterns: Optional[str] = typer.Option(None, "--patterns", help="Comma-separated craft tokens."),
    notes: str = typer.Option("", "--notes"),
) -> None:
    """Log engagement for a post."""
    pat_list = [p.strip() for p in patterns.split(",")] if patterns else None
    entry = performance.log(
        post_bundle_id=post_bundle, post_url=url, format_slug=format,
        patterns=pat_list, posted_at=posted_at,
        likes=likes, reposts=reposts, replies=replies, quotes=quotes,
        impressions=impressions, bookmarks=bookmarks,
        window=window, notes=notes,
    )
    console.print(f"[green]logged[/] {entry.id}  score≈{performance._score_entry(asdict_or_dict(entry)):.1f}")


def asdict_or_dict(obj):
    """Small util for older dataclass objects that don't convert with vars."""
    from dataclasses import asdict, is_dataclass
    return asdict(obj) if is_dataclass(obj) else dict(obj)


@perf_app.command("summary")
def perf_summary() -> None:
    """Print a performance summary (by format, by pattern, by hour)."""
    console.print(performance.summary_text())


@perf_app.command("by-format")
def perf_by_format() -> None:
    for slug, n, avg in performance.by_format():
        console.print(f"  {slug:<28} n={n:<3}  avg={avg:.1f}")


@perf_app.command("top")
def perf_top(n: int = typer.Option(10, "-n")) -> None:
    for e in performance.top_n(n):
        console.print(
            f"  [{e.get('format_slug', '-')}]  "
            f"likes={e.get('likes', 0)}  rt={e.get('reposts', 0)}  "
            f"replies={e.get('replies', 0)}  url={e.get('post_url') or '-'}"
        )


# ---------------------------------------------------------------------------
# Sessions — mark start/end of working blocks.
# ---------------------------------------------------------------------------

session_app = typer.Typer(help="Mark session boundaries for bucketing activity.")
app.add_typer(session_app, name="session")


@session_app.command("start")
def session_start(
    name: str = typer.Argument("", help="Optional session name."),
    notes: str = typer.Option("", "--notes"),
) -> None:
    event = session_mod.start(name=name, notes=notes)
    console.print(f"[green]started[/] session {event.session_id}  name={event.name or '-'}")


@session_app.command("end")
def session_end(notes: str = typer.Option("", "--notes")) -> None:
    event = session_mod.end(notes=notes)
    if event is None:
        console.print("[yellow]no open session[/]")
        raise typer.Exit(code=1)
    console.print(f"[green]ended[/] session {event.session_id}")


@session_app.command("current")
def session_current() -> None:
    s = session_mod.current()
    if s is None:
        console.print("[dim]no session open[/]")
        return
    console.print(
        f"[bold]{s.get('session_id')}[/]  name={s.get('name') or '-'}  "
        f"started={s.get('at', '')[:19]}"
    )


@session_app.command("list")
def session_list(n: int = typer.Option(20, "-n")) -> None:
    for s in session_mod.list_sessions()[:n]:
        dur = s.get("duration_sec")
        dur_str = f"{dur//60}m" if dur else "open"
        console.print(
            f"[bold]{s['session_id'][:8]}[/]  "
            f"{s.get('started_at', '?')[:19]}  dur={dur_str}  {s.get('name', '-')}"
        )


# ---------------------------------------------------------------------------
# Journal — unified feed.
# ---------------------------------------------------------------------------


@app.command("journal")
def journal_cmd(
    days: Optional[int] = typer.Option(None, "--days", "-d"),
    limit: int = typer.Option(50, "--limit", "-n"),
) -> None:
    """Print a reverse-chronological feed of everything memegine has logged."""
    entries = journal_mod.collect(days=days, limit=limit)
    # Plain print — avoids Rich's cp1252 issues on Windows consoles.
    print(journal_mod.as_text(entries))


# ---------------------------------------------------------------------------
# Next — "what now" dashboard.
# ---------------------------------------------------------------------------


@app.command("next")
def next_cmd() -> None:
    """One-screen dashboard: queue, last winner, top format, recommendations."""
    dash = next_action.compute()
    # Plain print — avoids Rich's cp1252 issues on Windows consoles.
    print(dash.as_text())


# ---------------------------------------------------------------------------
# X posting prepare (dry-run).
# ---------------------------------------------------------------------------

x_app = typer.Typer(help="Pre-flight for posting to X (no API needed).")
app.add_typer(x_app, name="x")


@x_app.command("prepare")
def x_prepare(
    post_bundle_id: str = typer.Argument(..., help="Post bundle id from `memegine post list`."),
) -> None:
    """Lint + format a post bundle for posting to X."""
    try:
        plan = x_post.prepare(post_bundle_id)
    except FileNotFoundError as exc:
        print(f"[red]{exc}[/]")
        raise typer.Exit(code=1)
    print(plan.checklist_text())
    print()
    print(plan.clipboard_block())


# ---------------------------------------------------------------------------
# Codex audit.
# ---------------------------------------------------------------------------


@codex_app.command("audit")
def codex_audit_cmd() -> None:
    """Detect duplicate bullets, contradiction hints, heavy sections."""
    audit = codex_audit.audit()
    print(audit.as_text())


if __name__ == "__main__":
    app()
