# Marketing Launch Materials

This file contains ready-to-post marketing content for launching the SaaS Pricing Intelligence API.

## Product Hunt Launch Post

**Title:** SaaS Pricing Intelligence API — Real-time pricing data for 500+ SaaS products

**Tagline:** Build competitive pricing tools with comprehensive market data

**Description:**
Pricing intelligence API that gives you real-time access to pricing tiers, historical trends, and AI-powered recommendations for 500+ SaaS products across 97 categories. Perfect for:
- Competitive analysis dashboards
- M&A due diligence
- Revenue optimization
- Sales enablement tools

**Features:**
- 500+ SaaS products tracked
- 97 categories covered
- REST API with simple integration
- Historical pricing trends
- AI-powered pricing recommendations
- Competitor benchmarking
- Revenue estimation

**Pricing:**
- Free: 100 requests/month
- Startup: $49/mo (1,000 requests)
- Growth: $199/mo (unlimited)
- Enterprise: Custom

**Maker's Comment:**
I built this to solve a persistent problem — SaaS pricing data is scattered and hard to aggregate. Now you can build pricing tools without spending hours manually collecting data.

**Link:** [Your deployed URL]

---

## Indie Hackers Launch Post

**Title:** I built an API that tracks pricing for 500+ SaaS products — here's what I learned

**Content:**

Hey IH,

I've been working on a problem that's been nagging me for a while: there's no easy way to get comprehensive SaaS pricing data programmatically.

Most solutions either:
- Cost thousands per month
- Require manual research
- Are outdated within weeks

So I built the SaaS Pricing Intelligence API — a simple REST API that gives you:
- Pricing tiers for 500+ products across 97 categories
- Historical trend data
- AI-powered pricing recommendations
- Competitor benchmarking
- Revenue estimation

**The Tech:**
- Python/Flask backend
- 500+ products in database
- Stripe for payments

**The Ask:**
Would love feedback from the community. Is this useful? What would make it more valuable? Any pricing concerns?

Currently at $0 MRR, but that's the goal!

Link: [Your deployed URL]

---

## Reddit r/startups Post

**Title:** Built an API that aggregates pricing data for 500+ SaaS products — looking for feedback

**Body:**

Hey everyone,

I've been working on a side project that's now at a point where I could use some feedback.

**The Problem:**
I kept running into the same issue — when doing competitive analysis for SaaS products, pricing data is everywhere and nowhere. You'd have to manually visit 50+ websites to get a sense of the market.

**The Solution:**
SaaS Pricing Intelligence API — a simple REST endpoint that returns pricing tiers, historical data, and AI recommendations for 500+ products across 97 categories.

Example use cases:
- Building competitive analysis dashboards
- M&A due diligence research
- Pricing optimization tools
- Sales enablement

**What I'd Love Feedback On:**
- Is this useful as-is, or is the dataset too limited?
- Would you pay for this? What's the right price point?
- Any features you'd want to see?

Demo: [Your deployed URL]
API Docs: [Your deployed URL]/api/status

Thanks in advance for any thoughts!

---

## Reddit r/SaaS Post

**Title:** I made a tool to help with SaaS pricing research — would love your thoughts

**Body:**

Fellow SaaS builders,

Quick question for those of you who price SaaS products — how do you research competitor pricing?

I used to spend hours on this, so I built a tool to automate it.

**SaaS Pricing Intelligence API:**
- Tracks 500+ products across 97 categories
- Historical pricing data
- AI recommendations for your own pricing
- Competitor benchmarking
- Revenue estimation

**Example query:**
```
GET /api/pricing/slack
```
Returns all Slack pricing tiers, from free to enterprise.

**What I'm trying to figure out:**
- Is this useful for your pricing decisions?
- What would make it more valuable?
- What would you pay?

Free tier available to test: [Your deployed URL]

Thanks!

---

## Twitter/X Post (for testing virality)

**One post:**
> Built an API that knows what 500+ SaaS products charge 💰
>
> Slack: $8.75-$15/user
> Notion: $10-$20/user
> Figma: $0-$75/user
>
> Perfect for competitive analysis, M&A due diligence, or pricing your own SaaS.
>
> Free tier available 👇
> [link]

---

## Next Steps

After deployment is complete:

1. **Product Hunt**: Submit at [producthunt.com/post](https://www.producthunt.com/post)
2. **Indie Hackers**: Post in the "Show" category
3. **Reddit**: Post to r/startups and r/SaaS (different angles)
4. **Twitter**: Post and engage with responses
5. **HN**: If relevant, post to Hacker News

**Metrics to track:**
- Signups (via localStorage or Stripe)
- API usage (via /api/status)
- Traffic sources (UTM parameters)
- Conversion rate (free → paid)
