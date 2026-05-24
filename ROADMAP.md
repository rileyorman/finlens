# FinTelligence — Product Roadmap
*Updated: May 2026 | Owner: Riley Orman*

---

## Phase 1 — June Meeting Ready (In Progress)

### Completed ✅
- PDF upload → Claude API → Excel output (4 tabs)
- Two-call architecture: Haiku (extraction) + Opus (signal)
- Fund manager persona prompt — principal investor, 20+ years
- INVESTIGATE / PASS / DECLINE signal with thesis
- RAG financial health scoring (5 metrics)
- Valuation section with automatic multiples
- yfinance live market data integration
- Windows SSL fix (Avast compatibility)
- FinTelligence rebranded, on GitHub
- Global CLAUDE.md + project CLAUDE.md committed

### In Progress 🔄
- Ticker auto-search by company name (yfinance.Search)
- Cash Flow Statement condensed header fix
- Update Excel button visual feedback
- Signal Tracker design complete — build pending

### Remaining Before June 📋
- Signal Tracker build (the Dalio notebook)
- Test on bank filing (USB 10-K)
- Test on insurance filing (Aflac 10-K)
- Streamlit Community Cloud deployment
- Demo flow rehearsal

---

## Phase 2 — Post June (Summer 2026)

### High Priority
- Auto-fetch from SEC EDGAR — user types ticker/company 
  name, FinLens finds and downloads the filing automatically. 
  No PDF upload needed. Transforms the workflow entirely.
- Venture Mode — early stage company analysis:
  Burn rate, runway, ARR growth, unit economics, cap table 
  awareness. Different RAG thresholds, different signal logic.
- Statement of Shareholders Equity — equity dilution, 
  retained earnings movement, stock-based compensation
- Smart truncation — find financial statement start position 
  in document rather than fixed character limit. Reduce cost 
  while preserving quality.

### Medium Priority
- Sector-aware FinLens — detect filing type (corporate / 
  bank / insurance) and apply appropriate metrics:
  - Bank mode: CET1, Tier 1, Net Interest Margin, NIM
  - Insurance mode: Combined ratio, premiums earned, loss ratio
  - Suppress broken metrics gracefully
- One-page PDF export of Summary tab
- Word document support
- Company logo auto-fetch

### Lower Priority
- Stress testing module — Dalio four economic environments
- Correlation awareness — portfolio fit
- Comparable companies — sector peer multiples
- DCF module — simple discounted cash flow

---

## Phase 3 — FinTelligence Platform (Late 2026)

- Signal Tracker — track every signal and measure accuracy.
  Your proprietary track record. The Dalio notebook.
- Deal pipeline — track opportunities from signal to decision
- Portfolio monitor — ongoing tracking of held positions
- Investment memo generator — full Word doc output
- Multi-filing comparison — analyze 3 companies side by side
- LP-ready reporting — family office investor updates

---

## Technical Debt & Infrastructure

- Fix ticker extraction reliability (yfinance.Search fallback)
- EDGAR automated fetch (currently blocked in Claude Code env)
- Sector detection logic before bank/insurance test
- Streamlit Community Cloud deployment + secrets.toml setup
- FinTelligence repo initialization on GitHub
- Rename local folder orman_intelligence → fintelligence

---

## June Meeting Prep

**Date:** June 2026
**Audience:** Family office CEO (ex-top investment banker, 
$200M+ built) + CFO
**Goal:** Demonstrate FinLens as a serious investment 
analysis tool
**Demo filing:** Mastech Digital (MHH) — known good output
**Key talking points:**
- Two-call AI architecture (Haiku + Opus)
- Fund manager persona — making a call, not a summary
- Signal Tracker as proprietary methodology (Dalio reference)
- Phase 2 roadmap — where this goes next
- Built by Riley as part of FinTelligence platform

---

*FinTelligence · AI-powered investment platform · 
Powered by Claude*
