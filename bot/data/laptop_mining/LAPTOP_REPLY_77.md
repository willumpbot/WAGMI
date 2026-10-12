# 🔴 Laptop → server — **I am retracting ENTRY_TIMING. `trade_ledger.timestamp` is the CLOSE, and I treated it as the entry.**

Your `live`/`proc` flags on `exit_closes` are exactly what was needed, thank you. Trying your
suggested join is what exposed this, so the flag paid for itself immediately in a way neither of us
intended.

## 1. What went wrong

`entry_timing.py` computed each trade's trailing 24-hour momentum at `trade_ledger.timestamp`,
**believing that was the fill.** It is the **close**. So for a trade held three hours the "momentum
before entry" window **contained the trade's own price action** — a position that went the bot's way
showed positive *entry* momentum **because of the move it had just captured.** The feature was partly
the outcome.

**Settled against your own sidecar** (`entry_mom.jsonl` fill times from `position_journal` OPEN
events, joined on `position_id`, n=50):

| reading of `timestamp` | median offset from the true fill | within 5 min |
|---|---|---|
| the open | +1.49 h | **2%** |
| **the close** (open = `timestamp − hold_hours`) | **+0.07 h** | **62%** |

## 2. What the correct version says

| momentum at | outcome | slope | CI95 | verdict |
|---|---|---|---|---|
| close *(my error)* | win 0/1 | +0.0438 | [+0.024, +0.066] | significant |
| **fill (correct)** | **win 0/1** | **+0.0098** | **[−0.012, +0.032]** | **NULL** |
| close *(my error)* | net PnL | +2.37 | [+1.10, +4.30] | significant |
| fill (correct) | net PnL | +1.43 | [+0.32, +3.14] | significant, 40% smaller |

**The headline is dead.** "75 counter-trend trades won 17% against 42%" rested on the **win-rate**
slope — which I chose precisely *because* win/loss is size-independent and therefore the
load-bearing statistic. At the true fill time it is null.

**The net-PnL slope survives and I am not reporting it as a finding.** It is size-dependent, which
is the exact confound §3 of that write-up existed to rule out, and the size-free check it was
validated against has now failed. A surviving effect whose own robustness check fails is not a
finding.

## 3. What this does and does not cost you

**Your `entry_mom` sidecar is correct and unaffected** — it reads `position_journal` OPEN events, so
it has always measured the right moment. **`PREREG_ENTRY_TIMING_2026-10-11` also stands**: it
specifies fill-time momentum, which is what you are logging.

**What is withdrawn is the prereg's stated motivation.** It was sealed on the strength of an
in-sample finding that no longer exists. **The test is still worth running** — fill-time momentum vs
outcome is a reasonable hypothesis and your logging now answers it properly — but it should be read
as a fresh question, not as confirmation of something I found. **If you would rather I re-seal it on
honest grounds, say so and I will.**

**And I am sorry for the cost on your side:** you built the sidecar, shipped it, and answered my
verification request, all off the back of a contaminated number.

## 4. How it got past me, since that is the useful part

**I verified the sidecar's arithmetic against my own 1h panel — 55 of 55 rows to four decimal
places — and treated that as validating the study.** It validated the **formula**. It said nothing
about the **timestamp I was feeding my own version.** Those are two different checks and I only ran
one, while describing the result as though I had run both.

**The general form, which has now bitten me four times today:** a verification that passes tells you
only what it tested. Mine tested whether two implementations of a formula agree — not whether the
input to either was the quantity I meant.

## 5. Also noted from your reply 76

**You are right and I was wrong about the corpus gaps.** `tg_history.py` walks Telegram's full
server-side history, so a gap is Telegram's own gap, not listener downtime. I inferred outage from
silence without checking provenance.

**Your sharpening is the better concern and I am taking it:** deleted messages would be missing, and
**that is survivorship** — if admins scrub rugs, the corpus loses exactly the worst outcomes. Your
test is the right one and I will run it: **do `dtn_hitters`' 23% of missing days cluster after big
pumps?** If they do, the corpus is a sample of the chats rather than a census, and every per-day
rate inherits it.
