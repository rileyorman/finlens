Walk the FinLens pre-release deployment checklist in order. Source: CLAUDE.md "Deployment Checklist" (synced 2026-07-10). Steps 1–10 below are transcribed verbatim from that section. Any CC-executable verification or prompt added around a step is labeled [ADDITION] and is not part of the original source. If this file and CLAUDE.md ever disagree, CLAUDE.md wins — flag the drift and re-sync.

Source preamble (verbatim): **Secrets note (since 2026-07-08):** there is no plaintext `.env` — API keys come from the encrypted SOPS store, so the app must run with secrets injected: `Import-Secrets` then the command, or `sops exec-env %USERPROFILE%\.secrets\secrets.enc.env "<cmd>"`. **The test suite needs NO secrets (since 2026-07-09)** — see CLAUDE.md for the full note; run `python test_run.py` manually (with secrets) when the live smoke test is wanted.

Do not present step 8 until Riley has explicitly confirmed steps 1–7 are complete.

---

**Step 1 — Confirm work is on `dev`.**
[ADDITION: run `git branch --show-current` and confirm the output is `dev`. If not, stop and tell Riley which branch is active.]

**Step 2 — Run `python -m py_compile app.py`.**
[ADDITION: run `.\venv\Scripts\python.exe -m py_compile app.py` and report pass or fail. If it fails, stop — do not continue.]

**Step 3 — Start Streamlit locally (secrets injected) and confirm the app loads.**
[ADDITION: first probe `http://localhost:8501/_stcore/health`. If an instance is already running and healthy, report the 200 and confirm with Riley that it serves the current working tree. Otherwise ask Riley: "Please start the app (`.\run.bat`, or `Import-Secrets` then the standard launch) and confirm it loads — check the terminal output for the Local URL, as the port may be 8501, 8502, or 8503 if multiple Streamlit instances are running. Reply 'loaded' to continue." Once Riley confirms, re-probe health as server-side evidence.]

**Step 4 — Run the full suite: `python -m pytest -q` — expect green (no secrets needed since 2026-07-09; see the secrets note above).**
[ADDITION: run `.\venv\Scripts\python.exe -m pytest -q` and report the pass count. If not green, stop — do not continue.]

**Step 5 — Test the affected user flow.**
[This step belongs to Riley — CC cannot perform visual testing alone. ADDITION: before asking, identify the affected flow(s) concretely — run `git log main..dev --oneline` and inspect changed files to name exactly what Riley should look at on screen, in plain language (no bare CB IDs without explanation). If a flow was already live-evidenced on the identical working tree, say so and propose a proportionate lighter check (e.g. the UI element renders). Ask: "Reply 'flow confirmed' to continue."]

**Step 6 — Confirm `.streamlit/secrets.toml` is not committed (the `.env` is gone/gitignored; SOPS store lives outside the repo).**
[ADDITION: run `git status --short` and `git diff --cached --name-only`. Verify neither `.streamlit/secrets.toml` nor any `.env` appears. Report findings.]

**Step 7 — Confirm generated reports and PDFs are not committed.**
[ADDITION: run `git status --short` and confirm no `.xlsx`, `.docx`, or `.pdf` files are staged or untracked-and-about-to-be-added. Report findings.]

---

**Confirmation gate — all seven steps must pass before merge.**
Ask Riley: "Steps 1–7 are complete and confirmed. Ready to merge to main? Reply 'merge' to continue, or 'stop' to abort."

If Riley replies 'stop' or anything other than 'merge', end the command here and report which steps need attention.

---

**Step 8 — Merge `dev` into `main` only when stable (`git merge --no-ff dev`).**
[ADDITION: before merging, verify what the merge actually carries with `git log main..dev --oneline` — handoff "dev is ahead" notes can be stale (2026-07-10 precedent: CB-028 was already on main) — and write the merge message to describe only what actually moves. Run `git checkout main; git merge --no-ff dev`. Then RE-RUN the full suite on merged main and report the result before proceeding. Then `git checkout dev`, and push both branches (`git push origin main dev`) per standing precedent unless Riley says otherwise. Report the merge commit hash.]

**Step 9 — If using Windows service deployment (NSSM), restart the FinLens service and pass secrets via the service environment (the service can't run `Import-Secrets`). Not installed on the 2026-07 ThinkPad — that machine relaunches the app directly.**
[ADDITION: on the ThinkPad, if the running app was launched from the same working tree whose content just merged, say so — no relaunch needed. Otherwise remind Riley to relaunch via `.\run.bat` and re-probe health.]

**Step 10 — Check service/startup logs if the app does not start.**
[ADDITION: if Riley reports the app is not starting, run `Get-Content logs\service_stderr.log -Tail 50` to surface recent errors and report them.]
