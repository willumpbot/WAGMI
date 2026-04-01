# X/Twitter Algorithm Research -- Complete Technical Breakdown

**Last Updated: March 2026**
**Sources: Open-sourced algorithm code (2023 + Jan 2026 xAI release), Buffer (18.8M posts analyzed), Sprout Social, Social Media Today, growth practitioner data**

---

## 1. ENGAGEMENT SIGNAL WEIGHTS (From Source Code)

The algorithm scores every tweet using weighted engagement signals. These are the confirmed multipliers from the open-sourced code:

### Primary Scoring Formula

| Signal | Weight | Relative to Like |
|--------|--------|-------------------|
| Reply that gets author reply back | +75.0 | **150x** a like |
| Retweet/Repost | +20.0 | **40x** a like |
| Reply (direct) | +13.5 | **27x** a like |
| Profile click (from tweet) | +12.0 | **24x** a like |
| Link click | +11.0 | **22x** a like |
| Bookmark | +10.0 | **20x** a like |
| Like/Favorite | +0.5 | **1x** (baseline) |

### Negative Signals

| Signal | Weight | Effect |
|--------|--------|--------|
| Tweet report (spam/abuse) | **-369x** | Catastrophic -- essentially kills distribution |
| Block/Mute/"Show less" | **-74x** | Severe suppression |
| "Not interested" click | Strong negative | Reduces future distribution to similar users |
| Quick scroll-past (low dwell) | Negative | Signals irrelevance |

### Key Insight
**A single conversation (reply + author reply-back) is worth 150x more than a like.** This means sparking and participating in conversations is BY FAR the highest-leverage activity on X. Likes are nearly worthless algorithmically.

---

## 2. FOR YOU FEED MECHANICS

### Three-Stage Pipeline

```
Stage 1: CANDIDATE SOURCING
  - Pulls ~1,500 candidate tweets from 500M+ daily tweets
  - 50% from accounts you follow (in-network)
  - 50% from accounts you don't follow (out-of-network)
  - Sources: Social graph, topic interests, engagement history

Stage 2: NEURAL NETWORK RANKING (Heavy Ranker)
  - Grok-powered transformer model (since Jan 2026)
  - Scores each candidate across 15 engagement types
  - Predicts: Will this user like/reply/retweet/bookmark this?
  - Combines predictions using the weighted formula above

Stage 3: HEURISTICS & FILTERING
  - Author diversity (no flooding from one account)
  - Content type mixing (text, video, images)
  - Recency decay
  - Anti-spam / quality filters
```

### How a Tweet Breaks Into For You (Out-of-Network)

1. **First 30-60 minutes are critical** -- the algorithm watches engagement velocity
2. Tweet gets shown to a small % of your followers first
3. If engagement rate exceeds threshold, it enters candidate pool for non-followers
4. Strong early signals (replies > bookmarks > retweets > likes) push it wider
5. Each expansion round, the algorithm re-evaluates engagement rate
6. A tweet that gets 10 replies in 15 minutes dramatically outperforms 10 replies over 24 hours

### What Kills For You Reach

- Low engagement velocity in first hour
- High "Not interested" / scroll-past rate
- Reports or blocks from viewers
- External links (30-50% penalty for Premium, near-100% for free accounts)
- Low TweepCred score (see section 8)
- Spam-like patterns (repetitive content, excessive hashtags)

---

## 3. REACH KILLERS -- Specific Actions That Tank Impressions

### Confirmed Reach Destroyers

| Action | Impact | Severity |
|--------|--------|----------|
| External links (free account) | Zero median engagement since March 2025 | CRITICAL |
| External links (Premium) | 30-50% reach reduction | HIGH |
| 3+ hashtags per tweet | 40% penalty, 17% engagement drop | HIGH |
| Tweet reports from viewers | -369x multiplier per report | CATASTROPHIC |
| Blocks/mutes from viewers | -74x multiplier per action | SEVERE |
| Follow/unfollow spam | Shadowban within 24-48 hours | CRITICAL |
| Bot-like behavior (mass actions) | Shadowban trigger | CRITICAL |
| Posting same links repeatedly | Spam flag | HIGH |
| Consistently negative/combative tone | Deboosted even with high engagement | MEDIUM |
| Mass unfollowing by others | 3-month shadowban possible | HIGH |
| Low dwell time on your content | Algorithmic suppression | MEDIUM |
| Posting during dead hours | Missed critical velocity window | MEDIUM |

### The Link Problem -- Workaround

**Never put links in the main tweet body.** Instead:
1. Write valuable native content in the tweet
2. Drop the link in the first reply
3. A/B testing showed **1,700% reach increase** when removing a link from an identical tweet

### Engagement Bait

The algorithm now detects engagement bait patterns ("Like if you agree", "RT to win"). Grok's semantic analysis can identify these patterns and suppress them.

---

## 4. OPTIMAL POSTING PATTERNS

### Best Times to Post (All Times in EST/ET)

| Day | Peak Window | Secondary Window |
|-----|-------------|------------------|
| Monday | 9-11 AM | 12-2 PM |
| Tuesday | 9-11 AM | 12-2 PM |
| Wednesday | 9-11 AM | 12-2 PM |
| Thursday | 9-11 AM | 12-2 PM |
| Friday | 9-11 AM | 12-1 PM |
| Saturday | 10 AM-12 PM | Lower overall |
| Sunday | 10 AM-12 PM | Lower overall |

**Best overall days:** Tuesday, Wednesday (highest engagement)
**Worst day:** Sunday

### Posting Frequency

| Account Size | Recommended Frequency | Notes |
|-------------|----------------------|-------|
| 0-1,000 followers | 3-5 tweets/day | Focus more on replies (70/30 rule) |
| 1,000-5,000 | 5-10 tweets/day | Mix of original + replies |
| 5,000-10,000 | 5-15 tweets/day | Scale up original content |
| 10,000+ | 10-15 tweets/day | Consistent cadence matters most |

### Critical Timing Rules

- **First 18 minutes** = Most engagement happens here
- **First 30-60 minutes** = Algorithm decides whether to amplify
- Space tweets 2-3 hours apart to catch different audience segments
- Reply to your own replies within 1 hour (maximizes the 75x conversation bonus)
- Replying within 15 minutes to others gets 3-5x more visibility than replying after 2 hours

---

## 5. GROWTH VELOCITY BENCHMARKS

### Realistic Timelines (With Consistent 2-3 hrs/day Effort)

```
PHASE 1: 0 --> 500 followers (Month 1)
  - Building content library
  - Finding voice and niche
  - 70%+ time on replies to bigger accounts
  - Expect: 10-20 followers/day

PHASE 2: 500 --> 1,000 followers (Month 2)
  - Momentum building
  - First mini-viral moments
  - Strategic reply engagement compounding
  - Expect: 15-30 followers/day

PHASE 3: 1,000 --> 5,000 followers (Month 3-5)
  - Compound effects kicking in
  - Viral moments become more likely
  - Start getting replies on YOUR tweets
  - Expect: 30-100 followers/day

PHASE 4: 5,000 --> 10,000 followers (Month 5-8)
  - Authority established in niche
  - Organic discovery via For You
  - Other accounts start quoting you
  - Expect: 50-200 followers/day
```

### Growth Accelerators

- **X Premium**: 10x average reach boost -- ROI is massive for growth
- **Niche focus**: Accounts with clear positioning grow 3-5x faster
- **Reply strategy**: One good reply on a viral tweet > five original posts
- **Threads**: 3-5 tweet threads get 40-60% more total impressions than equivalent standalones
- **Consistency**: Missing days resets algorithm familiarity with your account

### What Stalls Growth

- Posting without engaging (broadcasting mode)
- Too broad / no niche identity
- External links in main tweets
- Inconsistent posting schedule
- Following/unfollowing for growth (triggers shadowban)

---

## 6. CONTENT FORMAT PERFORMANCE

### Engagement Rates by Format (2025-2026 Data)

| Format | Avg Engagement Rate | Algorithm Boost | Best For |
|--------|-------------------|-----------------|----------|
| Text-only | 0.48% | Baseline | Hot takes, insights, questions |
| Image/Photo | 0.41% | Slight boost | Charts, infographics, screenshots |
| Video (native) | 0.41% avg, up to 10x text | **Strong boost** | Tutorials, commentary, clips |
| Polls | 1.5-3.0% | High engagement | Audience interaction, debate |
| Links | 0.13% (0% for free) | **Severe penalty** | AVOID in main tweet |
| Threads (3-5 tweets) | 3x single tweet | Dwell time boost | Deep analysis, education |
| Quote tweets | Moderate | Good distribution | Commentary on trending topics |

### Key Findings

1. **X is the ONLY major platform where text beats video** on raw engagement rate (0.48% vs 0.41%)
2. **Native video gets 10x distribution** vs text-only through algorithmic boosting
3. **Polls generate 3-6x the engagement** of regular posts
4. **Links are poison** for free accounts (0% median engagement)
5. **Threads generate 3x engagement** of equivalent standalone tweets
6. **Images with charts/data** perform 40%+ better than plain images

### Optimal Content Mix (Weekly)

```
Monday:    Text insight/hot take (AM) + Reply engagement (PM)
Tuesday:   Thread (3-5 tweets, educational) + Text hot take
Wednesday: Poll or question + Text insights
Thursday:  Image/chart post + Thread
Friday:    Text recap/weekly insight + engagement
Weekend:   Light posting, heavy reply engagement on bigger accounts
```

---

## 7. REPLY STRATEGY -- The Fastest Growth Lever

### The 70/30 Rule

**Spend 70% of your X time on engagement (replies, discussions) and 30% creating original content.**

### How Reply Growth Works

1. Reply to a big account's tweet (2-10x your follower count)
2. Their entire audience sees your reply (free distribution)
3. If your reply is good, people click your profile
4. Profile visits convert to followers at 5-15% rate
5. Compound: more followers = more engagement on YOUR tweets = more algorithmic distribution

### Reply Strategy Execution

| Action | Frequency | Target |
|--------|-----------|--------|
| Reply to bigger accounts | 10-20x daily | Accounts with 2-10x your followers |
| Reply within 15 min of their post | Always | Time-sensitive -- first replies get most visibility |
| Reply to replies on YOUR tweets | Every reply | Triggers 75x conversation bonus |
| Reply with substance (not "great post") | Always | Add a unique insight, contrarian take, or data point |
| Target 10-15 accounts consistently | Daily | Build recognition with their audience |

### Verified Results

- One creator grew 500 to 12,000 followers in 6 months using 70/30 strategy
- Reply threads gain 25% more followers than original posts
- Top performers spend 30+ minutes daily in bigger accounts' comment sections
- Each quality reply generates 500-1,000+ monthly followers when done at scale

### What Makes a Good Reply

- **Add new information** the original post didn't cover
- **Share a personal experience** that validates or challenges the point
- **Ask a thoughtful question** that sparks further discussion
- **Provide data or evidence** (screenshots, charts)
- **Be early** -- first 15 minutes is 3-5x more effective
- **NEVER**: "Great post!", "This!", "Follow me for more" (spam signals)

---

## 8. TWEEPCRED -- The Account Quality Score

### What Is It?

Every X account has a hidden TweepCred score (0-100) calculated using a weighted PageRank approach. This score determines your baseline distribution ceiling.

### Score Ranges

| Score Range | Classification | Distribution Impact |
|-------------|---------------|-------------------|
| 0-30 | New/Flagged | Heavily limited, near-invisible |
| 30-55 | Normal small-mid | Standard distribution |
| 55-75 | Healthy & growing | Enhanced distribution |
| 75-90 | Strong reputation | 20-50x distribution boost |
| 90-100 | Elite (extremely rare) | Maximum algorithmic advantage |

### Critical Threshold: 65

- **Below 65**: Only 3 of your tweets are considered for algorithmic distribution
- **Above 65**: ALL your tweets are eligible for distribution

### Factors That Increase TweepCred

| Factor | Impact | How to Improve |
|--------|--------|---------------|
| Account age | Medium | Time (can't hack this) |
| Follower-to-following ratio | High | Follow fewer, earn more followers |
| Engagement quality (replies received) | Very High | Create conversation-worthy content |
| Interactions with high-TweepCred users | High | Reply to established accounts |
| Consistent posting history | Medium | Don't go dark for weeks |
| Low report/block rate | Very High | Avoid controversy that triggers reports |
| Profile completeness | Low-Medium | Bio, avatar, header, pinned tweet |
| X Premium subscription | High | Direct score boost |

### Factors That Decrease TweepCred

- High following-to-follower ratio (looks like spam)
- Getting blocked/muted frequently
- Receiving reports
- Sudden follower drops (mass unfollows)
- Bot-like behavior patterns
- Inactivity periods
- Low engagement rate on posts

### New Account Challenge

New accounts start at -128 TweepCred and need at least +17 to appear in feeds at all. This is the "new account penalty" -- it typically takes 2-4 weeks of consistent, quality activity to escape.

---

## 9. SHADOW BAN TRIGGERS

### Types of Shadow Bans

| Type | Effect | Detection |
|------|--------|-----------|
| Search ban | Tweets don't appear in search | Search your @handle while logged out |
| Reply deboosting | Replies hidden behind "Show more" | Check if replies are visible to non-followers |
| Ghost ban | Account invisible to non-followers | Ask someone who doesn't follow you to find you |
| Feed suppression | Posts excluded from For You | Sudden 70-90% impression drop |

### Confirmed Trigger Actions

**CRITICAL (immediate shadowban risk):**
- Follow/unfollow cycling (detected within 24-48 hours)
- Mass liking (100+ likes in rapid succession)
- Mass following (50+ follows in short period)
- Using unauthorized automation tools
- Posting identical content repeatedly
- Multiple accounts coordinating engagement

**HIGH RISK (can trigger after accumulation):**
- Posting same links/domains repeatedly
- Getting multiple reports in short period
- High block rate from people you interact with
- Aggressive DM behavior
- Using banned/flagged link domains
- Rapidly deleting and reposting tweets

**MODERATE RISK:**
- Excessive hashtag use (5+)
- Consistently negative/combative tone
- Mass unfollowing by your followers (signals quality decline)
- Sudden behavior changes (dormant account suddenly posting 50x/day)

### Shadowban Duration

- Typical duration: 24-72 hours for first offense
- Repeat offenses: up to 3 months
- Mass unfollow trigger: up to 3 months
- Recovery: Stop all flagged behavior, post quality content, wait

### Detection Method

1. Ask a non-follower to search for your @handle
2. Check if your replies appear under other people's tweets (logged out)
3. Monitor impressions -- a 70-90% overnight drop = likely shadowban
4. Use third-party tools (search "Twitter shadowban test")

### Recovery Protocol

1. **Stop all flagged behavior immediately**
2. Reduce posting to 1-2 high-quality tweets per day
3. Focus on genuine engagement (quality replies)
4. Do NOT use any automation or third-party tools
5. Wait 48-72 hours minimum
6. Gradually resume normal activity
7. If persistent after 7 days, submit appeal through X Help Center

---

## 10. THREAD MECHANICS

### Do Threads Get Boosted?

**Yes.** Threads outperform standalone tweets by significant margins:
- 3-5 tweet threads get **40-60% more total impressions** than 5 individual standalone tweets
- Thread posts generate **3x more total engagement** than equivalent standalone tweets
- Each addition to a thread bumps the original tweet's score (extends algorithmic life)
- Dwell time on threads is higher (people stop scrolling to read), which is a strong positive signal

### Optimal Thread Structure

```
Tweet 1 (HOOK):
  - Bold claim, surprising stat, or contrarian take
  - Must stand alone as interesting
  - This tweet gets 80% of your thread's total impressions
  - Include "Thread" or the thread emoji to signal more content

Tweet 2-4 (BODY):
  - Each tweet should deliver ONE clear point
  - Use numbers/data when possible
  - Include images/charts if relevant (especially tweet 2-3)
  - Each tweet should be readable standalone

Tweet 5 (CLOSER):
  - Summarize the key takeaway
  - Include a call-to-action (question, retweet request)
  - Link to relevant content in REPLY to this tweet (not in it)
```

### Thread Best Practices

| Practice | Rationale |
|----------|-----------|
| Keep to 3-8 tweets | Longer threads lose readers, shorter lack depth |
| Post 1-2 threads per week | More = audience fatigue |
| First tweet must hook in 2 seconds | 80% of impressions happen on tweet 1 |
| Add images to tweets 2-3 | Breaks up text, increases dwell time |
| End with a question | Drives replies (highest-weight signal) |
| Self-reply within 1 hour | Triggers 75x conversation bonus |
| Never put links in thread tweets | Use reply to last tweet for links |
| Keep each tweet under 2:20 of read time | Algorithm preference |

### Thread Timing

- Post threads during peak hours (9-11 AM EST Tue-Wed)
- The first tweet's engagement velocity determines the entire thread's distribution
- Space your thread tweets 30-60 seconds apart (don't dump all at once)

---

## 11. PREMIUM SUBSCRIPTION -- ROI ANALYSIS

### Algorithmic Advantages

| Feature | Free Account | Premium ($8/mo) | Premium+ ($16/mo) |
|---------|-------------|-----------------|-------------------|
| Feed reach multiplier | 1x | **4x in-network, 2x out** | **Higher** |
| Average reach boost | Baseline | **10x average** | **15x average** |
| Reply visibility | Standard | **Prioritized in threads** | **Top of threads** |
| Link posting viability | Dead (0% median) | Reduced but viable | Better |
| Edit tweets | No | Yes | Yes |
| Revenue sharing eligible | No | Yes (500+ followers, 5M+ impressions) | Yes |
| Analytics depth | Basic | Enhanced | Full |

### Is Premium Worth It For Growth?

**Yes, unequivocally.** The 10x average reach multiplier alone makes Premium the highest-ROI investment for X growth. Without Premium, link posts are invisible, replies are deprioritized, and your TweepCred ceiling is lower.

---

## 12. ALGORITHM ARCHITECTURE (Jan 2026 Update)

### Grok-Powered System

In January 2026, X open-sourced its new algorithm at github.com/xai-org/x-algorithm:

```
SYSTEM COMPONENTS:
  1. Home Mixer    -- Orchestration layer
  2. Thunder       -- In-memory post storage
  3. Phoenix       -- Grok-based retrieval & ranking
  4. Candidate Pipeline -- Framework for post selection

KEY CHANGE: All hand-engineered features eliminated.
Grok's transformer model now reads every post and watches
every video (100M+ per day) to match users with content.
```

### What This Means In Practice

- The algorithm is now MORE semantic -- it understands content meaning, not just engagement metrics
- Grok can detect engagement bait, spam patterns, and low-quality content
- Content relevance to the viewer's interests matters more than ever
- The engagement weight multipliers still apply but are inputs to the transformer, not the final scoring formula

---

## 13. ACTIONABLE PLAYBOOK -- Daily Execution Plan

### Morning Routine (30 min)

1. Check trending topics in your niche
2. Post 1 high-quality original tweet (text, hot take, or insight)
3. Reply to 5-7 bigger accounts' recent posts (within 15 min of their post)
4. Respond to all overnight replies on your content

### Midday (20 min)

1. Post 1 more original tweet or continue a thread
2. Reply to 3-5 more accounts
3. Engage with replies on your morning post (triggers 75x bonus)
4. Share 1 quote tweet with your take on a trending topic

### Evening (20 min)

1. Post 1 more tweet (question or poll for overnight engagement)
2. Reply to 5 more accounts
3. Engage with all replies from the day
4. Plan tomorrow's thread topic

### Weekly

- Monday: Launch 1 thread (3-5 tweets)
- Wednesday: Post 1 poll
- Friday: Recap/hot take thread
- Daily: 3-5 original tweets + 10-20 quality replies

---

## 14. METRICS TO TRACK

### Leading Indicators (Track Daily)

| Metric | Target | Why It Matters |
|--------|--------|----------------|
| Reply rate | > 2% of impressions | Highest-weight signal |
| Bookmark rate | > 0.5% | Strong quality signal |
| Profile visits | Growing week-over-week | Conversion funnel |
| Follower growth rate | Per benchmarks above | North star metric |
| Avg impressions per tweet | Growing | Algorithm favor |

### Lagging Indicators (Track Weekly)

| Metric | Target | Why It Matters |
|--------|--------|----------------|
| Follower-to-following ratio | > 2:1 ideally | TweepCred factor |
| Engagement rate | > 1% | Health check |
| Top tweet impressions | Growing | Viral potential |
| Reply thread depth | Avg > 2 replies | Conversation quality |

---

## Sources

- [PostEverywhere - How the X/Twitter Algorithm Works in 2026 (Source Code)](https://posteverywhere.ai/blog/how-the-x-twitter-algorithm-works)
- [Sprout Social - How the Twitter Algorithm Works in 2026](https://sproutsocial.com/insights/twitter-algorithm/)
- [Tweet Archivist - Complete Technical Breakdown](https://www.tweetarchivist.com/how-twitter-algorithm-works-2025)
- [Tweet Archivist - Twitter Algorithm Explained](https://www.tweetarchivist.com/twitter-algorithm-explained-2025)
- [OpenTweet - Complete Breakdown 2026](https://opentweet.io/blog/how-twitter-x-algorithm-works-2026)
- [SocialBee - Understanding the X Algorithm 2026](https://socialbee.com/blog/twitter-algorithm/)
- [Typefully - X Algorithm Update Jan 2026](https://typefully.com/blog/x-algorithm-open-source)
- [Social Media Today - X Algorithm Ranking Factors](https://www.socialmediatoday.com/news/x-formerly-twitter-open-source-algorithm-ranking-factors/759702/)
- [Circleboom - TweepCred, Shadow Hierarchy, Dwell Time](https://blog-content.circleboom.com/the-hidden-x-algorithm-tweepcred-shadow-hierarchy-dwell-time-and-the-real-rules-of-visibility/)
- [Circleboom - TweepCred Score](https://circleboom.com/blog/tweepcred-what-it-is-why-it-matters-and-how-to-increase-your-score-on-x-twitter/)
- [Buffer - Best Time to Post (1M Posts Analyzed)](https://buffer.com/resources/best-time-to-post-on-twitter-x/)
- [Buffer - Best Content Format (45M+ Posts Analyzed)](https://buffer.com/resources/data-best-content-format-social-media/)
- [Buffer - State of Social Media Engagement 2026 (52M+ Posts)](https://buffer.com/resources/state-of-social-media-engagement-2026/)
- [Buffer - Links on X Performance](https://buffer.com/resources/links-on-x/)
- [PostEverywhere - Best Time to Schedule X Posts (700K Posts)](https://posteverywhere.ai/blog/best-time-to-schedule-x-posts)
- [Tweet Archivist - How Often to Post on Twitter](https://www.tweetarchivist.com/how-often-to-post-on-twitter-2025)
- [Tweet Archivist - Posting Frequency Guide 2026](https://www.tweetarchivist.com/twitter-posting-frequency-guide-2025)
- [Sprout Social - Best Times to Post on Twitter](https://sproutsocial.com/insights/best-times-to-post-on-twitter/)
- [Enrich Labs - Twitter/X Benchmarks 2026](https://www.enrichlabs.ai/blog/twitter-x-benchmarks-2025)
- [WebFX - X Marketing Benchmarks 2026](https://www.webfx.com/blog/social-media/x-twitter-marketing-benchmarks/)
- [Adilo - X Engagement Rate Chart](https://adilo.com/blog/x-engagement-rate-chart-2025/)
- [Teract - 70/30 Reply Strategy 2026](https://www.teract.ai/resources/grow-twitter-following-2026)
- [Tweet Archivist - Twitter Premium Worth It 2026](https://www.tweetarchivist.com/twitter-premium-worth-it-2025)
- [Social Media Today - X Premium Reach Benefits](https://www.socialmediatoday.com/news/report-shows-paying-for-x-twitter-premkum-has-significant-reach-benefits/801881/)
- [OpenTweet - Twitter Shadowban Guide 2026](https://opentweet.io/blog/twitter-shadowban-check-fix-avoid-2026)
- [Tweet Archivist - Shadowban Complete Guide](https://www.tweetarchivist.com/twitter-shadowban-complete-guide-2025)
- [GitHub - xai-org/x-algorithm (Jan 2026)](https://github.com/xai-org/x-algorithm)
- [PiunikaWeb - X Algorithm Open Source Tips 2026](https://piunikaweb.com/2026/01/20/x-algorithm-open-source-tips-grow-reach-2026/)
- [X Engineering - Algorithm Open Source Announcement](https://x.com/XEng/status/2013471689087086804)
- [Social Media Today - X Testing New Link Handling](https://www.socialmediatoday.com/news/x-formerly-twitter-testing-links-in-app-link-post-penalties/803176/)
- [FounderBrands - 0 to 1000 Followers Strategy](https://www.founderbrands.io/how-to-grow-from-0-to-1000-x-twitter-followers-fast-complete-growth-strategy)
- [HasHMeta - Major Twitter Algorithm Changes 2025](https://hashmeta.com/insights/twitter-algorithm-changes-2025)
- [Radaar - Hidden X Algorithm Secrets 2025](https://www.radaar.io/resources-121/blog-388/are-you-ready-to-discover-the-hidden-x-algorithm-secrets-behind-tweepcred-shadow-hierarchy-and-dwell-time-in-2025-15361/)
- [GrowKaito - How to Grow on Crypto Twitter 2025](https://growkaito.com/blog/how-to-grow-on-crypto-twitter)
- [GitHub - twitter/the-algorithm (Original 2023)](https://github.com/twitter/the-algorithm)
