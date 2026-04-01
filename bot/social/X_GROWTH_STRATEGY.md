# X Growth Strategy — WAGMI Trading Bot

## The Algorithm (What Actually Matters)

### Engagement Signal Weights (from X open-source code)
| Signal | Weight vs Like | What This Means |
|--------|---------------|-----------------|
| Reply-to-reply (conversation) | **150x** | Start conversations, reply to replies on your tweets |
| Retweet | **40x** | Create quote-tweet-worthy content |
| Reply | **27x** | Ask questions, provoke discussion |
| Bookmark | **20x** | Create save-worthy content (data, frameworks, insights) |
| Like | **0.5x** | Nearly worthless. Stop optimizing for likes. |
| Report | **-369x** | Avoid controversy that gets reported |
| Block/Mute | **-74x** | Don't spam, don't be annoying |

**Key insight: One genuine conversation thread is worth more than 300 likes.**

### Reach Killers
- **Links in main tweet** = 30-50% reach penalty (put links in self-reply, 1700% reach increase)
- **3+ hashtags** = 40% penalty
- **Engagement bait** ("like if you agree") = algorithmic penalty
- **Follow/unfollow cycling** = shadowban within 24-48 hours
- **Mass liking/following** = rate limited, shadowban risk
- **Repetitive content** = reduced distribution

### Reach Boosters
- **Threads** = 40-60% more impressions than standalone tweets
- **First 30-60 min engagement velocity** determines everything
- **Text outperforms video** on X (0.48% vs 0.41% engagement rate)
- **X Premium** = 10x average reach boost (essential)
- **Conversations** = algorithm loves reply chains

### TweepCred Score (Hidden Account Quality)
- 0-100 score using PageRank algorithm
- **Critical threshold: 65** — below it, only ~3 tweets/day get distribution
- Factors: follower ratio, engagement quality, interactions with high-score users
- Improve it: engage with larger accounts, maintain good follower/following ratio

---

## Content Pillars (Daily Mix)

### 1. Calls & Market Reads (25%)
High-confidence macro calls that make the TL look like a real trader who HITS. This is what builds reputation fastest.

**Formats:**
- Bold directional calls with specific levels: "$BTC holding 67.2k support. Long here, 69.5k target"
- Bot signal tweets: "9-agent system just flagged $SOL. Regime agent sees momentum shift"
- Agent disagreement reveals: "Trade agent wanted to long X but Critic vetoed — Critic was right"
- Market reads backed by data, not vibes
- **ALWAYS screenshot/save your calls for receipts later**

### 2. Community Coin Bags (25%)
Organic promotion for the coins you're bagworking. The key: weave naturally into broader market analysis, never look like a paid shill.

**Formats:**
- Organic: "$BTC pumping, watching the SOL ecosystem. $COINNAME looking ready for a move with the community catalyst"
- Direct: "Been watching $COINNAME. Community is building, chart setup is clean. Not huge yet but the builders are real"
- Alpha: "Interesting wallet activity around $COINNAME today. Make of that what you will"
- **Rule: Max 2 direct coin posts per day. Rest should be organic mentions in broader context.**

### 3. Engagement Drivers (20%)
Pure impression machines. Drive replies (27x) and conversations (150x).

**Formats:**
- Polls: "Where's $BTC by end of month?" (1.5-3% engagement)
- Hot takes: contrarian views during consensus
- Questions: "What's your best trade this week?"
- "What are you watching today?" — community building
- **ALWAYS end with a question or something people want to respond to**

### 4. Building in Public (15%)
Shows you're legit. Building real tech, not just drawing lines.

**Formats:**
- Feature drops: "Shipped new Overseer agent at 3am. It monitors all other agents."
- Bug stories: "Bot caught a bug that would've cost me. Fixed it."
- Dashboard screenshots — people love seeing the tech behind the calls

### 5. Alpha Drops & Education (10%)
Bookmark-worthy. Positions you as someone who THINKS.

**Formats:**
- Quick frameworks: "How I size positions" (one tweet)
- Data insights: "Ran 500 trades through the system. The edge is in [X]"
- Save longer education for threads (40-60% more impressions)

### 6. Receipts (5%)
Quote-tweet your own calls when they hit.

---

## The Daily Grind (250 → 1000+)

**This is the reality: growth requires DAILY consistency. No days off.**

### Morning Routine (15-20 min)
1. Run `python -m social.cli grind --context "market state"` — generates 8-12 posts
2. Review the plan in `bot/data/social/daily_grind.md`
3. Edit posts to sound like YOU (the AI drafts, you finalize)
4. Post first tweet of the day (market open content)

### Throughout the Day
- Post every 30-60 minutes during active hours
- Reply to 10+ tweets from larger accounts (this is THE growth hack)
- Reply to every reply on YOUR tweets within 2 hours
- Drop community coin mentions naturally in market analysis

### Evening
- Post recap / what you're watching tomorrow
- Queue next morning's first tweet

### Daily Targets
| Metric | Target | Why |
|--------|--------|-----|
| Original tweets | 8-12 | Consistent presence = algorithm trust |
| Replies to others | 10-15 | Profile visits from larger audiences |
| Reply to own replies | All of them | Conversations = 150x algorithm weight |
| Threads per week | 2-3 | 40-60% more impressions |
| Bag mentions | 3-5 | Mix of organic and direct |

### Content Calendar
- **Monday**: Weekly recap + "what I'm watching this week" (sets the tone)
- **Tuesday**: Build update + bag mentions woven into market analysis
- **Wednesday**: Educational thread (one per week minimum)
- **Thursday**: Call day — bold macro calls backed by bot data
- **Friday**: Hot take + weekend prediction + community coin spotlight
- **Saturday**: Thread or deeper analysis (less competition = better reach)
- **Sunday**: Engagement content — polls, questions, community interaction

### Immediate Setup Checklist
- [ ] Pin a thread explaining what you're building (9-agent system, the mission)
- [ ] Bio: clear, specific, memorable. Builder + trader + community.
- [ ] Get X Premium (10x reach, essential — non-negotiable)
- [ ] Add bags: `python -m social.cli bag add TICKER "Name" CHAIN "thesis"`
- [ ] Run first grind: `python -m social.cli grind`
- [ ] Start documenting every call with timestamps (receipts later)
- [ ] Find 20 accounts at 2-10x your size to reply to daily

### Phase 1: Grind (Weeks 1-8, 250→500)
The ugly phase. Nobody's watching yet. Post anyway. Every day.
- 8-12 tweets/day, every day, no exceptions
- 45 min/day reply game on larger accounts
- 1 thread per week minimum
- Build the receipts thread (pin your best calls)
- Community coins woven into every market analysis naturally

### Phase 2: Traction (Weeks 8-16, 500→2,000)
Your calls start hitting. Receipts start stacking. People notice.
- Quote-tweet your own calls when they hit (this is THE move)
- Start a free Telegram/Discord for signal followers
- Weekly X Space ("AI Trading Lab" or similar)
- Engagement group: 10-20 accounts your size, support each other's content
- Community coin promotion becomes more direct as audience trusts you

### Phase 3: Authority (Weeks 16-30, 2,000→5,000+)
Now you have leverage. Monetization opens up.
- Collaborative content with similar-sized accounts
- Dashboard screenshots become regular content
- Consider auto-posting bot signals via X API
- Launch paid tier if free community is engaged
- Community coins: you're now a real KOL for them

---

## Optimal Posting Times (UTC)
| Window | UTC | EST | Priority |
|--------|-----|-----|----------|
| US Market Open | 13:00-17:00 | 8AM-12PM | HIGHEST |
| European Session | 08:00-11:00 | 3AM-6AM | HIGH |
| US Evening | 20:00-23:00 | 3PM-6PM | GOOD (threads) |
| Asian Session | 01:00-04:00 | 8PM-11PM | MODERATE |

**Critical rule:** The first 30-60 minutes after posting determine everything. Post when you can engage with replies.

---

## Growth Benchmarks
| Milestone | Timeline | Daily Effort |
|-----------|----------|-------------|
| 0 → 500 | ~8 weeks | 1-2 hours/day |
| 500 → 1,000 | ~4 weeks | 1-2 hours/day |
| 1,000 → 5,000 | 2-4 months | 1-2 hours/day |
| 5,000 → 10,000 | 3-5 months | 1-2 hours/day |

---

## Voice Rules
- Always use specific numbers ("up 12%", not "up a lot")
- Short paragraphs, one idea per line
- Line breaks for readability
- Be opinionated — CT rewards confidence
- Show losses too — builds more trust than only showing wins
- No corporate language
- Occasional profanity is fine (reads as authentic)
- NO AI cliches: "let's dive in", "buckle up", "here's the thing"

---

## Anti-Bot Detection
The content engine has these safeguards:
1. **Banned phrase filter**: 30+ known AI-generation tells
2. **Voice profile training**: Match YOUR actual writing style
3. **Humanize filter**: Strip AI patterns from every generated tweet
4. **Human-in-the-loop**: You edit and approve everything before posting
5. **Pillar rotation**: Prevents repetitive content patterns

---

## Your Competitive Advantage
Most of crypto Twitter is people drawing lines on charts. You have:
- A working multi-agent AI trading system
- Real code, real architecture, real results
- A technical moat that's hard to replicate
- The "building in public" narrative people want to follow
- Data-driven content nobody else can produce

**Lean into what makes you different. The AI angle IS the growth hack.**
