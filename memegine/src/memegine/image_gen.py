"""Image generation — call AI image APIs directly, no manual paste.

Turns the end-to-end reply-guy loop into:
    tweet URL → tight Grok-ready prompt → IMAGE RENDERED via API →
    sent to operator's TG as a photo → operator saves + replies.

Supports multiple backends selected via env:
    MEMEGINE_FAL_KEY       → fal.ai Flux Schnell (cheapest, ~$0.003/img)
    MEMEGINE_XAI_API_KEY   → xAI Grok-2-image ($0.07/img)
    MEMEGINE_OPENAI_KEY    → OpenAI DALL-E 3 ($0.04/img)

The watcher / bot / CLI all just call `generate(prompt)` → get back
a list of image bytes. Backend selection is transparent.
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Optional


class ImageGenError(RuntimeError):
    pass


@dataclass
class GeneratedImage:
    bytes: bytes
    mime_type: str = "image/png"
    model: str = ""
    cost_usd: float = 0.0
    url: str = ""


def _backend() -> str:
    """Auto-select which backend to use based on which env key is set."""
    if os.environ.get("MEMEGINE_FAL_KEY", "").strip():
        return "fal"
    if os.environ.get("MEMEGINE_XAI_API_KEY", "").strip():
        return "xai"
    if os.environ.get("MEMEGINE_OPENAI_KEY", "").strip():
        return "openai"
    return ""


def available_backends() -> list[str]:
    """Which backends are configured right now?"""
    found = []
    for env_var, name in [
        ("MEMEGINE_FAL_KEY", "fal"),
        ("MEMEGINE_XAI_API_KEY", "xai"),
        ("MEMEGINE_OPENAI_KEY", "openai"),
    ]:
        if os.environ.get(env_var, "").strip():
            found.append(name)
    return found


# ---------- fal.ai (cheapest) ----------

def _fal_generate(
    prompt: str,
    *,
    num_images: int = 1,
    image_size: str = "square_hd",  # 1024x1024
) -> list[GeneratedImage]:
    """Call fal.ai Flux Schnell. Returns PNG bytes.

    API: https://fal.run/fal-ai/flux/schnell
    Auth: `Authorization: Key <api_key>`
    """
    key = os.environ.get("MEMEGINE_FAL_KEY", "").strip()
    if not key:
        raise ImageGenError("MEMEGINE_FAL_KEY not set")

    body = json.dumps({
        "prompt": prompt,
        "num_images": num_images,
        "image_size": image_size,
        "num_inference_steps": 4,     # schnell is distilled — 4 steps is enough
        "enable_safety_checker": False,
    }).encode()

    req = urllib.request.Request(
        "https://fal.run/fal-ai/flux/schnell",
        data=body,
        headers={
            "Authorization": f"Key {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise ImageGenError(f"fal.ai HTTP {exc.code}: {body}")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ImageGenError(f"fal.ai request failed: {exc}")

    images_meta = payload.get("images") or []
    if not images_meta:
        raise ImageGenError(f"fal.ai returned no images: {payload!r}"[:300])

    out: list[GeneratedImage] = []
    for img in images_meta:
        url = img.get("url", "")
        if not url:
            continue
        # URL is https → download the bytes.
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                data = r.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ImageGenError(f"fal.ai image fetch failed: {exc}")
        out.append(GeneratedImage(
            bytes=data,
            mime_type=img.get("content_type") or "image/png",
            model="fal-ai/flux/schnell",
            cost_usd=0.003,
            url=url,
        ))
    return out


# ---------- xAI Grok-2-image ----------

def _xai_generate(prompt: str, *, num_images: int = 1) -> list[GeneratedImage]:
    """Call xAI Grok-2-image via their OpenAI-compatible endpoint.

    API: https://api.x.ai/v1/images/generations
    Auth: `Authorization: Bearer <api_key>`
    """
    key = os.environ.get("MEMEGINE_XAI_API_KEY", "").strip()
    if not key:
        raise ImageGenError("MEMEGINE_XAI_API_KEY not set")

    body = json.dumps({
        "model": "grok-2-image",
        "prompt": prompt,
        "n": min(max(num_images, 1), 10),
    }).encode()

    req = urllib.request.Request(
        "https://api.x.ai/v1/images/generations",
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise ImageGenError(f"xAI HTTP {exc.code}: {body}")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ImageGenError(f"xAI request failed: {exc}")

    out: list[GeneratedImage] = []
    for item in payload.get("data", []):
        if "b64_json" in item:
            data = base64.b64decode(item["b64_json"])
            out.append(GeneratedImage(
                bytes=data, mime_type="image/png",
                model="grok-2-image", cost_usd=0.07,
            ))
        elif "url" in item:
            with urllib.request.urlopen(item["url"], timeout=60) as r:
                out.append(GeneratedImage(
                    bytes=r.read(), mime_type="image/png",
                    model="grok-2-image", cost_usd=0.07, url=item["url"],
                ))
    if not out:
        raise ImageGenError(f"xAI returned no images: {payload!r}"[:300])
    return out


# ---------- OpenAI DALL-E 3 ----------

def _openai_generate(prompt: str, *, num_images: int = 1) -> list[GeneratedImage]:
    key = os.environ.get("MEMEGINE_OPENAI_KEY", "").strip()
    if not key:
        raise ImageGenError("MEMEGINE_OPENAI_KEY not set")

    body = json.dumps({
        "model": "dall-e-3",
        "prompt": prompt,
        "n": 1,  # dall-e-3 only accepts n=1
        "size": "1024x1024",
        "response_format": "b64_json",
    }).encode()

    req = urllib.request.Request(
        "https://api.openai.com/v1/images/generations",
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise ImageGenError(f"OpenAI HTTP {exc.code}: {body}")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ImageGenError(f"OpenAI request failed: {exc}")

    out: list[GeneratedImage] = []
    for item in payload.get("data", []):
        if "b64_json" in item:
            out.append(GeneratedImage(
                bytes=base64.b64decode(item["b64_json"]),
                mime_type="image/png",
                model="dall-e-3", cost_usd=0.04,
            ))
    return out


# ---------- public dispatch ----------

def generate(
    prompt: str,
    *,
    num_images: int = 1,
    backend: Optional[str] = None,
) -> list[GeneratedImage]:
    """Generate N images from prompt via whichever backend is configured.

    If `backend` is None, auto-selects in cost order: fal → xai → openai.
    Raises ImageGenError if no backend is configured or the API call fails.
    """
    target = backend or _backend()
    if not target:
        raise ImageGenError(
            "No image backend configured. Set MEMEGINE_FAL_KEY (cheapest), "
            "MEMEGINE_XAI_API_KEY, or MEMEGINE_OPENAI_KEY in .env."
        )
    if target == "fal":
        return _fal_generate(prompt, num_images=num_images)
    if target == "xai":
        return _xai_generate(prompt, num_images=num_images)
    if target == "openai":
        return _openai_generate(prompt, num_images=num_images)
    raise ImageGenError(f"unknown backend: {target}")


def probe() -> dict:
    """Quick health-check — tries to generate one tiny image via the active backend."""
    target = _backend()
    if not target:
        return {"ok": False, "msg": "no backend key set"}
    try:
        start = time.time()
        imgs = generate(
            "A single white chalk hand-drawn peek figure on a dark brick wall, "
            "pure white chalk, one continuous line, centered, 1:1 square, "
            "no text, no background complexity.",
            num_images=1,
        )
        elapsed = time.time() - start
        if imgs:
            return {
                "ok": True,
                "msg": f"{target} OK — {len(imgs)} image in {elapsed:.1f}s "
                f"({len(imgs[0].bytes):,} bytes)",
                "model": imgs[0].model,
                "cost_usd": imgs[0].cost_usd,
            }
        return {"ok": False, "msg": f"{target} returned no images"}
    except ImageGenError as exc:
        return {"ok": False, "msg": str(exc)}
