"""Contact sheet — pack winner thumbnails into one grid image.

A single image worth scanning on a phone. Useful for end-of-week
visual review: 20 winners laid out in a 4×5 grid with IDs annotated,
open once, scroll once, done.

Uses PIL (already a dep).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import reference_lib, thumbnails
from .config import settings


@dataclass
class SheetResult:
    destination: str
    n_refs: int
    cols: int
    rows: int


def generate(
    *,
    destination: Path | None = None,
    cols: int = 4,
    cell_size: int = 256,
    cell_padding: int = 12,
    annotate: bool = True,
    winners_only: bool = True,
    max_refs: int = 40,
) -> SheetResult:
    """Build a grid image of ref thumbnails.

    Thumbnails must exist (call `thumbnails.generate_all()` first or
    this will auto-call it).
    """
    from PIL import Image, ImageDraw, ImageFont

    # Ensure thumbs exist.
    thumbnails.generate_all()

    refs = reference_lib._load_index()
    if winners_only:
        refs = [r for r in refs if "winner" in r.get("tags", [])]
    refs.sort(key=lambda r: r.get("added_at", ""), reverse=True)
    refs = refs[:max_refs]

    n = len(refs)
    if n == 0:
        raise ValueError("no refs to place on contact sheet")

    rows = (n + cols - 1) // cols
    label_space = 24 if annotate else 0
    cell_h = cell_size + label_space
    sheet_w = cols * (cell_size + cell_padding) + cell_padding
    sheet_h = rows * (cell_h + cell_padding) + cell_padding

    sheet = Image.new("RGB", (sheet_w, sheet_h), color=(20, 20, 20))
    draw = ImageDraw.Draw(sheet)
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont
    try:
        font = ImageFont.truetype("arial.ttf", 14)
    except OSError:
        font = ImageFont.load_default()

    for i, r in enumerate(refs):
        row = i // cols
        col = i % cols
        x = cell_padding + col * (cell_size + cell_padding)
        y = cell_padding + row * (cell_h + cell_padding)

        thumb_path = thumbnails.thumb_path_for(r["id"])
        if thumb_path is None or not thumb_path.exists():
            # Draw a placeholder rect.
            draw.rectangle([x, y, x + cell_size, y + cell_size], fill=(80, 0, 0))
            draw.text((x + 10, y + 10), "no thumb", fill=(255, 255, 255), font=font)
        else:
            with Image.open(thumb_path) as img:
                img = img.convert("RGB")
                # Center-crop to square then resize to cell_size.
                w, h = img.size
                m = min(w, h)
                left = (w - m) // 2
                top = (h - m) // 2
                img = img.crop((left, top, left + m, top + m))
                img = img.resize((cell_size, cell_size), Image.LANCZOS)
                sheet.paste(img, (x, y))

        if annotate:
            label = r["id"][:12]
            date = (r.get("added_at", "") or "")[:10]
            text = f"{label} · {date}"
            draw.text((x + 4, y + cell_size + 4), text,
                      fill=(220, 220, 220), font=font)

    if destination is None:
        import datetime as dt
        stamp = dt.date.today().isoformat()
        destination = settings.data_dir / "lookbooks" / f"contact-sheet-{stamp}.jpg"
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(destination, "JPEG", quality=88, optimize=True)

    return SheetResult(
        destination=str(destination), n_refs=n, cols=cols, rows=rows,
    )
