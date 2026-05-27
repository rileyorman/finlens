# FinLens — Product Roadmap

**Last updated:** May 2026  
**Goal:** World-class fund manager tool for financial statement analysis  
**Demo target:** June 2026 family office meeting

---

## Model Tier Strategy

FinLens is built with a two-tier model config so upgrading is a single config change:

| Tier | Models | Cost | Use case |
|---|---|---|---|
| **Student (current)** | Haiku (extraction) + Sonnet (analysis) | ~$0.05–0.20/run | Development & testing |
| **Pro (when budget allows)** | Haiku (extraction) + Opus (analysis) | ~$0.20–0.50/run | Client demos & production |

**To upgrade:** Change one line in `config.py`:
```python
ANALYSIS_MODEL = "claude-opus-4-6"   # Pro tier
ANALYSIS_MODEL = "claude-sonnet-4-6" # Student tier (current)
```

---

## Cost Control (Active)

- **Response caching** — save Claude API response to JSON on first run, reload free on repeat runs *(to build)*
- **Ticker Lookup Dev Tool** — test yfinance lookups with zero API cost ✅
- **Short test filings** — use 2-3 page earnings releases for development testing
- **Haiku for extraction** — only use Sonnet/Opus for narrative reasoning tasks

---

## Current Status

### Done ✅
- PDF upload → Claude extraction → structured Excel output
- Key Ratios, Income Statement, Balance Sheet, Cash Flow tabs
- Comparative FY columns, accounting format, red negatives
- yfinance live market data integration (price, market cap, P/E)
- US exchange prioritization with name-match tiebreaker
- Market cap T/B/M formatting
- Signal badge (INVESTIGATE / PASS / DECLINE)
- Investment thesis + catalysts & risks
- Financials at a Glance card row
- Financial Health RAG table
- Valuation multiples (EV/EBITDA, P/E, EV/Revenue, P/FCF)
- Two-branch Git workflow (main/dev) across all repos
- Global and per-project CLAUDE.md files
- Response caching (SHA-256 → cache/*.json, free repeat runs)
- Bear/Bull Case Generator (Call 3, Sonnet, 3 points each, UI expander + Excel tab)
- Anthropic prompt caching (cache_control on SUMMARY_SYSTEM_PROMPT + BEAR_BULL_SYSTEM_PROMPT)
- Input truncation for Calls 2 & 3 (MAX_FILING_CHARS = 80,000)
- Dev-mode model toggle (config.py — swap ANALYSIS_MODEL for Sonnet ↔ Opus)

### In Progress 🔄
- Nothing currently in progress

---

## Roadmap

### Phase 1 — Fix & Stabilise (Now, before June demo)

| Feature | Description | Est. cost/run | Effort |
|---|---|---|---|
| Fix Summary tab N/A | Expand keyword lists, add fuzzy matching | No change | ✅ Done |
| Response caching | Save/reload Claude API JSON — free repeat testing | Saves ~100% | ✅ Done |
| Bear/Bull Case Generator | Auto 3-point bull + bear case from filing | +$0.02 | ✅ Done |
| One-page Investment Memo | Word doc export: thesis, financials, risks, verdict | +$0.02 | Medium |

---

### Phase 2 — Analyst-Grade Features (June–August 2026)

| Feature | Description | Est. cost/run | Effort |
|---|---|---|---|
| MD&A Sentiment Delta | Compare tone vs prior filing — flags confidence shifts | +$0.03 | Medium |
| Earnings Call Transcript Analysis | Upload transcript alongside 10-K — Claude cross-references verbal claims vs actual numbers, flags inconsistencies e.g. "CEO cited margin improvement — filing shows 3rd consecutive quarter of compression" | +$0.04–0.06 | High |
| Earnings Quality Score | Accruals ratio, receivables creep, capex vs depreciation | +$0.01 | Medium |
| Red Flag Radar | Auditor change, CFO departure, going concern language | +$0.01 | Medium |
| Peer Benchmarking | Pull 3-5 competitors via yfinance, auto-compare ratios | Free (yfinance) | Medium |
| Bank/Insurance support | Adapt extraction for financial sector filings | No change | Medium |
| Word document support | Accept .docx filings in addition to PDF | No change | Low |

---

### Phase 3 — Pro Tier Features (When budget allows)

| Feature | Description | Notes |
|---|---|---|
| Upgrade to Opus | Swap ANALYSIS_MODEL config — one line change | ~3x better reasoning |
| Multi-filing trend analysis | Upload 3 years of 10-Ks, identify inflection points | Higher token cost |
| Natural language querying | "How has gross margin trended?" answered from filings | Stateful session needed |
| Watch list monitoring | EDGAR filing alerts → auto-analysis → email summary | Background job needed |
| Voice briefing | 90-second spoken summary for mobile fund managers | TTS API needed |
| Streamlit Cloud deployment | Public URL for client access | Free tier available |

---

### Phase 4 — Portfolio Manager

> **Vision:** Turn FinLens into a one-stop portfolio management platform.
> Start with a paper trading portfolio for learning, transition to real
> money when ready. Every feature is designed to build genuine investing
> intuition — not just track numbers, but understand why they move.
> Bloomberg costs $25,000/year. FinLens will do more for a fraction of the cost.

#### MVP (Build next after June demo)
| Feature | Description | Cost | Effort |
|---|---|---|---|
| Position tracker | Add/edit/remove holdings — ticker, entry price, quantity, date | Free (yfinance) | Low |
| Live P&L | Current price via yfinance, unrealised P&L in $ and % | Free | Low |
| Portfolio weights | % allocation per position, sector breakdown | Free | Low |
| Watchlist | Track companies not yet bought, one-click add to portfolio | Free | Low |

#### V2 — Daily Utility
| Feature | Description | Cost | Effort |
|---|---|---|---|
| Benchmark comparison | Total return vs S&P 500 and TSX | Free (yfinance) | Medium |
| Filing alerts | Notify when a portfolio company files new 10-K or 10-Q | Free (EDGAR) | Medium |
| Dividend tracking | Record and track dividend income | Free | Low |
| Sector/geography allocation | Visual breakdown of portfolio exposure | Free | Low |

#### V3 — AI Intelligence (FinLens Differentiator)
| Feature | Description | Cost | Effort |
|---|---|---|---|
| Filing change summary | "What changed since you bought this?" narrative vs prior filing | ~$0.10/run | Medium |
| Thesis tracking | Record investment thesis on entry, Claude scores each new filing against it | ~$0.05/run | High |
| Sentiment drift monitor | Tracks MD&A tone across filings, alerts when management language shifts | ~$0.03/run | High |
| Cross-portfolio risk narrative | "3 of your 5 holdings cite rising rates as key risk" | ~$0.05/run | Medium |
| Peer relative analysis | Auto-benchmarks each holding vs 3-5 sector peers | Free + ~$0.05 | High |

#### V4 — Bloomberg Killer
| Feature | Description | Cost | Effort |
|---|---|---|---|
| Scenario analysis | "What happens to my portfolio if rates rise 1%?" | ~$0.05/run | High |
| Natural language queries | "Which holdings have FCF conversion below 70%?" | ~$0.02/query | High |
| Automated portfolio memo | Monthly one-page Word doc — performance, risks, developments | ~$0.10/run | High |
| Earnings season dashboard | All portfolio companies reporting this quarter, pre/post analysis | ~$0.10/run | High |
| Investment journal | AI-assisted trade log, thesis vs outcome pattern recognition | ~$0.02/entry | Medium |

---

## June Demo Priority List

For the family office meeting, focus on:

1. **One-page Investment Memo** — most impressive, immediately useful to a CFO
2. **Bear/Bull Case Generator** — tangible AI value-add, nothing else does this from a raw PDF
3. **Clean Summary tab** — fix N/A issue so metrics display correctly
4. **Peer benchmarking** — sector context makes the valuation story stronger

---

## Repo & Environment

- **GitHub:** rileyorman/finlens
- **Working branch:** dev (merge to main when stable/demo-ready)
- **Local path:** C:\Users\riley\OneDrive\Documents\Python Project\finlens
- **Run locally:** streamlit run app.py
- **Stack:** Python, Streamlit, Claude API, yfinance, openpyxl, pdfplumber

---

## Columbia Course Feature Roadmap

Features are sequenced to align with the Columbia Business School / Wall Street Prep
AI for Business & Finance certificate (July 13 – September 6, 2026).
Each module unlocks a FinLens feature sprint.

| Priority | Feature | Course Module | Timing |
|----------|---------|---------------|--------|
| 1 | Wire Red Flags into Word Memo | — | Now (pre-demo) |
| 2 | Demo Prep — company selection, rehearsal | — | This week |
| 3 | Financial Distress Score (logistic regression on Altman Z-Score inputs) | Module 3 — Predictive Analytics | Late July |
| 4 | MD&A Sentiment Scoring (4th Claude call, isolated prompt) | Module 7 — NLP & Text Analytics | August |
| 5 | Scenario Simulator (Monte Carlo, what-if on revenue/margins) | Module 5 — Simulations & Optimization | August |
| 6 | Filing Comparison Engine (embeddings, year-over-year language shift) | Module 6 — Generative AI / Embeddings | August |

### Feature Notes

**Financial Distress Score (Module 3)**
Logistic regression model on Altman Z-Score inputs — working capital, retained earnings,
EBIT, equity, revenue. All inputs already exist in financial_data dict. Outputs a 0–1
distress probability alongside the existing Red Flag rules.

**MD&A Sentiment (Module 7)**
New 4th Claude API call using analyze_mda_sentiment(raw_text, API_KEY).
Isolated prompt — Claude locates and scores the MD&A section for tone.
Option A architecture (separate call) confirmed over Option B (piggyback).

**Scenario Simulator (Module 5)**
User inputs revenue change % and margin compression bps. Model shows downstream
impact on FCF, interest coverage, and debt covenants. Feeds Portfolio Manager MVP.

**Filing Comparison Engine (Module 6)**
Upload two filings — embeddings identify material language shifts year-over-year.
Especially powerful for risk factors section of 10-Ks.
