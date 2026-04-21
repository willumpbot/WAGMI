"""Kilroy compositor — authentic sticker-style Kilroy peek over any base.

Matches the operator's reference gallery:
  - Solid filled head (white/light fill with black outline)
  - Two cartoon HANDS on the sides of the head, fingers over the wall
  - Solid filled capsule/teardrop nose hanging past the wall
  - Two eye dots + tiny eyebrow marks above
  - Hand-lettered "[TEXT] was here" caption

Two render modes:
  "sticker"  — solid fill + outline (white body on any base). Looks
               like a sticker dropped into a photo. Default.
  "line_art" — black outline + white/transparent fill. Classic flat
               meme look for plain backgrounds.
  "chalk"    — legacy white-on-dark graffiti mode (keep for variety)
  "sharpie"  — legacy black-on-light graffiti mode

API stays backward-compatible:
    kilroy_onto(base_bytes, position=..., size_pct=..., text=...,
                mode="sticker")
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


# ---------- geometry (all ratios relative to overlay width) ----------

_HEAD_W_RATIO      = 0.70
_HEAD_H_RATIO      = 0.42   # bulbous-dome visible-height fraction of width
_EYE_Y_FRAC        = 0.55   # eye y within dome (0=top, 1=wall)
_EYE_RADIUS_RATIO  = 0.034
_EYE_DX_RATIO      = 0.10
_EYEBROW_LEN_RATIO = 0.08
_EYEBROW_DY_RATIO  = 0.08
_NOSE_WIDTH_RATIO  = 0.11
_NOSE_DROP_RATIO   = 0.48   # how far below wall nose droops
_HAND_SIZE_RATIO   = 0.20   # hand diameter as fraction of overlay width
_TEXT_H_RATIO      = 0.14
_TEXT_GAP_RATIO    = 0.04
_OUTLINE_W_RATIO   = 0.012  # outline stroke weight


@dataclass
class CompositeResult:
    image_bytes: bytes
    width: int
    height: int
    overlay_pct: float
    mode: str


def _jitter(val: float, amount: float) -> float:
    return val + random.uniform(-amount, amount)


def _load_hand_font(size: int) -> ImageFont.ImageFont:
    for name in [
        "Chalkduster", "Bradley Hand ITC", "Marker Felt",
        "Segoe Script", "Comic Sans MS", "Ink Free",
    ]:
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
    h = int(w * 1.3)   # room for head + wall + fingers-and-caption
    m = int(shorter * 0.04)
    if position == "bottom-right":
        x1, y1 = bw - m, bh - m;   x0, y0 = x1 - w, y1 - h
    elif position == "bottom-left":
        x0, y1 = m, bh - m;        x1, y0 = x0 + w, y1 - h
    elif position == "top-right":
        x1, y0 = bw - m, m;        x0, y1 = x1 - w, y0 + h
    elif position == "top-left":
        x0, y0 = m, m;             x1, y1 = x0 + w, y0 + h
    elif position == "center":
        x0, y0 = (bw - w) // 2, (bh - h) // 2
        x1, y1 = x0 + w, y0 + h
    else:
        x1, y1 = bw - m, bh - m;   x0, y0 = x1 - w, y1 - h
    return x0, y0, x1, y1


# ---------- drawing components ----------

def _draw_head(draw, cx, top_y, head_w, head_h, fill, outline, weight):
    """Bulbous dome head — filled + outlined.

    Real Kilroy head: the TOP half of an egg/ellipse that's slightly
    wider than tall (bulbous). Visible part ends at the wall line.
    """
    left = cx - head_w // 2
    right = cx + head_w // 2
    # Use a PIE slice to get filled top-half; ellipse bbox extends
    # below wall but we'll mask that with the wall line later.
    full_h = int(head_h * 2.2)
    bbox = [left, top_y, right, top_y + full_h]
    if fill is not None:
        draw.pieslice(bbox, start=180, end=360, fill=fill)
    if outline is not None:
        draw.arc(bbox, start=180, end=360, fill=outline, width=weight)


def _draw_eyes_and_brows(draw, cx, eye_y, eye_dx, eye_r, color, brow_dy, brow_len, weight):
    """Two dot eyes. Canonical Kilroy has no eyebrows (refs 3, 4)."""
    for sign in (-1, 1):
        ex = cx + sign * eye_dx
        draw.ellipse([ex - eye_r, eye_y - eye_r, ex + eye_r, eye_y + eye_r], fill=color)


def _draw_capsule_nose(draw, cx, wall_y, width, drop, fill, outline, weight):
    """Solid filled capsule/teardrop nose hanging past the wall.

    Top attaches to the head (between eyes, above wall).
    Body: a stretched vertical oval.
    """
    # Top of nose = just above wall (at head interior)
    top_inset = int(drop * 0.12)  # a bit of nose visible ABOVE the wall
    top_y = wall_y - top_inset
    bot_y = wall_y + drop
    left = cx - width // 2
    right = cx + width // 2
    # Filled ellipse
    if fill is not None:
        draw.ellipse([left, top_y, right, bot_y], fill=fill)
    if outline is not None:
        draw.ellipse([left, top_y, right, bot_y], outline=outline, width=weight)


def _draw_hand(draw, cx, cy, radius, fill, outline, weight, *, facing: str = "left"):
    """Draw 4 fingertips peeking up over the wall.

    cy is the wall line. We draw a hand body BELOW cy (hidden under
    the wall) and 4 finger-tip bumps ABOVE cy. Only the fingertips
    are visible on-screen since the hand body is later occluded by
    the wall line itself.
    """
    # Hand body below wall (this stays hidden, but we draw the top
    # curve JUST ABOVE the wall so when the wall line paints, only
    # the fingers above are preserved).
    hw = int(radius * 1.9)
    # 4 fingertip bumps above wall
    fn_count = 4
    fn_span = int(hw * 0.85)
    fn_w = max(6, fn_span // (fn_count + 1))
    fn_h = max(6, int(radius * 0.55))
    first_x = cx - fn_span // 2
    step = fn_span / fn_count
    for i in range(fn_count):
        fx = int(first_x + i * step + step / 2 + _jitter(0, weight * 0.5))
        fy_top = cy - fn_h
        fy_bot = cy + int(fn_h * 0.6)    # bottom extends under wall
        # Filled fingertip
        draw.ellipse(
            [fx - fn_w // 2, fy_top, fx + fn_w // 2, fy_bot],
            fill=fill, outline=outline, width=max(1, weight - 1),
        )


def _draw_wall(draw, cx, wall_y, span_half, outline, weight):
    """Horizontal wall edge. Gets drawn AFTER the character body so the
    lower portion of hands / head gets trimmed behind it. We also draw
    a small break under the nose so the nose droops through."""
    wall_left = cx - span_half
    wall_right = cx + span_half
    # (the actual 'under hands' section is already correct because
    # hands are drawn with palms below wall_y; the wall line just runs
    # through them visually).
    break_half = max(3, int(weight * 1.5))
    draw.line(
        [(wall_left, wall_y), (cx - break_half, wall_y)],
        fill=outline, width=weight,
    )
    draw.line(
        [(cx + break_half, wall_y), (wall_right, wall_y)],
        fill=outline, width=weight,
    )


def _draw_text(draw, text_box, text, color):
    """Hand-lettered caption that autofits within the box."""
    x0, y0, x1, y1 = text_box
    band_w = x1 - x0
    band_h = y1 - y0
    target_w = int(band_w * 0.86)

    def _measure(font, size):
        w = 0
        for ch in text:
            if ch == " ":
                w += int(size * 0.42)
                continue
            cbbox = draw.textbbox((0, 0), ch, font=font)
            w += (cbbox[2] - cbbox[0]) + max(1, int(size * 0.03))
        return w

    font_size = max(10, int(band_h * 0.95))
    font = _load_hand_font(font_size)
    text_w = _measure(font, font_size)
    attempts = 0
    while text_w > target_w and font_size > 6 and attempts < 30:
        font_size = max(6, int(font_size * 0.88))
        font = _load_hand_font(font_size)
        text_w = _measure(font, font_size)
        attempts += 1
    bbox = draw.textbbox((0, 0), text, font=font)
    text_h = bbox[3] - bbox[1]
    sx = x0 + (band_w - text_w) // 2
    sy = y0 + max(0, (band_h - text_h) // 2)
    cx_ = sx
    for ch in text:
        if ch == " ":
            cx_ += int(font_size * 0.42)
            continue
        jx = int(_jitter(0, font_size * 0.04))
        jy = int(_jitter(0, font_size * 0.06))
        draw.text((cx_ + jx, sy + jy), ch, fill=color, font=font)
        cbbox = draw.textbbox((0, 0), ch, font=font)
        cx_ += (cbbox[2] - cbbox[0]) + max(1, int(font_size * 0.03))


# ---------- mode resolution ----------

def _resolve_colors(mode: str, base_img: Image.Image, bbox) -> tuple:
    """Return (body_fill, outline_color, text_color) for the given mode."""
    if mode == "sticker":
        # White-ish fill + black outline — sticker look that pops on any base
        return ((245, 245, 242, 255), (12, 12, 12, 255), (12, 12, 12, 255))
    if mode == "line_art":
        return (None, (12, 12, 12, 255), (12, 12, 12, 255))
    if mode == "chalk":
        return (None, (255, 255, 255, 245), (255, 255, 255, 240))
    if mode == "sharpie":
        return (None, (10, 10, 10, 245), (10, 10, 10, 240))
    # auto: pick based on brightness
    b = _brightness_in(base_img, bbox)
    if b < 140:
        return ((245, 245, 242, 255), (12, 12, 12, 255), (245, 245, 242, 255))
    return ((245, 245, 242, 255), (12, 12, 12, 255), (12, 12, 12, 255))


# ---------- public API ----------

def kilroy_onto(
    base_bytes: bytes,
    *,
    position: str = "bottom-right",
    size_pct: float = 0.30,
    text: str = "KILROY WAS HERE",
    mode: str = "sticker",           # sticker / line_art / chalk / sharpie / auto
    seed: Optional[int] = None,
) -> CompositeResult:
    """Composite a canonical-style Kilroy onto the base image."""
    base = Image.open(io.BytesIO(base_bytes)).convert("RGBA")
    if seed is None:
        seed = random.randint(0, 999_999)
    random.seed(seed)

    x0, y0, x1, y1 = _compute_bounds(base.size, position=position, size_pct=size_pct)
    ow = x1 - x0
    oh = y1 - y0

    body_fill, outline, text_color = _resolve_colors(mode, base, (x0, y0, x1, y1))
    weight = max(2, int(ow * _OUTLINE_W_RATIO))

    # Layout calculations
    head_w = int(ow * _HEAD_W_RATIO)
    head_h = int(ow * _HEAD_H_RATIO)
    cx = ow // 2
    dome_top = int(oh * 0.04)
    wall_y = dome_top + head_h

    eye_y = dome_top + int(head_h * _EYE_Y_FRAC)
    eye_r = max(2, int(ow * _EYE_RADIUS_RATIO))
    eye_dx = int(ow * _EYE_DX_RATIO)
    brow_dy = int(ow * _EYEBROW_DY_RATIO)
    brow_len = int(ow * _EYEBROW_LEN_RATIO)

    nose_w = int(ow * _NOSE_WIDTH_RATIO)
    nose_drop = int(oh * _NOSE_DROP_RATIO)
    nose_bottom = wall_y + nose_drop

    hand_r = int(ow * _HAND_SIZE_RATIO) // 2
    hand_y = wall_y   # palm centered on the wall line
    # Hands flank the head on each side, slightly outside head_w
    hand_left_cx  = cx - int(head_w * 0.50) - hand_r // 2
    hand_right_cx = cx + int(head_w * 0.50) + hand_r // 2

    text_top = nose_bottom + int(oh * _TEXT_GAP_RATIO)
    text_bot = min(oh, text_top + int(oh * _TEXT_H_RATIO))

    # Transparent overlay canvas
    overlay = Image.new("RGBA", (ow, oh), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Draw order:
    #   1) hands (so head can paint over them at palm top)
    #   2) head (filled, with outline)
    #   3) eyes + brows (on head)
    #   4) nose (extends below wall, drawn over wall line at end)
    #   5) wall (crisp horizontal line; breaks under nose)
    #   6) text
    _draw_hand(draw, hand_left_cx, hand_y, hand_r,
               fill=body_fill, outline=outline, weight=weight, facing="right")
    _draw_hand(draw, hand_right_cx, hand_y, hand_r,
               fill=body_fill, outline=outline, weight=weight, facing="left")
    _draw_head(draw, cx, dome_top, head_w, head_h, body_fill, outline, weight)
    _draw_eyes_and_brows(
        draw, cx, eye_y, eye_dx, eye_r, outline,
        brow_dy, brow_len, weight,
    )
    # Nose: filled solid if we have a fill, otherwise outline-only
    nose_fill_color = outline  # canonical Kilroy nose is SOLID DARK
    _draw_capsule_nose(
        draw, cx, wall_y, nose_w, nose_drop,
        fill=nose_fill_color, outline=None, weight=weight,
    )
    _draw_wall(
        draw, cx, wall_y,
        span_half=int(head_w * 0.60) + hand_r,
        outline=outline, weight=weight,
    )
    _draw_text(draw, (0, text_top, ow, text_bot), text, text_color)

    # Subtle blur to break vector-perfection
    overlay = overlay.filter(ImageFilter.GaussianBlur(radius=0.35))

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
