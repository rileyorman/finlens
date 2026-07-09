# Coverage: close the n=1 gaps (2nd bank + 2nd O&G filer)

**Why.** The 2026-07-09 audit (Step 4) and the Step-8 Opus review (rec #2) both
flag it: `financial_sector` is n=1 (RY) and `resource_sector` is n=1 (CNQ). A
single filer per profile means those sectors' judgment-class rulings are
**un-cross-checked** — the second filer is the validation event that turns a
one-filer guess into a trustworthy shape. Breadth is what both a buyer and the
"widest validated Canadian corpus" story actually need.

**The one thing only Riley can do:** supply the filing PDF. SEDAR+ is
CAPTCHA-gated, so filings are hand-downloaded (issuer IR page or SEDAR+) and
dropped at `C:\Users\riley\.finlens\sedar\filings\`. Everything after that
(extract → map → cross-check → promote → registry → suite) is CC work.

---

## Recommended 2nd filers (picked because the mapper groundwork already exists)

### 2nd bank → **TD (Toronto-Dominion), FY2025** — lowest friction
The mapper was already hardened for TD as a cold-slot dry-run:
- CB-018 (commit `56cb4fd`): canonical-first revenue, bare-EPS scale guard, and
  the **`provision for credit losses`** (PCL) alias — all shipped and in
  `sedar_aliases.json`. TD's slot went **FAIL → PASS**.
- What's missing: TD was never **banked as a validated fixture**. So this is a
  promotion, not a from-scratch mapping. Just needs the PDF + a clean run.

### 2nd O&G → **IMO (Imperial Oil, FY2025)** or **TOU (Tourmaline, FY2024)** — extraction already done
Both have **candidate extraction bundles on the `sterling` remote** from the
ingestion pilot:
- `sterling/ingest/IMO-FY2025` (commit `300ff9a`)
- `sterling/ingest/TOU-FY2024` (commit `68e4273`)
Per the ingestion spec, the canonical (Windows) side re-fetches the PDF
independently as a provenance check, re-extracts, and uses Sterling's bundle as
an **independent-agreement witness** before promotion — so the second extraction
is already sitting there as a cross-check.
- Alternative: **Suncor (SU), FY2025** — the `gross revenues` alias is already
  shipped (Task B, `35cda16`) and its producer slot was visually verified
  (SU + CNQ). No Sterling bundle, so it needs the PDF from scratch, but the
  mapper is ready.

**Recommendation for the 4-day runway:** TD (bank) + IMO or TOU (O&G via the
existing Sterling bundle). Two filers, both with the mapper already prepared.

---

## Drop-in runbook (per filer)

Secrets must be injected (`Import-Secrets`, or `sops exec-env`). Extraction is a
real (small) Haiku API call — CC will confirm go-ahead before spending.

1. **Riley:** download the annual financial statements PDF; save as
   `C:\Users\riley\.finlens\sedar\filings\{TICKER}_FY{YEAR}_annual_financials.pdf`
   (e.g. `TD_FY2025_annual_financials.pdf`).
2. **CC:** extract via `sedar_extractor.extract_sedar_filing(pdf_path)` (the same
   entry point `scripts/reextract_sedar_fixtures.py` uses) → writes a candidate
   `tests/fixtures/{TICKER}_FY{YEAR}_sedar.json.NEW`.
3. **CC:** for IMO/TOU, fetch the `sterling/ingest/*` bundle and diff the two
   independent extractions (canonical vs Sterling) — agreement is the provenance
   check; disagreements get triaged, not silently resolved.
4. **Riley (irreducible human gate):** ground-truth — hand-verify the fixture's
   `mapped[]` + major `unmapped[]` against the source PDF (actual numbers, not
   just the filing date; ~20 min, fresh head, no expected values pre-supplied).
   This is the check that makes all downstream automation trustworthy.
5. **CC:** promote — rename `.NEW` → validated fixture; **regenerate the registry**
   (`scripts/build_filing_registry.py`) and run the **FULL** suite including
   `test_filing_registry.py` (never a narrowed subset — the
   "Fixture mapped_count Changes Require Registry Regen + Full Suite" rule).
6. **CC:** update the corpus count docs (SESSION_HANDOFF "Campaign state",
   STEP_7 prompt) — 15 → 16/17 filers; note the sector is now n=2.

**Result:** `financial_sector` and `resource_sector` become n=2 — the two
single-filer rulings get their first independent cross-check, and the corpus
story goes from "wide-and-thin, 5 shapes one-filer-deep" to two more shapes
validated.

---

## Notes / cautions

- **Cross-check, don't just add.** The value of the 2nd filer is the *validation
  event* — if its labels disagree with the profile's rulings, that's a casebook
  question for Riley (a spec), not a silent alias add (Iron Rule: mapper/alias
  changes need a spec).
- **Ground-truth is non-negotiable** before a fixture is called `campaign_validated`
  (per the gate discipline). No promotion without it.
- **This is moat work, not feature work** — it serves whichever product Riley
  picks in `docs/MOAT_VS_SAAS_DECISION.md` (casebook proof OR sellable-dataset
  breadth), so it's safe to do before that decision lands.
