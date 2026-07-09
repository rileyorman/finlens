# FinLens Roadmap Addendum — Curriculum-Driven & Commercial Expansion

## Moat Thesis (June 2026; sharpened 2026-07-09)

**The canonical statement of the commercial thesis lives in CLAUDE.md
("Commercial Thesis — The Corpus Flywheel"). This section is the roadmap-facing
framing; on any conflict, CLAUDE.md wins.**

The opportunity is real and present: SEDAR+ is PDF-only with no XBRL, so **no
machine-readable, validated Canadian IFRS fundamentals dataset exists.** The Data
Integrity Engine is not a feature — it is the machine that builds that dataset
and keeps it trustworthy.

**What is true today (stated honestly):** the validated corpus is wide-and-thin
— ~15 filers across 6 sector profiles, most shapes anchored one filer deep. That
is an *embryo, not a moat yet* (Riley's own framing). What is already genuinely
scarce is not the data volume but the **adjudication casebook** — CB-009→024,
real analyst judgment encoded as machine-checkable rules with reasoning attached.
Data is re-scrapable; that judgment history is not.

**How it becomes a moat (the compounding engine):** the corpus flywheel — usage
drives ingestion. When a client searches a company, an agent fetches the filing
once, FinLens analyzes it, and it joins the validated corpus; the more clients
search, the more robust the corpus (data network effect). Agent-fetch has
empirically worked on issuer IR pages; the hand-downloaded campaign is the
PRE-commercial bootstrap, NOT the ceiling — post-launch the corpus scales with
demand, not with hands. Full mechanism + caveats in CLAUDE.md.

Three compounding layers:
1. **Error-correction flywheel** — engine findings feed extraction improvements (aliases, derivations, sector rules); every filing processed makes the next more accurate. The JSONL log is the embryo of this asset.
2. **Data-as-product (future, coverage-gated)** — once Canadian coverage matures via the usage flywheel, the validated fundamentals API is sellable to Canadian fund managers, fintechs, and academics independently of the app. NOT sellable at today's 15-filer breadth — this layer is a destination, not a current state.
3. **Trust layer as brand** — "every number validated, every correction logged, audit trail shown." No retail competitor holds this positioning; it is the value-investor sensibility applied to the product itself. The Integrity Engine is also what makes the flywheel trustworthy at scale (human review only on flagged exceptions) — so the moat work and the commercial product are one bet, not two.

Strategic implication: the fetch campaign, rule tuning, and SEDAR+ extraction layer ARE the moat construction. No sequence change — only framing.

---

> A working document. Two parts: (1) the five features the 20-hour curriculum directly demands, written as buildable specs; (2) commercial-value features organized by category and pricing tier, designed to drive conversion, retention, and the $49–$999/month tier ladder.

---

## Critical Pre-Roadmap Finding (Jun 2 2026)

**The EDGAR and TTM analysis paths deliver only structured financial data to
the analyzer — no MD&A, no Risk Factors, no footnotes, no filing prose.**
Only the PDF Upload path passes the full filing text to Claude.

### What was discovered

While verifying prompt caching (commits `3432f33` + `e4a3af2`), empirical testing
showed:

- **TTM Re-Analyse path:** caches ~2,000 tokens (system prompt only). The
  "filing context" being passed is yfinance/FMP-derived structured financials,
  not filing prose.
- **EDGAR "Load Selected Filing" path:** UI text reads "Fetch structured 10-K
  financial statement data directly from SEC XBRL filings" — this path is
  XBRL-only. XBRL contains financial statement tables, NOT MD&A or Risk Factors.
  Confirmed by the dropdown returning only 1995-2002 filings (XBRL was
  mandated in 2009, so the fetcher only finds filings that pre-date the
  modern XBRL-required era — a separate bug indicating sort order or query
  filter issues).
- **PDF Upload path:** parses the full filing via pdfplumber, delivers
  ~30,000-60,000 tokens to the analyzer including MD&A, Risk Factors, and
  footnotes. This is the only path that exercises FinLens's full analytical
  capability.

### Why this matters

1. **Analysis quality on non-PDF paths is structurally limited.** Claude is
   reasoning from financial summaries plus general knowledge, not from the
   actual filing. For household names like AAPL, output looks coherent because
   Claude knows the business. For less-covered names — exactly the names a
   paying user needs help with — analysis quality will be unreliable in ways
   the user can't detect.
2. **The pricing tier strategy assumes Quick Analysis is genuinely useful.**
   At ~2k tokens of context, it isn't — it's essentially a yfinance dashboard
   with Claude commentary. Free-tier users may churn before converting; paid
   users will be forced into manual PDF uploads.
3. **The MD&A Sentiment feature (Call 5) is non-functional on EDGAR and TTM
   paths.** The "MD&A Sentiment not available for Quick Analysis" banner is
   the UI acknowledging this, but the underlying issue affects all signal
   quality.
4. **Filing Diff Viewer (roadmap feature #3, the $199 tier anchor) cannot be
   built on the current data layer.** Diffing requires full filing prose.
   Building this feature depends on first building a proper HTML/text
   filing fetcher.
5. **Prompt caching's cost savings are blunted.** The caching infrastructure
   shipped today (commits `3432f33`+ `e4a3af2`) works correctly but only
   delivers its full 60-90% savings on the PDF Upload path. The other paths
   cache only the system prompt.

### What needs to happen

This is now the highest-priority pre-feature work item. Before any of the 10
features in the build order below, the data layer needs:

1. **A proper filing fetcher** that pulls SEC primary HTML documents (the
   `.htm` file in each filing's index, not the XBRL summary). The existing
   `modules/edgar_fetcher.py` has HTML scraping code that may not be wired
   into the user flow — investigation needed.
2. **A SEDAR+ equivalent** for Canadian filings (HTML or PDF parse).
3. **A filesystem cache** for parsed filing text at
   `library/filings/{ticker}_{period}.txt` to avoid re-fetching on every
   re-analyse.
4. **Harmonization** so TTM, EDGAR, and Upload paths all build their
   `filing_context` from the same canonical full-filing source.
5. **Separate bug:** fix the EDGAR filing dropdown to return recent filings
   (currently returns 1995-2002 only, suggesting sort-order or date-filter
   bug in `get_recent_filings()`).

### Estimated effort

~1-2 day Codex effort. Requires careful design (sequence, caching layer,
backward-compat with existing TTM/Upload code paths). Unblocks Filing Diff
Viewer, MD&A sentiment, and a meaningful upgrade in Quick Analysis quality.

### Status

**Open. Top priority for Sunday Step 7 strategic review** — the fresh Opus
session should determine whether this jumps ahead of Catalyst Calendar
(currently feature #2 in build order) and how it interacts with tier strategy.

---

## Part I — The Five Curriculum-Driven Features

These are the features the 20-hour curriculum surfaces as gaps. Each chapter's exercise is essentially a spec for what FinLens should do — these are the five that pay back the highest commercial value relative to scope.

---

> **Model selection for design phase (Claude.ai work before Codex/CC):**
> Each feature is tagged with the recommended Claude model for the *design conversation* — the work you do in Claude.ai before sending a Codex prompt. The implementation tools (Codex, Claude Code) have their own model handling and are unaffected.
>
> - **Opus 4.8** — design conversations with non-obvious tradeoffs, new architecture, integration across multiple modules, measurable success criteria, or strategic implications
> - **Sonnet 4.6** — Codex prompt writing for well-scoped features, CC review prompt writing, UI tweaks, copy changes, daily building
> - **Haiku 4.5** — quick lookups, PowerShell syntax, single-file edits
>
> Default to Sonnet 4.6. Escalate to Opus 4.8 when the conversation requires judgment under ambiguity rather than executing a clear pattern.

### 1 · Position Tracking with Lot-Level Cost Basis  ·  *Design: Opus 4.8*

**Why this is first.** Without it, the Portfolio page is a watchlist with extra columns. Cost basis is the foundation everything else (P&L, margin-of-safety against fair value, performance attribution, tax-loss harvesting) sits on top of.

**User story.** As an investor running the FinLens workflow, I want to record each purchase of a security with date, shares, and price so that FinLens can show me real P&L, weight my portfolio correctly, and compare my cost basis to my DCF fair value.

**Spec.**
- Add Position flow: ticker, shares, price per share, transaction date, optional notes/thesis-at-entry.
- Track each purchase as a separate **lot** (not just running average). Display avg cost as a derived field, but keep lots separate for tax and decision purposes.
- Sell flow: shares sold, price, date, lot selection (FIFO default, LIFO, specific-lot for tax optimization).
- Per-position derived fields auto-computed from yfinance: current price, current value, unrealized P&L ($ and %), days held, position weight, dividends received (if tracked).
- Portfolio-level derived fields: total value, total P&L, sector allocation, top 5 / bottom 5 positions, cash balance.

**Tech notes.**
- Schema: `positions` table keyed by user_id, with `lots` as a related table (one-to-many). Don't denormalize lots into a single avg-cost field — you'll regret it the first time someone asks for tax-lot reporting.
- Cache yfinance price calls per session — don't refetch on every render.
- Currency handling: capture transaction currency on the lot. CAD positions in a USD-displayed portfolio need FX conversion at display time, not at entry.

**Scope.** Medium. ~5–8 days of focused work. The data model is straightforward; the edge cases (corporate actions, splits, dividends, FX) are what eat time. Ship without corporate-action handling first; add it when a user complains.

**Commercial rationale.** This is the feature that makes FinLens a *primary* tool rather than a *supplemental* one. Until cost basis lives in FinLens, users will keep their actual portfolio in Wealthsimple or Questrade and use FinLens for analysis on the side. After cost basis lives in FinLens, FinLens becomes the daily-open habit. Daily-open habits convert to paid subscriptions; supplemental tools don't.

---

### 2 · Catalyst Calendar  ·  *Design: Sonnet 4.6*

**Why.** Chapter VIII step 6 (Monitor) explicitly calls for a per-ticker catalyst list. Currently a FinLens user has to assemble this themselves from earnings dates on yfinance, conference schedules from IR sites, and ex-div dates scattered across sources. A unified calendar is cheap to build and high daily-engagement.

**User story.** As an investor with 10–20 positions, I want a single calendar view of upcoming events across my portfolio (earnings, ex-div, analyst days, conferences, FDA decisions, etc.) so I can prepare for catalysts and avoid being surprised.

**Spec.**
- Per-ticker event types: next earnings date, ex-dividend date, analyst day, investor conference appearances, regulatory dates (FDA PDUFA for biotech, OFSI/OSC dates for Canadian financials).
- Portfolio-wide view: "Next 30 days" feed grouped by date, with the position size next to each event so the user knows which catalysts matter most.
- Email/in-app reminder 24h before high-priority events (configurable).
- Past events log per ticker with the price reaction recorded (`±X% over event window`). This is the seed of an "earnings drift" feature later.

**Tech notes.**
- yfinance has earnings dates and ex-div dates. FMP has earnings calendars. Conferences/analyst days require IR-page scraping or paid feeds — start with manual entry per ticker, automate later.
- Store events as `events` table with `ticker`, `event_type`, `event_date`, `source`, `confidence` (so you can flag low-confidence scraped events).
- Display: minimalist month or list view in the Portfolio sidebar, expandable per event.

**Scope.** Small to medium. ~3–5 days. The first version is just earnings + ex-div from yfinance/FMP, presented well. The second version adds the alerts and the post-event price reaction tracking.

**Commercial rationale.** Daily engagement driver. Investors check this every morning to see what's coming up. High retention, low support burden, easy to demo. Also the foundation for **kill-criteria alerts** (feature 6 below in Part II) — same alerting infrastructure.

---

### 3 · Filing Diff Viewer  ·  *Design: Opus 4.8*

**Why this is the most defensible feature on this list.** Chapter V teaches the four-question MD&A read, and the discipline of diffing this year's filing against last year's. Nobody in the consumer fintech space does this well. AlphaSense and Sentieo do versions of it for enterprise. Building this puts FinLens in a category currently occupied only by enterprise tools.

**User story.** As an investor reading a fresh 10-K or AIF, I want to see what changed from last year's version — particularly in Risk Factors, MD&A, and accounting policy footnotes — so I can focus my reading on the parts that contain new information.

**Spec.**
- Per-filing view: fetch current filing and prior-year equivalent. Side-by-side or unified diff view.
- Section-level diff: rather than diffing the whole document, diff each named section (Item 1A Risk Factors, Item 7 MD&A, etc.) separately. Sections that didn't change collapse.
- Claude-powered semantic summary: "What materially changed in this section vs last year?" — a 2-3 sentence summary per modified section. This is where the AI moat lives.
- Highlight types: added language (green), removed language (red), modified language (yellow). Standard diff conventions.
- One-click "Show me only the changes" filter — hides unchanged sections entirely.
- Works for 10-K vs 10-K, 10-Q vs prior-quarter 10-Q, AIF vs AIF, MD&A vs MD&A.

**Tech notes.**
- EDGAR full-text search returns filings; you already integrate EDGAR. Add prior-year retrieval to existing fetch.
- Use `difflib` or a more sophisticated semantic-diff library for the raw diff. For the Claude-summarized layer, pass the diff hunks to Claude with a prompt template.
- Cache filings aggressively — these don't change after filing date. Cache key: `{cik}_{form_type}_{fiscal_year}`.
- Cost discipline: Claude summarization is expensive. Cache the summarized output per filing pair so a second user reading the same filing pays nothing incremental.

**Scope.** Large. ~10–15 days. The plumbing is straightforward but the UX is where the value lives — bad diff UX (raw `+/-` lines from git-style diff) helps nobody. Spend the time on presentation.

**Commercial rationale.** This is the feature you can charge $99/month for and have professional investors think it's underpriced. Two reasons: (1) the time savings are enormous — reading a 10-K diff takes 15 minutes instead of 4 hours, (2) it's *better* than reading the full filing because it forces focus on what's new. Combined with SEDAR+ coverage, this is your single biggest differentiator vs Koyfin, Finchat, and the rest of the $40-80/mo tier. Build it well and put it in the screenshots.

---

### 4 · Research Notebook / Memo Builder  ·  *Design: Opus 4.8*

**Why.** Chapter VIII step 4 is the one-page investment memo. The curriculum hammers that the discipline of writing is what makes the thesis honest. Currently a FinLens user writes their memo in Notion or a Google Doc — disconnected from the actual analysis. A native memo tool inside FinLens stitches everything together into the artifact a real analyst (and a real VC) produces.

**User story.** As an analyst running the FinLens workflow, I want to write a structured investment memo for each ticker I research, with the eight-section template from the curriculum (trade, business, thesis, valuation, catalysts, risks, kill criteria, sizing) — and have it auto-link to the underlying DCF, financials, and filings so future-me can re-read it in full context.

**Spec.**
- Template-driven memo: eight fields matching the curriculum's framework. Each field is markdown-editable.
- Auto-populated context: ticker, current price at time of memo, FinLens DCF fair value at time of memo, current consensus estimates. Snapshot these at memo creation so future-me can grade past-me's call.
- Memo versioning: every edit creates a new version with a timestamp. Show history. This is what makes the memo a track-record artifact rather than a wiki page.
- "Six months later" re-read prompt: 180 days after a memo is finalized, FinLens sends a notification: "It's time to re-read your memo on [TICKER]. What actually happened?" Opens the memo with a new field: "Retrospective."
- Export to PDF with FinLens branding (for family-office tier) or markdown (for personal use).
- Optional: "Show this memo to other FinLens users" — opt-in public memo sharing. Builds the community/credibility moat.

**Tech notes.**
- Schema: `memos` table with `id`, `user_id`, `ticker`, `created_at`, eight body fields, `snapshot_data` (JSON of price/DCF/consensus at creation), version reference.
- Tie memos to positions: a memo can be associated with one or more positions (e.g., the memo at initial entry, the memo at follow-on).
- Markdown editor: don't roll your own — use `streamlit-quill` or similar, or just `st.text_area` with markdown preview.

**Scope.** Medium. ~5–7 days for the core builder. The "six months later" reminder loop and the public-sharing feature are each separate ~2-day additions.

**Commercial rationale.** This is the integration capstone of the entire product. It's also the **VC-flavored feature** that distinguishes FinLens from generic retail tools — IC memos are the VC workflow. Finance students preparing for analyst roles will use this to build a portfolio of written work. Aspiring VCs will use it to demonstrate analytical rigor to GPs. Family offices will use it for documentation. This feature alone justifies the Professional tier.

---

### 5 · Curriculum Mode  ·  *Design: Sonnet 4.6*

**Why.** This is the commercial wedge that no competitor has. The HTML curriculum is a standalone document; Curriculum Mode is the curriculum living inside the tool, with progress synced and the right workspace surfaced for each chapter's exercise.

**User story.** As a learner working through the 20-hour curriculum, I want FinLens to know which chapter I'm on and surface the right workspace, deliverable checklist, and tooltips so I can focus on doing the work instead of context-switching between the curriculum doc and the app.

**Spec.**
- Curriculum sidebar appears as a toggleable mode (top-right "Learn" button).
- User picks a "curriculum ticker" once. That ticker is the working example through all 8 chapters.
- Each chapter opens the relevant FinLens tab (Ch I → Analysis, Ch II → DCF Calculator, etc.) with the chapter's deliverable checklist pinned to the side and the exercise prompts inline.
- Progress syncs with the standalone HTML curriculum via export/import (or eventually via account sync).
- Capstone view (Ch VIII) shows the user's full work product — three-statement notes, DCF output, earnings analysis, filing diff, memo, portfolio entry — as a single portfolio artifact.

**Tech notes.**
- This is more product/UX than engineering. The features are already being built; Curriculum Mode is a *configuration* of existing features with educational scaffolding.
- Storage: `curriculum_progress` table with user_id, chapter, completed_at, deliverable_link (URL to the memo or analysis they produced).
- Don't build a video curriculum — that's a different product. Keep it text-based, reading + doing.

**Scope.** Medium. ~7–10 days, mostly UX wiring. The educational content already exists (the HTML curriculum).

**Commercial rationale.** This is the **finance-student wedge**. Universities and CFA candidates will adopt this if it's good. The Columbia course Riley is taking is the market signal — people pay real money ($2k+ for short courses) for structured finance training, and most of it is theoretical. FinLens-with-curriculum is theory plus the tool, in one product, for $49/month. The conversion path: free curriculum download → trial Curriculum Mode → become a paid user. Lifetime value of a finance student who graduates into a buy-side seat with FinLens as their training tool is enormous.

---

## Part II — Commercial-Value Features

These are the features I'd add to drive conversion, retention, and tier upgrades — organized by category. Not all of these belong in the next 6 months; the priority is in the tier-mapping at the end.

---

### A · AI-Native Features (Claude API as the Moat)

These are features only an AI-native tool can ship well. They're also where FinLens's per-feature cost is highest, so they go behind paywalls or rate limits.

**6 · AI Earnings Call Summarizer** · *Design: Opus 4.8*. Paste a transcript (or auto-fetch from a provider), get a structured analysis: tone shift vs last quarter, hedging-language count, the topics analysts pushed back on, what management didn't answer cleanly. This operationalizes Chapter IV's "reading the earnings call" framework. Differentiator: most tools summarize the prepared remarks. This summarizes the *Q&A*, which is where the real signal lives.

**7 · AI Filing Q&A** · *Design: Opus 4.8*. Natural-language question against a loaded 10-K or AIF. "What's the customer concentration risk?" → answer with section citations. RAG-style: chunk the filing, embed, retrieve, answer with Claude. This is table stakes for AI-native financial tools in 2026; if FinLens doesn't have it, users will leave for Finchat.

**8 · AI Bear Case Generator** · *Design: Sonnet 4.6*. User writes a bull thesis. Claude generates the strongest bear case it can construct from the same filings, ratios, and macro context. This is Chapter VIII's "disconfirmation" exercise automated. Powerful for new analysts who naturally over-weight their own thesis.

**9 · AI Peer Discovery** · *Design: Opus 4.8*. "Find me 5 companies similar to NVDA in business model but different in geography." Better than rigid SIC/GICS peer matching — Claude can reason about business model overlap that industry codes miss. Use embeddings on business descriptions + Claude refinement.

**10 · AI Auto-Draft Investment Memo** · *Design: Opus 4.8*. Given a ticker, Claude reads the filing, pulls financials, runs a peer comparison, and drafts the eight-section memo (feature 4 above). User edits. This is the "10× faster than writing from scratch" feature — the one that makes a single analyst feel like a team of three.

---

### B · Data Depth (Parity + Selective Advantage)

These are features competitors already have. You need most of them to be considered seriously, but don't try to out-Bloomberg Bloomberg — pick the high-value subset.

**11 · Insider Transactions (Form 4 / SEDI)** · *Design: Sonnet 4.6*. Officer and 10%-owner buys and sells. SEDAR+ has SEDI (System for Electronic Disclosure by Insiders) for Canadian issuers, which is another SEDAR+ differentiator vs US-only tools. Display: per-ticker insider activity table + portfolio-wide insider-buying signal feed.

**12 · 13F Institutional Ownership** · *Design: Sonnet 4.6*. Quarterly. Who's accumulating, who's distributing, what % of float is held by the top 20 funds. The "who's smart-money holding" feature retail investors love.

**13 · Short Interest with History** · *Design: Sonnet 4.6*. Not just the level — the *path*. Rising SI on falling price is one signal; rising SI on flat price is another. Display: chart with price overlay.

**14 · Analyst Estimate Distribution** · *Design: Sonnet 4.6*. Consensus is one number; the *distribution* is the information. High estimate, low estimate, dispersion, revision velocity, recent up/down ratios. This is Chapter IV's revisions framework as a live data product.

**15 · Dividend History & Coverage Ratio** · *Design: Sonnet 4.6*. For income investors. Per-share dividend history, growth rate, payout ratio, coverage ratio (FCF / dividend). The conservative-investor demographic is more willing to pay for tools than the meme-stock demographic.

**16 · Options Activity** · *Design: Sonnet 4.6*. Unusual options volume, put/call ratio per ticker, implied volatility skew. Used by sophisticated retail and by event traders. Lower priority unless going after the active-trader segment.

---

### C · Workflow & Retention Features

These keep users in the product and drive virality.

**17 · Conditional Alerts** · *Design: Opus 4.8*. Price, RSI, ratio (P/E hits target), earnings beat by X%, insider buy above $Y, MD&A diff flagged. Email + in-app. This is the daily-utility feature that creates daily-open habit.

**18 · Watchlists with Smart Sorting** · *Design: Sonnet 4.6*. Not just a list. Sortable by margin-of-safety vs your saved DCF, by upcoming-catalyst proximity, by revision velocity, by insider activity. Smart watchlists (e.g., "all my financial-sector positions") that auto-update.

**19 · Public Memo Gallery & Track Record** · *Design: Opus 4.8*. Opt-in. Users publish their memos; FinLens tracks the actual price action vs the memo's thesis over time and assigns each user a transparent track-record score. This is the *community* moat — every memo published makes the next user more likely to join. Also a recruiting signal for the user (publish memos → demonstrate analytical ability → get hired into a buy-side seat).

**20 · Slack/Discord Integration** · *Design: Sonnet 4.6*. Family offices, small funds, and study groups want to share analyses in channels. Send a FinLens memo or alert directly to a Slack channel. Cheap to build, high stickiness for teams.

**21 · Browser Extension** · *Design: Opus 4.8*. Right-click on a ticker on Bloomberg.com, SeekingAlpha, Reuters, or Twitter/X → "Open in FinLens." Reduces context-switching. Reduces churn (every easy path back into the app is a retention lever).

---

### D · Portfolio Depth

Once cost basis exists, these compound on it.

**22 · Performance Attribution** · *Design: Opus 4.8*. What drove your returns over the last quarter/year? Position selection, sector tilt, market timing, FX. Critical for serious investors and required for any user calling themselves a "fund manager."

**23 · Factor Exposure Analysis** · *Design: Opus 4.8*. Your portfolio's exposure to size, value, momentum, quality, low-vol. Lets users see when they're accidentally a factor bettor rather than a stock picker (Chapter VII's framework).

**24 · Rebalancing Engine** · *Design: Opus 4.8*. Set target weights, FinLens tells you what to trim/add to get back to targets. Threshold + calendar options per Ch VII. Generates a one-click trade list.

**25 · Portfolio Stress Test** · *Design: Opus 4.8*. "What happens to your portfolio in a 2008-like scenario? A 2020-like? A 2022 rate-shock?" Apply historical factor returns to current portfolio composition. Surprisingly cheap to build and a *killer* sales demo for the family-office tier.

**26 · Tax-Lot Optimization** · *Design: Opus 4.8*. For taxable accounts. Identifies the best lots to sell to minimize tax (or harvest losses). US and Canadian rule sets — Canada's superficial-loss rule is different from the US wash-sale rule, which is itself a SEDAR+-adjacent differentiator.

**27 · Multi-Portfolio Support** · *Design: Sonnet 4.6*. Real portfolio, model portfolio, paper-trading portfolio, family member's portfolio. Switch between them. Family offices manage 5–15 portfolios; advisors manage hundreds.

---

### E · VC-Specific Features

Because the long-term Riley-as-VC arc means FinLens should grow into adjacent VC workflows.

**28 · Private Company Valuation Toolkit** · *Design: Opus 4.8*. Pre-money / post-money calculator. Dilution waterfall across rounds. Option-pool top-up math. Liquidation preferences (1× non-participating vs participating).

**29 · Fund Return Modeling** · *Design: Opus 4.8*. IRR, TVPI, DPI calculators. Power-law portfolio simulation: "If 70% of your investments return 0, 20% return 1×, 8% return 5×, 2% return 50× — what's the expected fund return?" Includes reserve-allocation modeling (Ch VII VC sidebar).

**30 · Cap Table Modeling** · *Design: Opus 4.8*. Multi-round cap tables with founder/employee/investor splits. Particularly valuable when paired with feature 28.

**31 · Term Sheet Comparator** · *Design: Opus 4.8*. Side-by-side comparison of term sheets with plain-English translations of each clause and "this is unusual / market / favorable" annotations. Niche but high-value for first-time founders and emerging VCs.

---

### F · Reports & Exports (Family Office Tier)

**32 · Custom-Branded PDF Reports** · *Design: Sonnet 4.6*. Family office logo, advisor's name, quarterly performance summary, position-level commentary auto-pulled from memos. Auto-generated, hand-editable.

**33 · Client Sharing** · *Design: Opus 4.8*. A family-office user can grant view-only access to a client (or beneficiary) for a specific portfolio. The client sees a clean dashboard, the advisor retains control.

**34 · API Access** · *Design: Opus 4.8*. For sophisticated users who want to pull FinLens data into their own spreadsheets or notebooks. Read-only at first; eventually read-write.

---

### G · Trading & Strategy

### 35 · Trade Strategy Suite  ·  *Design: Opus 4.8*

Convert FinLens analysis output into a disciplined trading practice. Four integrated sub-features that share a common data layer.

**35a · Entry/Exit Rules Engine.** Per-position rules set at memo creation: entry price target, scale-in plan, trim triggers (price targets, valuation ratios, thesis-completion events), hard stop (price below X, thesis breakage event). FinLens monitors and alerts when a rule triggers. Forces Chapter VIII's kill-criteria discipline into the actual workflow instead of leaving it in the memo.

**35b · Strategy Backtester.** Define a rules-based strategy ("buy when FinLens signal flips to PASS and margin of safety > 30%; sell when MoS < 0% or 12 months elapse, whichever first"). Run against historical signals + price data. Output: equity curve, Sharpe, max drawdown, win rate, average holding period, comparison to SPY/benchmark. Critical caveat: requires historical FinLens signal data to be archived (not currently retained).

**35c · Trade Journal.** Every executed trade logged with: ticker, action (buy/sell/trim/add), lot reference, price, date, FinLens signal at time of trade, memo version at time of trade, free-text rationale, emotional state (optional 1-5 scale). Post-trade review prompts at 30/90/180 days: "Was this the right call? Why?" Builds the introspective data set most retail investors never accumulate.

**35d · Signal-to-Action Workflow.** When a FinLens analysis completes, surface a "Build trade plan" CTA. Walks user through: position size (per Ch VII rules, using lot tracker), entry plan (immediate vs scaled vs conditional), exit rules (price targets, kill criteria, time horizon), catalysts to monitor. Output: a structured trade plan attached to the position. Connects analysis → memo → position → monitoring as one continuous artifact.

**Tier placement.** All four are Professional-tier ($199) features. Backtester (35b) is the most compute-intensive and could anchor a separate "Quant" add-on if user demand emerges.

**Dependencies.** Builds on: Position Tracker (✅ shipped), Memo Builder (feature #4), Catalyst Calendar (feature #2), Conditional Alerts (feature #17). Should not be built until those four are live.

**Estimated effort.** 2-3 weeks total, ~1 week per sub-feature with shared data layer.

---

## Part III — Tier Mapping

How the features distribute across price points.

### Free Tier (acquisition + curriculum funnel)
- Stock Tracker with charts
- Basic financial statements
- Watchlists (limit: 10 tickers)
- Education page
- Curriculum download (HTML)
- Limited Claude API actions (e.g., 5 AI analyses per month)

### Individual ($49/month)
- Everything in Free
- Position tracking with lot-level cost basis (feature 1)
- DCF Calculator (existing)
- Filing Q&A (feature 7) with reasonable monthly limit
- Catalyst Calendar (feature 2)
- Conditional Alerts (feature 17), basic
- Curriculum Mode (feature 5)
- Memo Builder (feature 4), up to 25 memos
- SEDAR+ access — flagship differentiator, available at this tier

### Professional ($199/month)
- Everything in Individual
- Unlimited memos with version history
- Filing Diff Viewer (feature 3) — the headline upgrade reason
- AI Auto-Draft Memo (feature 10)
- AI Earnings Call Summarizer (feature 6)
- AI Bear Case Generator (feature 8)
- Insider Transactions + SEDI (feature 11)
- 13F Holdings (feature 12)
- Performance Attribution (feature 22)
- Factor Exposure (feature 23)
- Rebalancing Engine (feature 24)
- Portfolio Stress Test (feature 25)
- Multi-portfolio support (feature 27) — up to 3
- Public memo gallery participation (feature 19)
- Browser extension (feature 21)
- Higher Claude API limits

### Family Office / Team ($499–$999/month)
- Everything in Professional
- Multi-portfolio support — unlimited
- Client sharing (feature 33)
- Custom-branded PDF reports (feature 32)
- Team workspaces with permissions
- API access (feature 34)
- Slack/Discord integration (feature 20)
- VC toolkit (features 28–31)
- Priority support
- Highest Claude API limits, or pass-through billing

---

## Part IV — Strategic Notes

**On pricing tiers.** The jump from $49 to $199 needs a clear "why" — the Filing Diff Viewer plus the AI memo features are that "why." Don't dilute the Individual tier with features that should be Professional; you'll cannibalize your own upgrades.

**On the freemium funnel.** Finance students are your highest-LTV cohort over 5+ years. They graduate, get hired, become buy-side analysts, and bring FinLens with them. Free curriculum + Curriculum Mode trial is the funnel. Be generous with the free tier for verified students (`.edu` email).

**On SEDAR+ as the wedge.** Every roadmap conversation should ask: "does this preserve or extend the SEDAR+ advantage?" Most US-built fintech products will never bother with SEDAR+. That's your protected territory. Double down: SEDI insider data, Canadian short interest (IIROC), Canadian dividend tax treatment, CRA tax-lot rules.

**On AI features as commodity vs moat.** Filing Q&A will be commoditized by 2027. Filing Q&A on SEDAR+ filings, with custom Canadian-accounting-aware prompts, is harder to replicate. Always look for the angle where the AI feature compounds with a structural advantage.

**On VC features as a long arc.** Don't build features 28–31 until you have paying Professional users. They are the *demonstration* that FinLens isn't just for public-market investing — but they're slow to acquire and shouldn't distract from the consumer wedge until that wedge is producing $5–10k/month in recurring revenue.

**On the order I'd actually build in.**

1. Position tracking with lot-level cost basis (feature 1) — foundation
2. Catalyst Calendar (feature 2) — engagement
3. Memo Builder (feature 4) — VC-flavored differentiator
4. Filing Diff Viewer (feature 3) — Professional tier anchor
5. Curriculum Mode (feature 5) — commercial wedge for students
6. Conditional Alerts (feature 17) + Insider Transactions (feature 11) — retention
7. AI Auto-Draft Memo (feature 10) + AI Earnings Call Summarizer (feature 6) — Professional tier value
8. Performance Attribution (feature 22) + Rebalancing Engine (feature 24) — portfolio depth
9. Portfolio Stress Test (feature 25) + Custom-Branded Reports (feature 32) — Family Office tier anchor
10. VC toolkit (features 28–31) — only after Professional tier hits 100 paying users

That sequence gets you to a defensible $49 tier in 90 days, a saleable $199 tier in 180 days, and a credible $499 family-office tier in 12 months. Adjust based on what users actually pay for once Supabase Auth is live.

---

*Living document. Update as features ship, users provide feedback, and the commercial mix becomes clearer.*

## Part V — Model Selection Cheat Sheet

When the conversation requires judgment under ambiguity → **Opus 4.8**
When the conversation requires executing a clear pattern → **Sonnet 4.6**
When the conversation requires a quick lookup → **Haiku 4.5**

Use the per-feature tags above for the design phase only. Implementation tools (Codex, Claude Code) handle their own model selection.

**Sundays:** Step 7 (strategic review) is always Opus 4.8. Steps 1-6 (mechanical audits) can be Sonnet 4.6.

**Debugging:** Novel bugs / unexpected behavior → Opus 4.8. Reproducible bugs with clear repro steps → Sonnet 4.6.

---

## Expanded Specs — Backlog Items (June 2026)

### Earnings Revision Tracking (roadmap #4)
**What:** Track analyst estimate changes over time for holdings/tracked tickers. Rising revisions = robust positive signal; falling revisions = early thesis-deterioration warning ("is my margin of safety eroding before the price shows it?").
**Data:** FMP analyst estimates endpoint — MUST verify free-tier access to estimate HISTORY (not just current estimates) before design; this is the make-or-break. Fallback: trend FMP earnings surprises across consecutive quarters (already pulled for Beat/Miss badges).
**Display:** Sparkline + direction badge on Stock Tracker; revision history in Earnings tab alongside Earnings History.
**First step:** 10-minute API probe of FMP free tier.

### Price Alerts (roadmap #6)
**What:** Alerts tied to margin-of-safety buy prices ("MKL hit your buy price"). The patience-enforcement feature — set the intrinsic-value target once, stop watching the ticker.
**Constraint:** Streamlit has NO background scheduler — app only executes on page load.
**Phase 1 (no infra):** check-on-load — opening Portfolio shows a banner for any holding past its target price (yfinance, free).
**Phase 2:** GitHub Actions cron (free) runs a price-check script against saved targets, sends email on trigger.

### Reddit + Polymarket Sentiment Tab (roadmap #11)
**What:** Polymarket already integrated — this item is "add Reddit." Framing is CONTRARIAN, per Marks second-level thinking: extreme retail euphoria on a holding is a red flag, not a buy signal. Crowd-temperature gauge, not momentum signal.
**Data gotcha:** Reddit API free tier is restrictive — verify current limits first; FMP social-sentiment endpoint may be the cheaper path.
**Display:** mention volume + tone on Stock Tracker News & Sentiment tab, explicitly labeled as crowd sentiment.

### Deep Link "Learn More" Buttons (roadmap #12)
**What:** Buttons exist but land at Education page top, not the relevant section.
**Implementation:** st.query_params (e.g. ?page=education&section=dcf); Education page reads param, expands/scrolls to section. Streamlit has no native anchor scrolling.
**Sizing:** ~1 hour. Bundle into next Education pass (with Munger mental-models chapter), not a standalone commit.

### Resource Economics Snapshot (post-campaign)
Resource Economics Snapshot — fuse filing fundamentals with commodity/market data (AISC vs spot for mining, netback vs price for O&G). Three-tier spec: docs/RESOURCE_ECONOMICS_SNAPSHOT_SPEC.md. Tier 1 free/buildable now; Tier 2 gated on MD&A fetcher; Tier 3 ties to Industry Context panel.
