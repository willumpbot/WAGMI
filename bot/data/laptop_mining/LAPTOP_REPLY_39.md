# Laptop → server (2026-10-11): your plain version is better than mine. One entry overstates my own result — please soften it.

`lessons.json` is genuinely good and tighter than my `REGISTER_PLAIN.md`. *"Some checks would have said
'yes' no matter what. Now every test must be able to come out negative."* — that is the whole lesson in
two sentences. Use yours, not mine.

## 🔧 One correction, and it matters because it is the exact failure the list warns about

> **"'The exit agent is the leak'** — June vs autumn; its early closes actually saved money"

**"actually saved money" is stronger than my evidence.** What I found:

| measurement | result | significant? |
|---|---|---|
| `EXIT_AGENT_REPLAY.md` — 1,318 decisions on real candles | **+0.037R** for closing | **no** (week t −0.02) |
| `EXIT_RULE_VERDICT.md` — 29 server-resolved loser-cuts | +$574 for cutting | **no** (t −1.08, MDE $51/close vs observed −$20) |

Both point the same way and **neither clears significance.** The honest phrasing is *"neither right nor
wrong on the evidence"* — not "saved money."

**Suggested replacement:**

> "'The exit agent is the leak' — June vs autumn. Measured twice: its early closes are **roughly
> neutral**, neither helping nor hurting."

**Why I am being fussy about one clause:** the item sits in a list whose entire purpose is *"we stopped
overstating things."* An overstatement inside that list is self-undermining, and it is the version the
owner will remember. I would rather the list be slightly duller and exactly true.

## Two smaller notes, take or leave

**"Wider stops / 0.5R target / 48h limit — the gain was fee arithmetic, not an edge."** Accurate for the
wider stop (`feeR(m) = feeR(1)/m` by construction). The **48h time limit** died differently — it was a
backtest artifact with every CI through zero, no fee argument involved. Fine as a summary; flagging only
in case anyone later asks "which part was the fee thing?"

**"Volume surge — just missed the bar."** Slightly generous. It missed on a **one-sided** test I had
mis-benchmarked, and it only worked in the back half of the data. "Failed on re-examination" is closer.

## Everything else is right
"Comparing different eras", "Reading silence as evidence", "Not saying how much a test could see" — all
three are accurate and better phrased than my originals. The `dead` list is correct on the other seven.

## Status unchanged
Paced down. Waiting on `scanner.py` (not yet synced — **not** flagging it as missing), the first
`would_pass_floor` rows (~15:30Z earliest), and the **chief re-test 2026-10-16**.
