"""Shared JSONL file utilities for reading bot log files."""
import json
from typing import List


def tail_jsonl(path: str, n: int) -> List[dict]:
    """Read the last N valid JSON lines from a JSONL file efficiently.

    Scans file from the end to avoid loading the entire file.
    Returns entries in newest-first order.
    Returns empty list if file doesn't exist or is empty.
    """
    try:
        with open(path, "rb") as f:
            # Seek to end, scan backwards for newlines
            f.seek(0, 2)
            size = f.tell()
            if size == 0:
                return []

            # Buffer to accumulate lines
            lines = []
            chunk = 8192
            pos = size
            remainder = b""

            while pos > 0 and len(lines) < n + 1:
                read_size = min(chunk, pos)
                pos -= read_size
                f.seek(pos)
                data = f.read(read_size) + remainder
                parts = data.split(b"\n")
                remainder = parts[0]
                lines = parts[1:] + lines

            # Include the remainder (first line of file)
            if remainder:
                lines = [remainder] + lines

        # Parse and return last n valid entries, newest first
        parsed = []
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                parsed.append(json.loads(line))
            except Exception:
                continue
            if len(parsed) >= n:
                break
        return parsed

    except FileNotFoundError:
        return []
    except Exception:
        return []
