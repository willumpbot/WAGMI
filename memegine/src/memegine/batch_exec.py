"""Batch executor — run every brief in a batch through Claude.

Takes a batch folder produced by `batch.build()` and, if
ANTHROPIC_API_KEY is set, submits each item's SYSTEM+USER to Claude,
parses the returned JSON, and writes a `executed/<slug>.json` file
alongside the original brief. Lints each resulting prompt.

The operator can now generate 6 ready-to-paste-into-Grok prompts in a
single command, or generate all 6 AND pre-lint them with a single key.
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import batch as batch_mod, deep_linter, executor, prompt_engine
from ._time import now_iso as _now_iso


@dataclass
class ExecutedItem:
    format_slug: str
    prompt: str = ""
    score: int = 0
    lint_ok: bool = True
    variants: list[str] = field(default_factory=list)
    captions: list[dict] = field(default_factory=list)
    error: str = ""


@dataclass
class BatchExecution:
    batch_id: str
    theme: str
    folder: str
    executed_at: str
    items: list[ExecutedItem] = field(default_factory=list)

    def best_item(self) -> ExecutedItem | None:
        ok_items = [i for i in self.items if i.lint_ok and not i.error]
        if not ok_items:
            return None
        return max(ok_items, key=lambda i: i.score)


def execute(
    batch_result: "batch_mod.BatchResult | None" = None,
    *,
    theme: str | None = None,
    n: int = 4,
    formats: list[str] | None = None,
    by_performance: bool = False,
    outputs_dir: Path | None = None,
    model: str | None = None,
) -> BatchExecution:
    """Build (or re-use) a batch and run every item through Claude.

    Pass an existing `batch_result` to re-execute an already-built batch,
    or leave it None to build a fresh one via `batch.build()` using theme /
    n / formats / by_performance / outputs_dir.
    """
    if not executor.api_key_available():
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set — use `memegine batch` for offline briefs"
        )

    if batch_result is None:
        if not theme:
            raise ValueError("theme is required when batch_result is None")
        batch_result = batch_mod.build(
            theme, n=n, formats=formats, by_performance=by_performance,
            outputs_dir=outputs_dir,
        )

    folder = Path(batch_result.folder)
    executed_dir = folder / "executed"
    executed_dir.mkdir(parents=True, exist_ok=True)

    items: list[ExecutedItem] = []
    for item in batch_result.items:
        ex_item = ExecutedItem(format_slug=item.format_slug)
        try:
            brief = executor.execute_prompt_brief(
                item.intent, item.format_slug, model=model,
            )
            ex_item.prompt = brief.prompt
            ex_item.variants = brief.variants
            ex_item.captions = brief.captions
            if brief.prompt:
                score = deep_linter.score(brief.prompt)
                ex_item.score = score.score
                ex_item.lint_ok = score.base_lint_ok
        except Exception as exc:
            ex_item.error = str(exc)
            ex_item.lint_ok = False

        items.append(ex_item)
        # Write per-item JSON for easy inspection.
        (executed_dir / f"{item.format_slug}.json").write_text(
            json.dumps(asdict(ex_item), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    result = BatchExecution(
        batch_id=batch_result.id,
        theme=batch_result.theme,
        folder=str(folder),
        executed_at=_now_iso(),
        items=items,
    )
    (folder / "execution.json").write_text(
        json.dumps(asdict(result), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return result


def summary_text(result: BatchExecution) -> str:
    lines = [
        f"=== batch execution {result.batch_id} — theme: {result.theme} ===",
    ]
    best = result.best_item()
    for item in result.items:
        star = "* " if best and item.format_slug == best.format_slug else "  "
        status = "ERR" if item.error else ("FAIL" if not item.lint_ok else f"{item.score}/100")
        lines.append(f"{star}{item.format_slug:<28} {status}")
        if item.prompt:
            lines.append(f"    {item.prompt[:100]}...")
        if item.error:
            lines.append(f"    error: {item.error}")
    if best:
        lines.append("")
        lines.append(f"winner: {best.format_slug}")
        lines.append(best.prompt)
    return "\n".join(lines)
