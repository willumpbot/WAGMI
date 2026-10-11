# Plain-language version of REGISTER sections 2 and 5 — for the owner's History tab

_2026-10-11. The server is surfacing `REGISTER.md` §2 and §5 on the owner's terminal. **I wrote those
for machines** — they use MDE, "algebraically incapable", "design effect", week-clustering. Nunu runs
this from a phone between 10-hour work shifts; jargon is friction, not rigour. Use this version for
anything owner-facing and keep `REGISTER.md` as the technical one._

---

## Things we already tried that don't work — don't let anyone talk you back into them

**Each of these looked promising and was tested properly. They're closed.**

| idea | the short reason |
|---|---|
| Make the trailing exit smarter | My test had three bugs in it. When they were fixed the advantage vanished. |
| Switch the volatility maths to something simpler | I claimed the old way was broken. **I was comparing it to something I'd made up myself.** The original is better. Keep it. |
| Use a wider stop, or a closer target, or hold longer | None of them held up. The one number that looked good turned out to be true by definition, not by measurement. |
| Size up when trading volume spikes | Failed its own test, and 1 day in 10 that it flagged had no volume data at all. |
| Stop the AI closing trades early | Of the 29 trades where this would have applied, **23 would have run into their stop.** Letting them run costs more. |
| Trade one coin against another (long the strong, short the weak) | Fees alone eat 0.36% a day. The edge was never bigger than the fees. |
| Earn the funding rate with a hedged position | Earns 1–2.5% a year, and the costs grow with your size. Not worth the complexity. |
| Treat liquidation clusters as price targets | Tested twice on different data and got **opposite answers.** |
| Tighten the trend filter | Can't be measured with the data we have, and setting it high would throw away 92% of all signals. |
| Use the confidence score as a gate | **It hasn't actually been doing anything since June** — the code path skips it entirely. |

## Why I keep having to take things back

**More than a dozen conclusions have been overturned. None of them were made up.** Every single one was
the same mistake wearing a different hat: **being more sure than the evidence allowed.**

Four shapes it takes:

**1. A test that can't come out "no".** The clearest example: I was measuring whether something was
bigger than zero, using a method that could only ever produce a number bigger than zero. It "passed"
every time, on any data, including random noise. Now I ask, every time: *could this result ever have
been negative?*

**2. Comparing June against July without noticing.** Three separate "discoveries" turned out to be
"June was a good month and July was a bad one." The confidence score one was the clearest — **the score
didn't exist before July**, so every trade before then had a zero in that column, and I'd found that
zeros did better. Now I split everything by month before believing it.

**3. Mistaking a gap in the records for nothing happening.** Four near-misses in one day. Logs get
rotated weekly, some files only keep recent data, and the sync runs hourly — so a missing day usually
means *the record is missing*, not that the bot was idle. I nearly told you your bot was switched off
for three weeks.

**4. Not saying how small an effect I could even detect.** Several "we found nothing" results could
only have spotted an edge worth **90%+ a year.** That's not "nothing is there" — it's "we couldn't see
anything short of enormous." Very different claims.

**Two more, learned today:**

- **A move being 7.7% bigger does not mean the stop needs to be 7.7% wider.** I assumed that and was
  wrong by nearly 3×. The real answer has to be measured, not calculated.
- **"It finished without an error" is not the same as "it worked."** Your clip queue sat empty for 74
  days because a script crashed *and reported success*. Now I check what actually happened, not what
  the program claimed.

## The one-line summary

**Nothing has ever shown it can predict which way the price goes.** Everything that survived is about
*how big* a move will be and *how much* to risk — never direction. That's worth knowing, because it
means the bot standing aside in a quiet market is the right behaviour, not a fault.
