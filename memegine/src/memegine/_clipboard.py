"""Tiny cross-platform clipboard helper.

No pyperclip dependency — shells out to the OS-native tool. Silent
failure: if copy doesn't work (e.g. headless Linux with no xclip), the
caller prints the text to stdout so the operator can grab it manually.
"""
from __future__ import annotations

import subprocess
import sys


def copy(text: str) -> bool:
    """Copy `text` to the system clipboard. Returns True on success."""
    if not text:
        return False
    try:
        if sys.platform == "win32":
            # Windows: `clip` reads from stdin.
            p = subprocess.run(
                ["clip"], input=text, text=True, check=True,
                encoding="utf-8", shell=True,
            )
            return p.returncode == 0
        if sys.platform == "darwin":
            p = subprocess.run(
                ["pbcopy"], input=text, text=True, check=True,
                encoding="utf-8",
            )
            return p.returncode == 0
        # Linux: try xclip then xsel.
        for cmd in (["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]):
            try:
                p = subprocess.run(cmd, input=text, text=True, check=True, encoding="utf-8")
                if p.returncode == 0:
                    return True
            except (FileNotFoundError, subprocess.CalledProcessError):
                continue
        return False
    except (subprocess.CalledProcessError, OSError):
        return False
