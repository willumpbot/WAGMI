# 🔴 CORRECTED SAME DAY — **every horizon label below is wrong. This is a 24-HOUR study, not a 60-day one, and the correction reopens the question it claimed to close.**

**`peak_m` is a MINUTE grid.** 1,441 points × 60-second steps = **24 hours**. I computed
`len(peak_m) / 24 = 60` and labelled the result **days**, when the unit is minutes — a factor of 60.
**So "hold 60 days" in the body below is actually "hold 24 hours", and every "sell at X" figure means
"sell at X if it happens within 24 hours".**

**What caught it:** the end-to-end check on the 58.69× call. It came back **1.30×**, and I went
looking for a second bug in the fetch. There is none — **both numbers are correct.** That coin did
1.30× in its first 24 hours and 58.69× within 14 days. **My own probe had measured 14 days; the
production fetch measures 24 hours; I compared them as if they were the same quantity.**

**What survives:**
- the **24-hour** result stands exactly as computed: every target-based exit loses over one day, and
  earlier targets lose less;
- the base rates stand — **19% unpriceable, median call closing at 0.47× of its call price within
  24h**;
- the **structural** argument in §3 stands and does not depend on the horizon: **a sell-at-2× rule
  pays +100% for a 58× coin either way.** A target cannot see a tail. That remains the answer to the
  owner's question.

**What is now UNTESTED, and it is the half that matters:**
- **"holding" was never tested beyond one day.** §2's −42.3% is a 24-hour figure, so the claim that
  holding is the worst rule is **unsupported over the horizons where memecoin peaks actually
  happen** — and the 58.69× call is direct evidence that they do.
- **§4's break-even arithmetic is therefore void**, because it compares a 24-hour hold against a
  multi-day tail.

**Why this is not quickly fixable:** the hourly fallback (`peak_h`) only runs to 72h, and it is used
only when minute data is missing — **0 of 342 fetched rows have it.** Covering 60 days hourly needs
1,440 bars against the API's 1,000-bar limit, so it is two requests per call on top of the existing
two. **That is a 2× cost on a pull that is 14% done, and it is the owner's question, so I am putting
the choice to the server rather than silently re-scoping a running job.**

---

_Original write-up follows unedited, so the error is legible rather than erased. **Read every
horizon in it as 24 hours.**_

---

# The fat-tail question, answered on corrected data: **the big winners are real and they cannot save it — because capturing them requires holding, and holding is the worst rule tested.**

_2026-10-12. 314 Telegram calls with corrected price paths (`token=<ca>` fix, 2026 only, inside the
free-data window). Dead tokens counted as −100%, not dropped. Supersedes `FATTAIL_CHECKIN.md`, whose
numbers predate the wrong-token-side bug._

---

## 1. The owner's question

> *"i dont understand how its not still easily profitable necessarily because of how many x's some
> of the winners have. there have been some massive calls semi recently."*

**The premise is correct. The conclusion does not follow, and the reason is specific.**

## 2. Every exit rule loses, and the earlier you sell the less you lose

Buy every call equally. The 19% that cannot be priced at all are **counted as −100%**, because
dropping them is the survivorship error this project keeps finding.

| rule | mean return | median | win rate | best single call |
|---|---|---|---|---|
| **sell all at 1.5×** | **−19.6%** | −14.0% | **44.2%** | +50% |
| sell all at 2× | −28.1% | −56.1% | 28.8% | +100% |
| sell all at 3× | −34.4% | −67.3% | 21.5% | +200% |
| sell all at 5× | −36.2% | −68.7% | 19.2% | +400% |
| **hold 60 days** | **−42.3%** | −70.2% | 18.3% | +555% |

**The loss shrinks monotonically as the target moves closer to the entry.** Extrapolating that
gradient, the best available target is not buying.

## 3. 🔴 Why the big winners cannot rescue it — the part that actually answers the question

**A target-based rule is blind to the tail by construction.**

I tested it directly by inserting the biggest call I know of — the **58.69×** one the token-side bug
had recorded as 1.00×, which is not yet in this sample:

| rule | mean | with one 58.69× call added | what that call contributes |
|---|---|---|---|
| sell all at 2× | −28.2% | **−27.8%** | **+100%** — identical to any plain doubler |
| sell all at 5× | −36.3% | −35.0% | +400% |
| hold 60 days | −42.3% | **−23.9%** | +5,769% |

**Under a sell-at-2× rule, a 58× call pays exactly the same as a coin that merely doubled.** The
tail is only worth something if you hold — **and holding is the worst rule on the board.**

**So the two halves of the thesis are in direct conflict:** you cannot both take profit at a target
*and* harvest the monsters. Choosing the target throws the tail away; keeping the tail means eating
the median.

## 4. How much tail holding would actually need

| | |
|---|---|
| hold-60d mean | **−42.3%**, so it needs **+42.3 points** to break even |
| one call **closing** at 58.69× contributes | **+18.4 points** |
| **so you would need** | **2.3 such calls in every 314 — 0.73% of all calls — closing there** |
| **best close actually observed in 314 calls** | **6.61×** |

**Nothing in 314 calls closes above 6.61×, and break-even needs roughly one in 137 closing at
nine times that.**

## 5. The base rate doing the damage

| | |
|---|---|
| could not be priced at all (rug / delisted / no pool) | **60 of 314 — 19%**, each counted −100% |
| **median call closes at** | **0.47×** — the typical call loses **53%** |
| p25 closes at | 0.14× — a quarter lose **86%** |
| calls closing above the call price | **57 of 254 — 22%** |
| calls whose **peak** exceeds 2× | **24%** |

**24% touch a double and 22% end up above water.** The peaks are real and almost entirely
transient — which is the whole finding in one line.

## 6. What I would tell the owner — three rules, one number each

1. **The x's are real; they are not enough.** 24% of calls do touch 2× — but 19% go to zero and the
   median call ends at **0.47×**.
2. **Selling at a target throws the monsters away.** Under a sell-at-2× rule a 58× call pays
   **+100%**, the same as any doubler.
3. **Holding to catch them loses most of all.** −42.3%, and break-even would need **0.73%** of calls
   to close at 58× when the best close in 314 is 6.61×.

## Limits
- **314 of 2,485 calls (13%)**, so these move. The fetch order is balanced across chat × half-year,
  so the prefix is not cherry-picked, but it is 13%.
- **2026 only, inside the ~180-day free-data window.** The 2025 corpus is paywalled (`401`).
- **No fees, slippage, priority fees or MEV**, so every figure above is *optimistic*.
- **"Sell at X" assumes a fill at X.** The owner's own point — that spamming the sell button at a
  target is fast enough — is what makes a touch-based fill defensible rather than fantasy.
- **These are the chats' calls, not the bot's trades.** Separate question, separate P&L.
- **One known 58.69× call is absent** and tested by insertion in §3; it does not flip any rule.
