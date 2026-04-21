"""Kilroy compositor — draw the canonical Kilroy over any base image.

AI-generated Kilroy always looks wrong. This module draws the real
character programmatically with PIL:

  - bald-head arc
  - two tiny eye dots
  - long drooping nose (the defining feature)
  - four knuckle fingers gripping the wall edge
  - "KILROY WAS HERE" hand-lettered block caps below

Output is a transparent PNG that composites cleanly onto any base
image. Color auto-adjusts: pure white chalk on dark surfaces, pure
black sharpie on light surfaces — detected per-placement-region.

Authentic irregular line weight (not vector-perfect) so it reads as
GI-drawn not AI-rendered.
"""
from __future__ import annotations

import io
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
except ImportError as exc:  # pragma: no cover
    raise ImportError("Pillow is required. Install via `pip install memegine`.") from exc


# ---- geometry constants ----

# All proportions relative to the Kilroy overlay's longer side.
# Head (bald dome) is the reference unit.
_HEAD_WIDTH_RATIO   = 0.55   # head spans this fraction of overlay width
_NOSE_DROP_RATIO    = 0.70   # how far nose hangs BELOW the wall edge
_FINGER_DROP_RATIO  = 0.10
_LINE_WEIGHT_RATIO  = 0.028  # stroke thickness as fraction of head width
_TEXT_BAND_RATIO    = 0.26   # height reserved for "KILROY WAS HERE"
_GUTTER_RATIO       = 0.05   # padding inside the overlay


@dataclass
class CompositeResult:
    image_bytes: bytes
    width: int
    height: int
    overlay_pct: float       # what % of the base the Kilroy overlay covered
    mode: str                # "chalk" or "sharpie"


# ---- helpers ----

def _jitter(x: float, amount: float) -> float:
    """Add irregular hand-drawn jitter — uniform ± amount."""
    return x + random.uniform(-amount, amount)


def _load_font(size: int) -> ImageFont.ImageFont:
    """Try hand-lettered-ish fonts in order; fall back to default."""
    candidates = [
        "Comic Sans MS",
        "Chalkduster",
        "Marker Felt",
        "Segoe Print",
        "ImpactLabel",
    ]
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.truetype("arial.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _draw_kilroy_shape(
    draw: ImageDraw.ImageDraw,
    *,
    bounds: tuple[int, int, int, int],
    color: tuple[int, int, int, int],
    line_weight: int,
    seed: int = 0,
) -> None:
    """Draw the Kilroy character (bald head + eyes + nose + fingers).

    `bounds` is the rect the head+nose+fingers occupy (excluding text).
    The wall edge is implicit at bounds.top + head_height.
    """
    random.seed(seed)
    x0, y0, x1, y1 = bounds
    w = x1 - x0
    h = y1 - y0
    cx = (x0 + x1) // 2

    head_w = int(w * _HEAD_WIDTH_RATIO)
    head_h = int(head_w * 0.62)                 # flatter dome than a circle
    head_left = cx - head_w // 2
    head_right = cx + head_w // 2
    wall_y = y0 + head_h                         # wall edge (top of fingers)

    # 1) Head (arc — just the top-half dome, open at the bottom where the wall is)
    head_bbox = [head_left, y0, head_right, y0 + head_h * 2]
    draw.arc(head_bbox, start=180, end=360, fill=color, width=line_weight)

    # 2) Eyes — two tiny filled dots, slightly below the dome apex
    eye_y = y0 + int(head_h * 0.78)
    eye_dx = int(head_w * 0.18)
    eye_r = max(2, int(head_w * 0.04))
    for sign in (-1, 1):
        ex = cx + sign * eye_dx
        draw.ellipse(
            [ex - eye_r, eye_y - eye_r, ex + eye_r, eye_y + eye_r],
            fill=color,
        )

    # 3) Nose — long drooping line that extends BELOW the wall
    nose_top = eye_y + int(head_h * 0.12)
    nose_bottom = wall_y + int(h * _NOSE_DROP_RATIO)
    nose_curve_x = int(_jitter(cx, head_w * 0.04))
    # slight irregular curve via two-segment polyline
    mid_y = (nose_top + nose_bottom) // 2
    draw.line(
        [(cx, nose_top), (nose_curve_x, mid_y), (cx + int(head_w * 0.04), nose_bottom)],
        fill=color, width=line_weight,
    )

    # 4) Four fingers gripping the wall — short vertical strokes below the wall edge
    finger_span = int(head_w * 0.68)
    finger_left = cx - finger_span // 2
    finger_drop = int(h * _FINGER_DROP_RATIO)
    for i in range(4):
        fx = finger_left + int((finger_span / 3) * i) + int(_jitter(0, line_weight))
        draw.line(
            [(fx, wall_y), (fx, wall_y + finger_drop)],
            fill=color, width=line_weight,
        )
    # Thin curve under the fingers suggesting the wall/hand silhouette
    draw.line(
        [
            (finger_left - line_weight, wall_y + finger_drop),
            (finger_left + finger_span + line_weight, wall_y + finger_drop),
        ],
        fill=color, width=max(1, line_weight - 1),
    )


def _draw_text_band(
    draw: ImageDraw.ImageDraw,
    *,
    text: str,
    text_box: tuple[int, int, int, int],
    color: tuple[int, int, int, int],
    seed: int = 0,
) -> None:
    """Render 'KILROY WAS HERE' in a hand-lettered block-caps style."""
    random.seed(seed + 1)
    x0, y0, x1, y1 = text_box
    band_h = y1 - y0
    font_size = max(10, int(band_h * 0.75))
    font = _load_font(font_size)

    # Measure text
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    start_x = x0 + (x1 - x0 - text_w) // 2
    start_y = y0 + (band_h - text_h) // 2

    # Draw each letter with slight position jitter so it looks hand-done
    cur_x = start_x
    for ch in text:
        if ch == " ":
            cur_x += int(font_size * 0.45)
            continue
        jx = int(_jitter(0, font_size * 0.05))
        jy = int(_jitter(0, font_size * 0.08))
        draw.text((cur_x + jx, start_y + jy), ch, fill=color, font=font)
        cbbox = draw.textbbox((0, 0), ch, font=font)
        cur_x += (cbbox[2] - cbbox[0]) + max(1, int(font_size * 0.04))


# ---- corner analysis for chalk-vs-sharpie choice ----

def _sample_region_brightness(base: Image.Image, box: tuple[int, int, int, int]) -> float:
    """Mean brightness (0-255) of the base image in the given region."""
    x0, y0, x1, y1 = box
    x0 = max(0, x0); y0 = max(0, y0)
    x1 = min(base.width, x1); y1 = min(base.height, y1)
    if x0 >= x1 or y0 >= y1:
        return 128
    region = base.crop((x0, y0, x1, y1)).convert("L")
    # PIL's getextrema / sum can be slow — resize first to speed up
    small = region.resize((min(64, x1 - x0), min(64, y1 - y0)))
    pixels = list(small.getdata())
    return sum(pixels) / len(pixels) if pixels else 128


# ---- placement calculator ----

def _compute_bounds(
    base_size: tuple[int, int],
    *,
    position: str,
    size_pct: float,
) -> tuple[int, int, int, int]:
    """Return (x0, y0, x1, y1) rect where Kilroy overlay should be placed."""
    bw, bh = base_size
    shorter = min(bw, bh)
    overlay_w = int(shorter * size_pct)
    overlay_h = int(overlay_w * 1.25)    # taller than wide (includes text band)
    margin = int(shorter * 0.04)
    if position == "bottom-right":
        x1 = bw - margin; y1 = bh - margin
        x0 = x1 - overlay_w; y0 = y1 - overlay_h
    elif position == "bottom-left":
        x0 = margin; y1 = bh - margin
        x1 = x0 + overlay_w; y0 = y1 - overlay_h
    elif position == "top-right":
        x1 = bw - margin; y0 = margin
        x0 = x1 - overlay_w; y1 = y0 + overlay_h
    elif position == "top-left":
        x0 = margin; y0 = margin
        x1 = x0 + overlay_w; y1 = y0 + overlay_h
    elif position == "center":
        x0 = (bw - overlay_w) // 2
        y0 = (bh - overlay_h) // 2
        x1 = x0 + overlay_w; y1 = y0 + overlay_h
    else:
        x1 = bw - margin; y1 = bh - margin
        x0 = x1 - overlay_w; y0 = y1 - overlay_h
    return x0, y0, x1, y1


# ---- public API ----

def kilroy_onto(
    base_bytes: bytes,
    *,
    position: str = "bottom-right",
    size_pct: float = 0.22,
    text: str = "KILROY WAS HERE",
    seed: Optional[int] = None,
    force_mode: Optional[str] = None,  # "chalk" / "sharpie"
) -> CompositeResult:
    """Composite a drawn Kilroy onto a base image.

    base_bytes: JPEG/PNG/WebP bytes.
    position: bottom-right / bottom-left / top-left / top-right / center
    size_pct: overlay width as fraction of shorter base dimension (0.15-0.30 typical)
    force_mode: override auto chalk/sharpie detection ("chalk" = white,
                "sharpie" = black)

    Returns CompositeResult with PNG bytes of the final image.
    """
    base = Image.open(io.BytesIO(base_bytes)).convert("RGBA")

    if seed is None:
        seed = random.randint(0, 999_999)

    x0, y0, x1, y1 = _compute_bounds(base.size, position=position, size_pct=size_pct)
    overlay_w = x1 - x0
    overlay_h = y1 - y0

    # Decide chalk vs sharpie based on brightness of the placement region.
    if force_mode:
        mode = force_mode
    else:
        brightness = _sample_region_brightness(base, (x0, y0, x1, y1))
        mode = "chalk" if brightness < 140 else "sharpie"

    color = (255, 255, 255, 240) if mode == "chalk" else (12, 12, 12, 240)
    line_weight = max(2, int(overlay_w * _LINE_WEIGHT_RATIO))

    # Build transparent overlay
    overlay = Image.new("RGBA", (overlay_w, overlay_h), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)

    char_bottom = int(overlay_h * (1 - _TEXT_BAND_RATIO))
    _draw_kilroy_shape(
        odraw,
        bounds=(0, 0, overlay_w, char_bottom),
        color=color, line_weight=line_weight, seed=seed,
    )
    _draw_text_band(
        odraw,
        text=text,
        text_box=(0, char_bottom, overlay_w, overlay_h),
        color=color, seed=seed,
    )

    # Tiny blur so the chalk/sharpie doesn't look vector-perfect
    overlay = overlay.filter(ImageFilter.GaussianBlur(radius=0.6))

    # Composite onto the base
    composite = base.copy()
    composite.paste(overlay, (x0, y0), overlay)

    # Export PNG
    out = io.BytesIO()
    composite.convert("RGB").save(out, format="PNG", optimize=True)

    area_pct = (overlay_w * overlay_h) / (base.width * base.height) * 100.0
    return CompositeResult(
        image_bytes=out.getvalue(),
        width=base.width,
        height=base.height,
        overlay_pct=round(area_pct, 1),
        mode=mode,
    )


def save_kilroy_composite(
    base_path: str | Path,
    output_path: str | Path,
    **kwargs,
) -> CompositeResult:
    """Convenience — read a file, composite, write result."""
    base_path = Path(base_path)
    output_path = Path(output_path)
    result = kilroy_onto(base_path.read_bytes(), **kwargs)
    output_path.write_bytes(result.image_bytes)
    return result
