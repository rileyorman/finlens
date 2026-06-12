# FinLens Bug Audit — June 12, 2026

Sweep of `app.py`, `modules/`, and related helpers for six bug classes identified
from real failures during the docx support build-out. Read-only — no fixes applied.

Ordered by severity: **crash → silent-failure → cosmetic.**

---

## CRASH

### [C5] Comparison page: `extract_text_from_pdf` on docx bytes
**File:** `app.py:2819–2826`
**Class:** 5 — file-type assumption
**Repro:** User compares two library entries where the first entry is a docx
upload that had an identified ticker (e.g., AAPL). `_pdf_cache_path(ticker, period)`
returns a `.pdf` path where the original docx bytes were saved. Line 2824 reads those
bytes; line 2826 passes them to `extract_text_from_pdf` without any `file_type` branch
or try/except. pdfplumber raises an exception that propagates up — Streamlit shows a
red error box.

Note: this only triggers for docx entries **with** an identified ticker. Docx entries
with ticker `"—"` have no bytes saved to `_pdf_cache_path` (line 5401 skips save when
ticker is falsy), so they fall through correctly to `_library_text_for_entry` at 2827.

**Fix:** Wrap the `extract_text_from_pdf` call in a try/except and fall through to
`_library_text_for_entry`, or check `entry.get("file_type")` and branch to
`convert_to_markdown` for docx. The cleanest fix: check raw_text first via
`_library_text_for_entry` before attempting byte extraction at all.

---

## SILENT FAILURE

### [C5] Portfolio Manager no-text recovery: `extract_text_from_pdf` on possibly-docx bytes
**File:** `app.py:1638–1652`
**Class:** 5 — file-type assumption
**Repro:** User clicks Re-Analyse on a docx library entry **with** a ticker in the
Portfolio Manager. `_pdf_bytes` is loaded from `_pdf_cache_path` (docx bytes stored
at a `.pdf` path). Line 1641 calls `extract_text_from_pdf(io.BytesIO(_pdf_bytes))`.
pdfplumber raises; the `except Exception:` at 1652 swallows it and falls to
`al_no_text_warning`. The user sees no explanation — the Re-Analyse button simply
disappears and `al_no_text_warning` fires a generic "no PDF stored" message.

**Fix:** Branch on `entry.get("file_type", "pdf")` before line 1641. For docx entries,
call `convert_to_markdown` using a temp file the same way the re-analyse no-text
recovery at lines 4859–4871 does. Also add `"file_type": entry.get("file_type", "pdf")`
to the `pending_reanalyse` dict built at line 1640 (currently missing, unlike the two
other setters which were fixed tonight).

---

### [C2] `lib_add` in Portfolio Manager Re-Analyse silently swallows all exceptions
**File:** `app.py:1928–1935`
**Class:** 2 — silent exception swallowing
**Classification:** Hides bugs
**Repro:** Any exception inside `lib_add` (e.g., `NameError`, corrupt JSON, permission
error) is caught and discarded at line 1934 with no logging. The re-analysis runs
successfully, but the updated result is never written to the library. User has no
indication the save failed. This is the same pattern that hid the `_is_docx` NameError
bug earlier tonight.

**Fix:** Add `logger.warning(f"lib_add failed in PM re-analyse: {e}")` before `pass`, or
use `except Exception as e:` and log. Do not raise — the guard is correct (a failed
library write should not crash the analysis). But silence makes debugging impossible.

---

### [C2] `lib_add` in Single Analysis Re-Analyse silently swallows all exceptions
**File:** `app.py:5081–5089`
**Class:** 2 — silent exception swallowing
**Classification:** Hides bugs
**Repro:** Same as above — the Single Analysis re-analyse path at line 5088 has an
identical bare `except Exception: pass`. The re-analysis result is not persisted
to the library if lib_add fails, with no user feedback or log entry.

**Fix:** Same as above — `except Exception as e: logger.warning(...)`.

---

### [C2] `lib_add` on fresh upload silently swallows all exceptions
**File:** `app.py:5365–5380`
**Class:** 2 — silent exception swallowing
**Classification:** Hides bugs
**Repro:** Fresh upload analysis completes; the `lib_add` call at 5366 fails (NameError,
bad data, etc.); the `except Exception: pass` at 5380 discards it. Upload shows success
but the Filing Library has no new entry. This is the exact bug class from tonight's
`_is_docx` incident. Comment says "Library write failure must never block analysis"
which is correct — but silent failure makes the root cause invisible.

**Fix:** `except Exception as e: logger.warning(f"lib_add on fresh upload failed: {e}")`.

---

### [C2] `_save_analysis_to_supabase` silently discards all errors
**File:** `app.py:508–524`
**Class:** 2 — silent exception swallowing
**Classification:** Intentional guard, but no observability
**Repro:** Supabase write fails (network timeout, expired key, quota exceeded); user
sees no error, and the analysis is never synced. Supabase is optional so not crashing
is correct. But with zero logging, diagnosing sync failures during a live demo or
cloud deployment is blind.

**Fix:** `except Exception as e: logger.warning(f"Supabase save failed: {e}")`.

---

### [C2] `detect_flags` and `_calc_summary_metrics` failures silently omit data from cache payload
**File:** `app.py:571–580`
**Class:** 2 — silent exception swallowing
**Classification:** Intentional guard
**Repro:** `detect_flags(financial_data)` or `_calc_summary_metrics(financial_data)`
raises (malformed data, unexpected schema). The corresponding `payload["red_flags"]`
or `payload["ratio_data"]` key is never set. The Supabase cache payload is saved
without those fields; downstream consumers that expect them get a KeyError or missing
data. Not a crash, but silent data loss in the cache payload.

**Fix:** Acceptable to guard (enrichment is optional), but add
`logger.warning(f"detect_flags/ratio_data failed: {e}")` before each `pass` so the
root cause is visible in logs.

---

## COSMETIC

### [C1] `entry["company_name"]` used raw in sidebar display strings
**File:** `app.py:1583, 1598, 1814, 1821, 1838`
**Class:** 1 — None-as-falsy gate / None rendered as text
**Repro:** Filing Library entries with no identified company name have
`company_name: null` in the JSON. Direct dict-key access in f-strings renders the
literal string `"None"` in the sidebar: entry label shows "None", confirmation dialog
asks "Re-analyse **None**?", remove tooltip says "Remove None from library".

**Fix:** Replace `entry['company_name']` with
`entry.get('company_name') or entry.get('file_name') or 'Unknown'` at each site.

---

### [C1] `entry["company_name"]` stored raw in `pending_reanalyse` and `reanalyse_pdf_info`
**File:** `app.py:1610, 1642, 1850, 1866`
**Class:** 1 — None propagated downstream
**Repro:** When `company_name` is None, these dicts store `None` for the key. Downstream
consumers render it in spinners (`"Re-analysing **None** — running all 4 Claude calls"`)
and in the results header. Not a crash because f-strings handle None as `"None"`, but
the UX is confusing.

**Fix:** Same substitution — `entry.get("company_name") or entry.get("file_name") or "Unknown"`.

---

### [C6] `confirm_reanalyse` / `al_confirm_reanalyse` not cleared when a different entry is loaded
**File:** `app.py:1596, 1744` (confirm setter and Load button)
**Class:** 6 — session state lifecycle
**Repro:** User clicks Re-Analyse on entry A (sets `confirm_reanalyse = eid_A`). Without
clicking Cancel, they click the Load button on entry B. The Load branch doesn't clear
`confirm_reanalyse`, so on the next rerun the "Yes, re-analyse" confirmation dialog
for entry A is still visible in the sidebar. If the user then clicks "Yes", entry A
is re-analysed even though entry B is loaded. Low-risk (entries are keyed by eid), but
confusing UX.

**Fix:** In the Library Load handler (around line 1755), add
`st.session_state.confirm_reanalyse = None` and `st.session_state.al_confirm_reanalyse = None`
before `st.rerun()`.

---

## Findings not confirmed (agent flagged, verified as safe)

| Agent claim | Verdict |
|---|---|
| Class 3 (branch-defined variables): none after tonight's `_is_docx` hoist | Verified correct — no remaining branch-scope issues |
| Class 4 (.get → None-unsafe ops): none remaining | Verified — all `[:n]`, `.lower()`, regex usages are guarded |
| Class 6 `pending_reanalyse` lifecycle: cleared in both consumers | Verified — cleared at 1962 (PM) and 5148 (SA); consumed correctly per page |
| `_pdf_cache_path` confusion for docx bytes | Real root cause of C5 bugs above, not a standalone bug |

---

## Summary table

| # | Class | File:Line | Severity | Short description |
|---|---|---|---|---|
| 1 | C5 | app.py:2826 | **crash** | Comparison page: `extract_text_from_pdf` on docx bytes — no try/except, propagates |
| 2 | C5 | app.py:1641 | silent-failure | PM no-text recovery: same assumption, swallowed, user gets wrong error message |
| 3 | C2 | app.py:1934 | silent-failure | PM Re-Analyse: `lib_add` bare except hides any save failure |
| 4 | C2 | app.py:5088 | silent-failure | SA Re-Analyse: same |
| 5 | C2 | app.py:5380 | silent-failure | Fresh upload: same — exact tonight's `_is_docx` incident class |
| 6 | C2 | app.py:523 | silent-failure | Supabase save: bare except, zero observability |
| 7 | C2 | app.py:574,579 | silent-failure | `detect_flags` / `_calc_summary_metrics`: silent data omission from cache payload |
| 8 | C1 | app.py:1583,1598,1814,1821,1838 | cosmetic | `entry["company_name"]` raw in sidebar — renders "None" |
| 9 | C1 | app.py:1610,1642,1850,1866 | cosmetic | `entry["company_name"]` raw in session state dicts — propagates "None" |
| 10 | C6 | app.py:1596,1744 | cosmetic | `confirm_reanalyse` stale after loading a different entry |
