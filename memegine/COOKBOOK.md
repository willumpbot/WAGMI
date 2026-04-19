# Memegine cookbook — 10 workflows

Concrete recipes for the operator's day-to-day. Each is a sequence of
commands the tool expects, in the order they make sense.

---

## 1. Morning ritual (5 min)

```bash
memegine flow morning --name "morning"
# opens session + shows dashboard + shows last activity
```

Look at:
- The queue (any pending topics?)
- Last winner (anything to re-use via like-winner?)
- Top-performing format (bias today's pieces there?)
- Recommendations (concrete next moves)

Pick ONE topic to work on. Everything else is distraction.

---

## 2. "I just had an idea" capture (10 sec)

You're walking, an idea lands. Pull out phone:

```bash
m topics add "trader cope face at 3am after ETH -12%" -p 4
```

Or via Claude CLI:

```bash
claude
# "add to topic queue: trader cope face at 3am after ETH -12%, priority 4"
```

That's it. The scheduler will include it in tomorrow's morning brief.

---

## 3. Hero photoreal piece (30-45 min)

```bash
# 1. Grade the idea first.
memegine grade-idea "trader at 3am, cope face, 12% drawdown"
# → A, score 100

# 2. Pipeline it.
memegine piece "trader at 3am, cope face, 12% drawdown"

# 3. Open the bundle folder. Paste the first .md into Claude Code.
# 4. Claude returns JSON; copy the `prompt` field.
# 5. Paste into Grok (Nano Banana / Aurora). Iterate.
# 6. When a generation lands, score it:
memegine score "the generated prompt"

# 7. Compound.
memegine refs add final.png \
  --winner --prompt "the prompt" --notes "3am dread landed"

# 8. Pack for posting.
memegine post build final.png --caption "kitchen, no one home" \
  --alt "trader portrait at 3am, quiet dread"

# 9. X pre-flight.
memegine x prepare <bundle_id>
# → prints a clipboard-ready block

# 10. Post on phone. Log engagement later.
memegine perf paste "820 likes 140 RT 35 replies 12.4K views"
```

---

## 4. Reactive news-hook piece (10-15 min)

ETH just dumped. You have a 30-minute window before the joke goes cold.

```bash
# 1. Queue is skipped — this is reactive.
memegine batch "ETH broke below 2800 at 4am" -n 4
# → 4 briefs across different formats (meme, chart, portrait, lore)

# 2. Open each .md, run in Claude Code, pick the 1 that lands.
# 3. Skip iteration — ship first landing.
memegine refs add shot.png --winner --prompt "..." --notes "reactive landed"
memegine post build shot.png --caption "..."
```

---

## 5. Batch production session (60-90 min)

Saturday morning. Produce 5-8 pieces for the week.

```bash
# 1. Open session.
memegine session start "saturday-batch"

# 2. Drain the queue.
memegine topics pop -n 6

# 3. For each popped topic, pipeline it.
for id in $(memegine topics list --status used | head -6 | cut -d' ' -f1); do
  memegine from-topic $id
done

# 4. Work each bundle serially in Grok.
# 5. Pack the winners.
# 6. Schedule posts across the week via your normal posting tool.

# 7. End session, distill.
memegine flow evening
```

---

## 6. Reverse-engineer a look (15-20 min)

You saw a photo on X you love. You want to produce in that style.

```bash
# 1. Save the image locally: ref.png
# 2. Reverse the look.
memegine reverse ref.png --context "want this quiet suburban dread"
# → brief in Claude Code, paste it, Claude returns the recreate prompt

# 3. Save as a reference.
memegine refs add ref.png \
  --tags "reference,<creator>,<mood>" --notes "source: <url>"

# 4. Try the recreate prompt.
memegine score "the recreate prompt"  # verify it's A-grade

# 5. Run it in Grok.
```

---

## 7. Variants from your latest winner (5 min)

```bash
memegine variants-last -n 6
# → 6 single-axis tweaks from your last winner

# Paste the output into Claude Code. Claude returns the 6 variant
# prompts. Run in Grok. Likely one or two compound on the winner.
```

This is the "do it again, a little different" command.

---

## 8. Kill a stale format (2 min)

Drake yes/no has flopped three times in a row.

```bash
memegine codex flop "drake_yes_no format" "feels stale Q2 2026"
memegine format-health
# → now you see drake_yes_no flagged
```

Future `memegine suggest` will deprioritize it, and `format_health`
will nag you if it stays on the curated rotation.

---

## 9. Scheduled morning brief (one-time setup, daily payoff)

```bash
# Set up telegram delivery.
export MEMEGINE_TELEGRAM_BOT_TOKEN=...
export MEMEGINE_TELEGRAM_ALLOWED_USER_IDS=12345
export MEMEGINE_TELEGRAM_CHAT_ID=12345

# Schedule a 7am brief.
memegine schedule add morning --hour 7 --minute 0 --action morning_brief

# Run the scheduler + bot together.
memegine serve --telegram
# (put this in tmux)
```

Every day at 7am: dashboard + last 48h journal + top formats + top
queued topics lands in your Telegram. You wake up with a plan.

---

## 10. End-of-week compounding (30 min)

Sunday evening.

```bash
# 1. Distill the week.
memegine codex distill --n 200 --min 2

# 2. Graduate frequent patterns to Core Patterns.
memegine codex graduate --threshold 5

# 3. Audit the codex.
memegine codex audit
# → any duplicates? contradictions? heavy sections to compact?

# 4. Performance review.
memegine perf summary
memegine perf by-format
memegine format-health

# 5. Journal.
memegine journal --days 7

# 6. Write one voice note about what you learned this week.
memegine codex flop "the thing that didn't work" "specifically why"
# OR: directly edit data/codex/style.md under "Voice Notes"
```

You now start next week with a sharper codex than last week. Over 10
weeks, the compounding becomes obvious. Every brief inherits more.

---

## Anti-patterns (things to NOT do)

- **Don't brief vague intents.** `grade-idea` first. Anything D or F
  gets fixed before you spend a brief on it.
- **Don't skip the caption linter.** Emojis / hashtags / "lfg" kill
  reach on crypto X. The linter catches them.
- **Don't manually log perf numbers.** Use `perf paste`. Friction kills
  the feedback loop.
- **Don't copy a full winner prompt and just swap the subject.** Use
  `like-winner` — it inherits just the craft, not the subject, so you
  get compounding without repetition.
- **Don't add to the codex manually if there's an automatic path.**
  `refs add --winner` is better than `codex winner` because it also
  extracts patterns.
- **Don't let the queue go empty.** The morning brief is useless if
  there's nothing in the queue. Drop 2-3 topics every evening.

---

## The anti-anti-pattern

The operator's taste is the thing. Memegine removes friction; it never
replaces judgment. If the tool is telling you to do something that
feels wrong, it's wrong. Update the codex with your instinct, not the
tool's default.
