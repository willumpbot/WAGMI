"""Spongify via spongmonkeys.fun web interface — optimized for batch processing.

Automate the actual spongmonkeys.fun generator:
  1. Navigate to spongmonkeys.fun
  2. Upload profile picture
  3. Wait for generation (monitor page for actual output image)
  4. Download result
  5. Return bytes

Fast enough to batch 50+ images overnight. Free — no API costs.
"""
from __future__ import annotations

import asyncio
import base64
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    from playwright.async_api import async_playwright
except ImportError:
    async_playwright = None


@dataclass
class SpongifyResult:
    image_bytes: bytes
    error: Optional[str] = None


async def spongify_via_web(
    image_path: Path,
    *,
    headless: bool = True,
    timeout_sec: float = 120,
    verbose: bool = False,
) -> SpongifyResult:
    """Upload image to spongmonkeys.fun, generate, download result.

    Args:
      image_path: Path to input image (JPG/PNG)
      headless: Run browser headless (no UI)
      timeout_sec: Max wait for generation (default 2 min)
      verbose: Print debug messages

    Returns:
      SpongifyResult with image_bytes or error
    """
    if not async_playwright:
        return SpongifyResult(
            image_bytes=b"",
            error="Playwright not installed. Run: pip install -e .[watch]"
        )

    if not image_path.exists():
        return SpongifyResult(image_bytes=b"", error=f"File not found: {image_path}")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)
            page = await browser.new_page()

            if verbose:
                print("[spongify] Navigating to spongmonkeys.fun...")

            # Load page
            await page.goto("https://spongmonkeys.fun", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)  # Let JS load

            if verbose:
                print("[spongify] Finding file input...")

            # Get all file inputs (there are 2 on the page)
            file_inputs = await page.locator("input[type='file']").all()
            if not file_inputs:
                await browser.close()
                return SpongifyResult(image_bytes=b"", error="File input not found")

            file_input = file_inputs[0]  # First is the main upload

            if verbose:
                print(f"[spongify] Uploading {image_path.name}...")

            # Upload file
            await file_input.set_input_files(str(image_path))
            await asyncio.sleep(2)

            # Call the Spongify generation function directly via JavaScript
            try:
                if verbose:
                    print("[spongify] Triggering generation via JavaScript...")
                # The button has onclick="doInspire()" — call it directly
                await page.evaluate("doInspire()")
                await asyncio.sleep(3)  # Wait for generation to complete
                if verbose:
                    print("[spongify] Generation triggered")
            except Exception as e:
                if verbose:
                    print(f"[spongify] JS call failed: {e}, will retry with button click")
                try:
                    # Fallback: try button click with force
                    btn = page.locator("#inspireBtn")
                    if await btn.count() > 0:
                        await btn.click(force=True)
                        await asyncio.sleep(2)
                except Exception as e2:
                    if verbose:
                        print(f"[spongify] Button click also failed: {e2}")

            # Wait for result image to appear (might be in canvas or img)
            if verbose:
                print("[spongify] Waiting for generation...")

            start_time = time.time()
            result_src = None
            check_count = 0

            while time.time() - start_time < timeout_sec:
                try:
                    # Method 1: Look for img with data URI (most common)
                    imgs = await page.locator("img").all()
                    for img in imgs:
                        try:
                            src = await img.get_attribute("src")
                            if src and len(src) > 500 and src.startswith("data:image"):
                                result_src = src
                                break
                        except Exception:
                            pass

                    if result_src:
                        if verbose:
                            print("[spongify] Found output image in img tag!")
                        break

                    # Method 2: Look for canvas element and convert to data URI
                    canvases = await page.locator("canvas").all()
                    if canvases and not result_src:
                        try:
                            # Try to convert canvas to data URL
                            canvas_data = await page.evaluate(
                                "canvas => canvas.toDataURL('image/png')",
                                canvases[0].element_handle()
                            )
                            if canvas_data and len(canvas_data) > 500:
                                result_src = canvas_data
                                if verbose:
                                    print("[spongify] Found output in canvas!")
                                break
                        except Exception as e:
                            if verbose and check_count % 10 == 0:
                                print(f"[spongify] Canvas check: {e}")

                    check_count += 1
                    if verbose and check_count % 6 == 0:  # Every 6 seconds
                        print(f"[spongify] Waiting... {int(time.time() - start_time)}s")

                except Exception as e:
                    if verbose:
                        print(f"[spongify] Check error: {e}")

                await asyncio.sleep(1)

            if not result_src:
                await browser.close()
                elapsed = int(time.time() - start_time)
                return SpongifyResult(
                    image_bytes=b"",
                    error=f"Generation failed (timeout after {elapsed}s)"
                )

            # Extract image from data URI
            try:
                # Format: data:image/png;base64,<encoded-data>
                if "," in result_src:
                    _, b64_data = result_src.split(",", 1)
                    image_bytes = base64.b64decode(b64_data)
                else:
                    await browser.close()
                    return SpongifyResult(image_bytes=b"", error="Invalid data URI format")

                if verbose:
                    print(f"[spongify] Extracted {len(image_bytes)} bytes")

                await browser.close()

                if len(image_bytes) < 100:
                    return SpongifyResult(
                        image_bytes=b"",
                        error=f"Generated image too small ({len(image_bytes)} bytes)"
                    )

                return SpongifyResult(image_bytes=image_bytes)

            except Exception as e:
                await browser.close()
                return SpongifyResult(image_bytes=b"", error=f"Decode error: {e}")

    except asyncio.TimeoutError:
        return SpongifyResult(image_bytes=b"", error="Browser timeout")
    except Exception as e:
        return SpongifyResult(image_bytes=b"", error=f"Error: {e}")


def spongify_sync(image_path: Path, **kwargs) -> SpongifyResult:
    """Synchronous wrapper for async function."""
    try:
        return asyncio.run(spongify_via_web(image_path, **kwargs))
    except Exception as e:
        return SpongifyResult(image_bytes=b"", error=f"Async error: {e}")
