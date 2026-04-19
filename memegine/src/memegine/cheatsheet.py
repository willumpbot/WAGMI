"""Cheatsheet — the 20 commands you actually use 90% of the time.

Designed for a phone terminal: narrow, scannable, grouped by intent.
"""
from __future__ import annotations

CHEATSHEET = """=== MEMEGINE CHEATSHEET ===

STATE
  memegine next              what should I make?
  memegine last              most recent brief/winner/post/session
  memegine stats daily       today's activity
  memegine search "X"        find across everything
  memegine env               show env vars (secrets masked)
  memegine doctor            health check

CAPTURE (phone-friendly)
  memegine topics add "..."        queue an idea
  memegine grade-idea "..."        score 0-100 before you brief
  memegine topics list             see what's queued
  memegine from-topic <id>         build a bundle for a topic

BRIEF
  memegine piece "..."                  full bundle (auto format)
  memegine prompt "..." -f <format>     single image brief
  memegine shots "..."                  video shot list
  memegine batch "theme" -n 4           N briefs across formats
  memegine batch-execute "..." -n 4     (needs ANTHROPIC_API_KEY)

LINT / FIX
  memegine lint "..."                validate prompt
  memegine score "..."               0-100 craft coverage
  memegine fix-prompt "..."          auto-insert fragments
  memegine caption-lint "..."        validate caption for X

COMPOUND (the winning loop)
  memegine refs add img.png --winner --prompt "..." --auto-variants
  memegine variants-last -n 6                    tweak last winner
  memegine like-winner "new subject"             inherit the craft
  memegine codex distill                         mine recent patterns
  memegine codex graduate --threshold 5          promote patterns

POST
  memegine post build media.png --caption "..." --alt "..."
  memegine x prepare <bundle_id>     X clipboard block
  memegine perf paste "820 likes 140 RT 35 replies 12.4K views"

SESSION
  memegine flow morning --name "morning"      open + dashboard + last
  memegine flow evening                       close + distill + stats
  memegine session start|end|current|list

FEEDS / AUTO
  memegine trends add-feed <name> <url>       RSS / JSON feed
  memegine trends fetch                       append new titles to queue
  memegine schedule add ...                   cron-style jobs
  memegine serve                              bot + scheduler

CODEX
  memegine codex init                         seed template
  memegine codex show
  memegine codex audit                        duplicates / contradictions
  memegine codex auto-winner "prompt" "why"

FRAGMENTS
  memegine fragments list                     browse library
  memegine fragments expand "LENS.35mm_1_4 ..."  expand inline
  memegine fragments show LENS.35mm_1_4

HEALTH
  memegine doctor                             env + deps check
  memegine validate                           YAML integrity
  memegine self-test                          synthetic operator walk

PHONE ALIASES (add to ~/.bashrc)
  alias m='memegine'
  alias mn='memegine next'
  alias ml='memegine last'
  alias mq='memegine topics add'
  alias mg='memegine grade-idea'
  alias mp='memegine piece'
  alias mfm='memegine flow morning'
  alias mfe='memegine flow evening'
  alias ms='memegine search'

=== END ===
"""


def render() -> str:
    return CHEATSHEET
