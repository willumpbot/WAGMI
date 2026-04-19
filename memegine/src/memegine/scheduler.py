"""Scheduler — daily/weekly brief batches that run themselves.

A job is a YAML entry at data/scheduler/jobs.yaml specifying:
- when (cron-ish: hour, minute, days_of_week)
- what (pull N topics from queue → generate briefs → deliver)
- delivery (telegram | stdout | file)

Loop pattern (blocking, for `memegine schedule run`):
  every 60s:
    for each job whose next_fire_at <= now:
      run the job
      update next_fire_at

This is intentionally tiny: no APScheduler, no celery. You either run the
scheduler in a tmux / screen session, or you invoke `memegine schedule
fire <job_id>` from a system cron / launchd / Task Scheduler. Both work.
"""
from __future__ import annotations

import datetime as dt
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Iterable

import yaml

from . import pipeline as pipeline_mod
from . import topics as topics_mod
from .config import settings


@dataclass
class ScheduleJob:
    id: str
    name: str
    hour: int                       # 0-23 local hour
    minute: int                     # 0-59
    days_of_week: list[int] = field(default_factory=lambda: list(range(7)))  # 0=Mon
    action: str = "daily_batch"     # "daily_batch" | "weekly_distill" | "custom"
    n_topics: int = 3               # how many topics to pull per fire
    kind: str = "any"               # "image" | "video" | "any"
    delivery: str = "file"          # "file" | "telegram" | "stdout"
    enabled: bool = True
    created_at: str = ""
    last_fire_at: str | None = None


def _jobs_path() -> Path:
    return settings.data_dir / "scheduler" / "jobs.yaml"


def _load() -> list[dict]:
    p = _jobs_path()
    if not p.exists():
        return []
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return list((raw.get("jobs", []) if isinstance(raw, dict) else raw) or [])


def _save(jobs: list[dict]) -> None:
    p = _jobs_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        yaml.safe_dump({"jobs": jobs}, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def add(
    *,
    name: str,
    hour: int,
    minute: int = 0,
    days_of_week: Iterable[int] | None = None,
    action: str = "daily_batch",
    n_topics: int = 3,
    kind: str = "any",
    delivery: str = "file",
) -> ScheduleJob:
    if not 0 <= hour <= 23:
        raise ValueError(f"hour must be 0-23, got {hour}")
    if not 0 <= minute <= 59:
        raise ValueError(f"minute must be 0-59, got {minute}")
    dow = sorted(set(int(d) for d in (days_of_week or range(7))))
    for d in dow:
        if not 0 <= d <= 6:
            raise ValueError(f"day_of_week must be 0-6 (Mon-Sun), got {d}")

    job = ScheduleJob(
        id=uuid.uuid4().hex[:8],
        name=name,
        hour=hour,
        minute=minute,
        days_of_week=dow,
        action=action,
        n_topics=n_topics,
        kind=kind,
        delivery=delivery,
        created_at=dt.datetime.utcnow().isoformat() + "Z",
    )
    jobs = _load()
    jobs.append(asdict(job))
    _save(jobs)
    return job


def list_jobs(*, enabled_only: bool = False) -> list[dict]:
    jobs = _load()
    if enabled_only:
        jobs = [j for j in jobs if j.get("enabled", True)]
    return jobs


def remove(job_id: str) -> bool:
    jobs = _load()
    before = len(jobs)
    jobs = [j for j in jobs if j.get("id") != job_id]
    if len(jobs) != before:
        _save(jobs)
        return True
    return False


def set_enabled(job_id: str, enabled: bool) -> bool:
    jobs = _load()
    hit = False
    for j in jobs:
        if j.get("id") == job_id:
            j["enabled"] = enabled
            hit = True
    if hit:
        _save(jobs)
    return hit


def _should_fire(job: dict, now: dt.datetime) -> bool:
    """Return True if the job should fire at this minute and hasn't yet today."""
    if not job.get("enabled", True):
        return False
    if int(now.weekday()) not in job.get("days_of_week", list(range(7))):
        return False
    if int(now.hour) != int(job.get("hour", -1)):
        return False
    if int(now.minute) != int(job.get("minute", -1)):
        return False

    last = job.get("last_fire_at")
    if not last:
        return True
    try:
        last_dt = dt.datetime.fromisoformat(last.replace("Z", ""))
    except ValueError:
        return True
    # Don't fire twice within the same minute window.
    return (now - last_dt).total_seconds() >= 60


def _mark_fired(job_id: str) -> None:
    jobs = _load()
    now = dt.datetime.utcnow().isoformat() + "Z"
    for j in jobs:
        if j.get("id") == job_id:
            j["last_fire_at"] = now
    _save(jobs)


# ---- actions ---------------------------------------------------------------


@dataclass
class JobResult:
    job_id: str
    fired_at: str
    action: str
    topics_used: list[str] = field(default_factory=list)
    bundles: list[str] = field(default_factory=list)   # bundle IDs created
    note: str = ""


def run_daily_batch(job: dict, *, deliver: Callable[[dict, JobResult], None] | None = None) -> JobResult:
    """Pop N topics → build a pipeline bundle for each → deliver."""
    n = int(job.get("n_topics", 3))
    kind = job.get("kind", "any")
    picked = topics_mod.pop(n=n, mark_used=True)
    result = JobResult(
        job_id=job.get("id", "?"),
        fired_at=dt.datetime.utcnow().isoformat() + "Z",
        action=job.get("action", "daily_batch"),
    )
    if not picked:
        result.note = "no topics queued"
        if deliver:
            deliver(job, result)
        return result

    from . import format_suggest  # lazy import; only needed for this action.
    for topic in picked:
        intent = topic.get("text", "")
        t_kind = topic.get("kind") or (kind if kind != "any" else None)
        chosen_kind = t_kind or format_suggest.infer_kind(intent)
        slug = topic.get("format_hint") or format_suggest.best(intent, kind=chosen_kind)
        try:
            bundle = pipeline_mod.build(
                intent,
                kind=chosen_kind,
                format_slug=slug if chosen_kind == "image" else None,
            )
            topics_mod.mark_used(topic["id"], bundle_id=bundle.id)
            result.topics_used.append(topic["id"])
            result.bundles.append(bundle.id)
        except Exception as exc:  # isolate per-topic failures
            result.note += f"\nfailed {topic.get('id')}: {exc}"

    if deliver:
        deliver(job, result)
    return result


def run_weekly_distill(job: dict, *, deliver: Callable[[dict, JobResult], None] | None = None) -> JobResult:
    """Mine the past N days of archived briefs for pattern frequencies and
    write a distill line to the codex.
    """
    from . import archive, auto_codex
    # Pull recent briefs' user messages as a proxy for "prompts that shipped".
    recent = archive.read_recent(n=200)
    prompts = [r.get("user", "") for r in recent]
    dist = auto_codex.distill_to_codex(prompts, min_frequency=2)
    result = JobResult(
        job_id=job.get("id", "?"),
        fired_at=dt.datetime.utcnow().isoformat() + "Z",
        action="weekly_distill",
        note="categories: " + ", ".join(f"{k}={len(v)}" for k, v in dist.items()),
    )
    if deliver:
        deliver(job, result)
    return result


def run_morning_brief(job: dict, *, deliver: Callable[[dict, JobResult], None] | None = None) -> JobResult:
    """Compose a morning intelligence drop: dashboard + recent trends +
    top queued topics + last perf leader. Designed to be delivered at a
    fixed time each morning so the operator wakes up with a plan.
    """
    from . import journal, next_action, performance, topics
    dash = next_action.compute()

    recent_journal = journal.collect(days=2, limit=15)
    top_perf = performance.by_format()[:3]
    top_topics = topics.list_queued(limit=5)

    body_lines = [dash.as_text(), "", "=== last 48h journal ==="]
    if recent_journal:
        for e in recent_journal[:10]:
            body_lines.append("  " + e.as_line())
    else:
        body_lines.append("  (no journal entries)")

    if top_perf:
        body_lines.append("")
        body_lines.append("=== top 3 formats by engagement ===")
        for slug, n, avg in top_perf:
            body_lines.append(f"  {slug:<28} n={n:<3}  avg={avg:.1f}")

    if top_topics:
        body_lines.append("")
        body_lines.append("=== next up (top 5 topics) ===")
        for t in top_topics:
            body_lines.append(
                f"  p={t.get('priority', 3)}  {t.get('text', '')[:70]}"
            )

    note = "\n".join(body_lines)
    result = JobResult(
        job_id=job.get("id", "?"),
        fired_at=dt.datetime.utcnow().isoformat() + "Z",
        action="morning_brief",
        note=note,
    )
    if deliver:
        deliver(job, result)
    return result


ACTIONS: dict[str, Callable[..., JobResult]] = {
    "daily_batch": run_daily_batch,
    "weekly_distill": run_weekly_distill,
    "morning_brief": run_morning_brief,
}


def fire(
    job_id: str,
    *,
    deliver: Callable[[dict, JobResult], None] | None = None,
) -> JobResult:
    """Manually fire a job by id."""
    jobs = _load()
    job = next((j for j in jobs if j.get("id") == job_id), None)
    if job is None:
        raise KeyError(f"no such job: {job_id}")
    action = job.get("action", "daily_batch")
    fn = ACTIONS.get(action)
    if fn is None:
        raise ValueError(f"unknown action: {action}")
    result = fn(job, deliver=deliver)
    _mark_fired(job_id)
    return result


def run_loop(
    *,
    poll_seconds: int = 30,
    deliver: Callable[[dict, JobResult], None] | None = None,
    stop_after: int | None = None,  # useful for tests: exit after N iterations
) -> None:
    """Blocking loop. Checks each minute (at poll_seconds granularity) and fires
    any job that's due. Meant for tmux / screen / systemd.
    """
    i = 0
    while True:
        now = dt.datetime.now()
        jobs = _load()
        for job in jobs:
            if _should_fire(job, now):
                try:
                    action = job.get("action", "daily_batch")
                    fn = ACTIONS.get(action)
                    if fn is None:
                        continue
                    res = fn(job, deliver=deliver)
                    _mark_fired(job["id"])
                    if deliver is None:
                        print(f"[scheduler] fired {job['name']}: {res.note or ''} bundles={res.bundles}")
                except Exception as exc:
                    print(f"[scheduler] job {job.get('name')} failed: {exc}")
        i += 1
        if stop_after is not None and i >= stop_after:
            return
        time.sleep(poll_seconds)
