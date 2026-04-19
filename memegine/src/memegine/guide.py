"""Guide — print the "start here" flow for a new operator.

Fast orientation for someone who just installed memegine. Points at
the 5 commands that matter first and the phone setup link.
"""
from __future__ import annotations

GUIDE = """=== MEMEGINE — WHERE TO START ===

1) Verify the environment.
   memegine doctor
   memegine validate
   memegine self-test
   All three should end in PASS.

2) Seed the style memory (pick ONE path).

   If you already have a folder of editor work (Dropbox / Google Drive
   sync folder):
     memegine corpus ingest "~/Dropbox/your-folder" --frames 5
     memegine corpus reverse         # needs ANTHROPIC_API_KEY (~$0.003/img)
     memegine corpus distill
     memegine corpus stats           # see what got learned

   If you're starting blank:
     memegine codex init             # seeds the template
     # Edit data/codex/style.md — fill North Star + Voice + Visual DNA

3) Capture an idea (this is the daily loop).
   memegine quick "trader at 3am cope face"
   # grades + queues the idea (refuses D/F grades)

4) Build a brief when you're ready.
   memegine piece "trader at 3am cope face"
   # -> opens bundle folder; paste each .md into Claude Code or claude.ai

5) Tighten the prompt Claude returns before pasting into Grok.
   memegine preflight "<the prompt>"
   # PASS -> paste. FAIL -> `memegine fix-prompt` for auto-insert.

6) When a piece lands, compound it.
   memegine refs add <image> --winner --prompt "..." \\
     --notes "why it landed" --auto-variants
   memegine perf paste "820 likes 140 RT 35 replies"

7) Every morning & evening:
   memegine flow morning --name "today"
   memegine flow evening
   # Opens session + dashboard, then distills at close.

--- phone setup ---

  Full Termux / iSH / a-Shell guide:   memegine/MOBILE.md
  30-second cheatsheet:                memegine cheatsheet

--- the killer workflow ---

  On your phone, run:
    claude                              (if you have Claude Code CLI)
    "I just thought of: <whatever>. /full-pipeline it."

  Claude walks you from idea -> brief -> ready-to-paste prompt in one
  turn. See memegine/.claude/skills/full-pipeline.md.
"""


def render() -> str:
    return GUIDE
