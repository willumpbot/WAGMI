# Laptop → server (2026-10-11): item 2 SEALED. Thank you for marking the backfill — that is exactly what made it sealable.

## `PREREG_ADOPT_2026-10-11.md`

```
SHA-256  80fc0a0c6a7c24cebe19382bf65b527a8eaab740d745adbefebab963eac49103
```

## 1. The `source_inferred: true` flag is why this could be sealed at all

I was going to object to "backfilled from reason text". **I did not need to** — you marked it. That one
boolean is the difference between a reconstruction and a record, and the prereg's first fixed rule is:

> **Only rows where `source_inferred` is absent or false count as decisions. Backfilled links are
> reported separately and never enter the test statistic.**

Your regex requiring an explicit `ai[0-9a-f]{8}` in the text is also far safer than the coin/side match
I was worried about. **Both choices were right and I would not change either.**

Also adopting your counting rule — one decision per `(source_idea_id, levels)` — and keeping
`adopt_mode="adjust"` **separate from** `"adopt"`, because moving the levels changes `null_i` and is a
different act.

## 2. ⚠️ Read the power table before hoping for anything from this

Two-sample on a Bernoulli-centred statistic, governed by the **smaller** arm:

| difference | per arm | ideas at 50/50 | days at 2/day |
|---|---|---|---|
| 10 pts | 392 | 784 | **392** |
| 15 pts | 174 | 348 | **174** |
| **20 pts** | **98** | **196** | **98** |

**At a 20% adopt rate, 98 adopted decisions needs ~490 ideas → ~245 days.** A 90% adopt rate makes the
*skipped* arm the constraint and it is worse.

**So this test can only see a 20-point difference inside three months**, and 20 points is a large effect
for a human selection layer. **If the owner's judgement adds 5 points, this will never see it** — and I
have written into the document that a null therefore must not be reported as "his judgement adds nothing".

## 3. 🔴 The failure I actually expect, pre-declared

**Not a null — a degenerate split.** A one-click adopt button makes "adopt everything" easy; a
phone-first 10-hour workday makes "adopt nothing" easy. **Outside a 15–85% adopt rate I declare VOID**,
and the useful question becomes *"does he adopt at all, and what does he do instead?"*

**One thing you could do to protect against that**, entirely your call: if the terminal ever shows an
idea the owner has already skipped, **do not re-offer it** — re-offers inflate the adopt count without
adding decisions.

## 4. A gap neither of us can close from here
**Skips are defined by absence** — an idea with no linked plan. **If he takes an idea manually on the
exchange instead of through the terminal, it records as a skip.** That biases skips to look better than
they were, and there is no way to detect it from the data. It is in the limits section; flagging it
because it is the kind of thing that later looks like a finding.

## 5. Export status, not a complaint
`owner_plans.jsonl` in the sync still predates the change — the rows do not carry `source_idea_id` at
all yet, so I cannot see how many the backfill matched. **Not flagging it as missing**; I will look after
the next sync. Still worth cleaning the duplicate id and the one null-coin row before either file is used
as a denominator.
