"""Kilroy compositor — authentic hand-drawn Kilroy over any base image.

This is NOT AI generation. It draws the canonical WWII-era Kilroy
("Kilroy was here") character with PIL using composed primitives that
match the real meme:

  - Rounded dome head (no hair, no shoulders)
  - Two EYES drawn ABOVE the wall line, centered in the head
  - LONG PENDULOUS NOSE — starts below the eyes, curves down past
    the wall edge, forms the defining drooping droop
  - Horizontal WALL EDGE line (visible, not implied)
  - FOUR FINGERS gripping the wall — curved fingertip arcs, not
    straight sticks
  - "KILROY WAS HERE" block caps hand-lettered below the whole thing

Every stroke has slight jitter so it reads GI-drawn not vector-clean.

Modes:
  chalk    = white on dark backgrounds
  sharpie  = black on light backgrounds
  (auto-detected from the placement region's brightness)
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
    raise ImportError("Pillow required. `pip install pillow`") from exc


# ---------- geometry ratios (relative to overlay short side) ----------

_HEAD_W_RATIO      = 0.72   # head width (a little bigger)
_HEAD_H_RATIO      = 0.40   # taller dome so eyes sit better
_EYE_Y_OFFSET      = 0.60   # eye Y within dome — MID-DOME, not near wall
_EYE_RADIUS_RATIO  = 0.045  # BIG eyes (was 0.03, too small)
_EYE_DX_RATIO      = 0.14   # a bit wider-spaced
_NOSE_LENGTH_RATIO = 0.50   # MUCH longer droopy nose
_NOSE_WEIGHT_MULT  = 1.4    # nose drawn THICKER than other lines
_WALL_EXTEND_RATIO = 1.18
_FINGER_DROP_RATIO = 0.13
_LINE_WEIGHT_RATIO = 0.034  # thicker confident strokes (was 0.022)
_TEXT_GAP_RATIO    = 0.06
_TEXT_HEIGHT_RATIO = 0.13


@dataclass
class CompositeResult:
    image_bytes: bytes
    width: int
    height: int
    overlay_pct: float
    mode: str               # "chalk" or "sharpie"


def _jitter(val: float, amount: float) -> float:
    return val + random.uniform(-amount, amount)


def _load_hand_font(size: int) -> ImageFont.ImageFont:
    """Prefer informal hand-lettered fonts; fall back to system default."""
    candidates = [
        "Chalkduster",           # macOS
        "Bradley Hand ITC",      # Windows
        "Marker Felt",           # macOS
        "Segoe Script",          # Windows
        "Comic Sans MS",         # widespread
        "Ink Free",              # Windows 10+
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


def _brightness_in(base: Image.Image, box) -> float:
    x0, y0, x1, y1 = box
    x0 = max(0, x0); y0 = max(0, y0)
    x1 = min(base.width, x1); y1 = min(base.height, y1)
    if x0 >= x1 or y0 >= y1:
        return 128
    region = base.crop((x0, y0, x1, y1)).convert("L")
    w = min(64, x1 - x0) or 1
    h = min(64, y1 - y0) or 1
    small = region.resize((w, h))
    pixels = list(small.getdata())
    return sum(pixels) / len(pixels) if pixels else 128


def _compute_bounds(base_size, *, position: str, size_pct: float):
    bw, bh = base_size
    shorter = min(bw, bh)
    w = int(shorter * size_pct)
    # Kilroy overlay is a bit taller than wide (character + wall + fingers + text)
    h = int(w * 1.35)
    margin = int(shorter * 0.04)
    if position == "bottom-right":
        x1, y1 = bw - margin, bh - margin
        x0, y0 = x1 - w, y1 - h
    elif position == "bottom-left":
        x0, y1 = margin, bh - margin
        x1, y0 = x0 + w, y1 - h
    elif position == "top-right":
        x1, y0 = bw - margin, margin
        x0, y1 = x1 - w, y0 + h
    elif position == "top-left":
        x0, y0 = margin, margin
        x1, y1 = x0 + w, y0 + h
    elif position == "center":
        x0, y0 = (bw - w) // 2, (bh - h) // 2
        x1, y1 = x0 + w, y0 + h
    else:
        x1, y1 = bw - margin, bh - margin
        x0, y0 = x1 - w, y1 - h
    return x0, y0, x1, y1


# ---------- core drawing ----------

def _draw_dome(draw, cx, top_y, head_w, head_h, color, weight):
    """Draw the BULBOUS Kilroy head.

    Canon: "bulbous head" — fuller, rounder than a flat dome. Draw as
    the top portion of a wider, rounder ellipse.
    """
    # Make the ellipse WIDER than tall — the visible arc is more curved
    left = cx - head_w // 2
    right = cx + head_w // 2
    # Total ellipse height = head_h * 2.2 (so visible half is more bulbous)
    full_h = int(head_h * 2.2)
    ellipse_bbox = [left, top_y, right, top_y + full_h]
    # Arc 180→360 draws the TOP half
    draw.arc(ellipse_bbox, start=180, end=360, fill=color, width=weight)
    # Double-stroke for drawn feel
    draw.arc(
        [left + weight, top_y + int(weight * 0.6),
         right - weight, top_y + full_h - int(weight * 0.6)],
        start=190, end=350, fill=color, width=max(1, weight - 1),
    )


def _draw_eyes(draw, cx, eye_y, dx, r, color):
    """Two simple filled eye dots inside the dome."""
    for sign in (-1, 1):
        ex = cx + sign * dx
        draw.ellipse(
            [ex - r, eye_y - r, ex + r, eye_y + r],
            fill=color,
        )


def _draw_nose(draw, cx, nose_top, wall_y, nose_bottom, color, weight):
    """Draw the ICONIC LONG pendulous droopy nose.

    This is the defining Kilroy feature — a bulbous, elongated nose
    that hangs well below the wall edge. Drawn thicker than other
    lines to dominate the character.
    """
    nose_weight = max(weight + 1, int(weight * _NOSE_WEIGHT_MULT))

    # Short segment inside the dome (between eyes)
    draw.line([(cx, nose_top), (cx, wall_y)], fill=color, width=nose_weight)

    # Main droop: quadratic curve, gentle side sway, ending in a bulbous tip
    segments = 24
    drop = nose_bottom - wall_y
    sway = max(3, int(drop * 0.14))
    pts = [(cx, wall_y)]
    for i in range(1, segments + 1):
        t = i / segments
        # y: slight ease-in so the nose elongates
        y = wall_y + int(drop * (t ** 1.05))
        # x: single S-curve sway, ending slightly right of center
        x = cx + int(math.sin(t * math.pi * 1.0) * sway)
        pts.append((x, y))
    for i in range(len(pts) - 1):
        draw.line([pts[i], pts[i + 1]], fill=color, width=nose_weight)

    # Bulbous tip — small circle at the nose end so it reads as droopy
    tip_x, tip_y = pts[-1]
    tip_r = max(4, int(weight * 2.0))
    draw.ellipse(
        [tip_x - tip_r, tip_y - tip_r, tip_x + tip_r, tip_y + tip_r],
        fill=color,
    )


def _draw_wall_and_fingers(draw, cx, wall_y, head_w, finger_drop, color, weight):
    """Draw the horizontal wall edge + 4 curved fingertips gripping over it.

    The wall extends slightly beyond the head on both sides (the hands
    reach out). Fingers are drawn as small upward-curving arcs sitting
    ON the wall line — they look like knuckles peeking over, not sticks.
    """
    wall_half = int(head_w * _WALL_EXTEND_RATIO * 0.5)
    wall_left = cx - wall_half
    wall_right = cx + wall_half

    # The wall edge itself — slight break in the middle under the nose
    # so the nose droops through a tiny gap.
    nose_gap = max(2, weight)
    draw.line(
        [(wall_left, wall_y), (cx - nose_gap, wall_y)],
        fill=color, width=weight,
    )
    draw.line(
        [(cx + nose_gap, wall_y), (wall_right, wall_y)],
        fill=color, width=weight,
    )

    # FINGERS — 4 separate knuckle bumps poking UP over the wall.
    # Crucial: the fingertips ONLY peek above the wall by a small
    # amount (~30-40% of the finger height). The bulk of each finger
    # sits BELOW the wall line, hidden by the wall. Imagine 4 fingertips
    # barely showing above a windowsill.
    finger_count = 4
    finger_span = int(head_w * 0.82)
    first_x = cx - finger_span // 2
    step = finger_span / finger_count
    fw = max(5, int(step * 0.70))
    # Poke = how much each finger shows ABOVE the wall (small!)
    poke_h = max(3, int(finger_drop * 0.45))
    # Below-wall length (hidden under wall) — taller, for sausage effect
    full_h = max(8, int(finger_drop * 1.2))
    for i in range(finger_count):
        fx = int(first_x + i * step + step / 2 + _jitter(0, weight * 0.4))
        # Finger bounding box: from (wall_y - poke_h) to (wall_y - poke_h + full_h)
        # So the TOP of the bounding box is only poke_h above the wall,
        # and only the first ~30% of an ellipse shows above the wall.
        bump_top = wall_y - poke_h
        bump_bot = bump_top + full_h
        # Draw as top-arc of ellipse, which will be a small bump curving up
        # and outlined
        draw.arc(
            [fx - fw // 2, bump_top, fx + fw // 2, bump_bot],
            start=180, end=360, fill=color, width=weight,
        )
        # Small fill JUST for the visible poke above the wall
        draw.pieslice(
            [fx - fw // 2 + weight, bump_top + weight // 2,
             fx + fw // 2 - weight, wall_y + weight],
            start=180, end=360, fill=color,
        )


def _draw_text(draw, text_box, text, color):
    """Hand-lettered 'KILROY WAS HERE' with per-character jitter.

    Auto-shrinks font size so text always fits inside the overlay
    width — prevents the "ROY WAS HE" cutoff bug on tight overlays.
    """
    x0, y0, x1, y1 = text_box
    band_w = x1 - x0
    band_h = y1 - y0
    # Target: text spans ~88% of band width (small padding)
    target_w = int(band_w * 0.92)

    # Binary-search-ish shrink: start big, shrink until it fits
    font_size = max(10, int(band_h * 0.95))
    font = _load_hand_font(font_size)
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    # Shrink if too wide
    attempts = 0
    while text_w > target_w and font_size > 10 and attempts < 20:
        font_size = int(font_size * 0.9)
        font = _load_hand_font(font_size)
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        attempts += 1

    text_h = bbox[3] - bbox[1]
    start_x = x0 + (band_w - text_w) // 2
    start_y = y0 + max(0, (band_h - text_h) // 2)

    cur_x = start_x
    for ch in text:
        if ch == " ":
            cur_x += int(font_size * 0.42)
            continue
        jx = int(_jitter(0, font_size * 0.04))
        jy = int(_jitter(0, font_size * 0.06))
        draw.text((cur_x + jx, start_y + jy), ch, fill=color, font=font)
        cbbox = draw.textbbox((0, 0), ch, font=font)
        cur_x += (cbbox[2] - cbbox[0]) + max(1, int(font_size * 0.03))


# ---------- public API ----------

def kilroy_onto(
    base_bytes: bytes,
    *,
    position: str = "bottom-right",
    size_pct: float = 0.25,
    text: str = "KILROY WAS HERE",
    seed: Optional[int] = None,
    force_mode: Optional[str] = None,
) -> CompositeResult:
    """Composite an authentic Kilroy peek onto the base image.

    Returns CompositeResult with PNG bytes of the final composite.
    """
    base = Image.open(io.BytesIO(base_bytes)).convert("RGBA")
    if seed is None:
        seed = random.randint(0, 999_999)
    random.seed(seed)

    x0, y0, x1, y1 = _compute_bounds(base.size, position=position, size_pct=size_pct)
    ow = x1 - x0
    oh = y1 - y0

    # Chalk vs sharpie
    if force_mode:
        mode = force_mode
    else:
        mode = "chalk" if _brightness_in(base, (x0, y0, x1, y1)) < 140 else "sharpie"
    color = (255, 255, 255, 245) if mode == "chalk" else (10, 10, 10, 245)
    weight = max(2, int(ow * _LINE_WEIGHT_RATIO))

    # Transparent overlay canvas
    overlay = Image.new("RGBA", (ow, oh), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Vertical layout:
    #   dome: top .. dome_bottom
    #   eyes: within dome
    #   wall: at dome_bottom
    #   fingers: just below wall
    #   nose: dome interior + drooping below wall
    #   text: below fingers
    head_w = int(ow * _HEAD_W_RATIO)
    head_h = int(ow * _HEAD_H_RATIO)     # visible dome height
    cx = ow // 2
    dome_top = int(oh * 0.05)
    wall_y = dome_top + head_h

    eye_y = dome_top + int(head_h * _EYE_Y_OFFSET)
    eye_r = max(2, int(ow * _EYE_RADIUS_RATIO))
    eye_dx = int(ow * _EYE_DX_RATIO)

    nose_top = eye_y + int(head_h * 0.10)
    nose_drop = int(oh * _NOSE_LENGTH_RATIO)
    nose_bottom = wall_y + nose_drop

    finger_drop = int(oh * _FINGER_DROP_RATIO)

    text_top = nose_bottom + int(oh * _TEXT_GAP_RATIO)
    text_bottom = min(oh, text_top + int(oh * _TEXT_HEIGHT_RATIO))

    # Draw in order: dome (back) → eyes → nose → wall+fingers → text
    _draw_dome(draw, cx, dome_top, head_w, head_h, color, weight)
    _draw_eyes(draw, cx, eye_y, eye_dx, eye_r, color)
    _draw_nose(draw, cx, nose_top, wall_y, nose_bottom, color, weight)
    _draw_wall_and_fingers(draw, cx, wall_y, head_w, finger_drop, color, weight)
    _draw_text(draw, (0, text_top, ow, text_bottom), text, color)

    # Tiny blur to break vector-perfection
    overlay = overlay.filter(ImageFilter.GaussianBlur(radius=0.5))

    composite = base.copy()
    composite.paste(overlay, (x0, y0), overlay)
    out = io.BytesIO()
    composite.convert("RGB").save(out, format="PNG", optimize=True)

    return CompositeResult(
        image_bytes=out.getvalue(),
        width=base.width,
        height=base.height,
        overlay_pct=round(ow * oh / (base.width * base.height) * 100.0, 1),
        mode=mode,
    )


def save_kilroy_composite(base_path, output_path, **kwargs) -> CompositeResult:
    base_path = Path(base_path)
    output_path = Path(output_path)
    result = kilroy_onto(base_path.read_bytes(), **kwargs)
    output_path.write_bytes(result.image_bytes)
    return result
