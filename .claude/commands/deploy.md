Walk the FinLens pre-release deployment checklist in order. Source: CLAUDE.md "Deployment Checklist". Steps 1–9 below are transcribed verbatim from that section. Any CC-executable verification or prompt added around a step is labeled [ADDITION] and is not part of the original source.

Do not present step 7 until Riley has explicitly confirmed steps 1–6 are complete.

---

**Step 1 — Confirm work is on `dev`.**
[ADDITION: run `git branch --show-current` and confirm the output is `dev`. If not, stop and tell Riley which branch is active.]

**Step 2 — Run `python -m py_compile app.py`.**
[ADDITION: run `.\venv\Scripts\python.exe -m py_compile app.py` and report pass or fail. If it fails, stop — do not continue to step 3.]

**Step 3 — Start Streamlit locally and confirm the app loads.**
[ADDITION: this requires a running app. Ask Riley: "Please start the app (`.\run.bat` or the standard PowerShell launch) and confirm it loads — check the terminal output for the Local URL, as the port may be 8501, 8502, or 8503 if multiple Streamlit instances are running. Reply 'loaded' to continue."]

**Step 4 — Test the affected user flow.**
[This step belongs to Riley — CC cannot perform visual testing. Ask: "Please test the affected user flow and confirm it works as expected. Reply 'flow confirmed' to continue."]

**Step 5 — Confirm `.env` and `.streamlit/secrets.toml` are not committed.**
[ADDITION: run `git status --short` and `git diff --cached --name-only`. Verify neither `.env` nor `.streamlit/secrets.toml` appears. Report findings.]

**Step 6 — Confirm generated reports and PDFs are not committed.**
[ADDITION: run `git status --short` and confirm no `.xlsx`, `.docx`, or `.pdf` files are staged or untracked-and-about-to-be-added. Report findings.]

---

**Confirmation gate — all six steps must pass before merge.**
Ask Riley: "Steps 1–6 are complete and confirmed. Ready to merge to main? Reply 'merge' to continue, or 'stop' to abort."

If Riley replies 'stop' or anything other than 'merge', end the command here and report which steps need attention.

---

**Step 7 — Merge `dev` into `main` only when stable.**
[ADDITION: ask Riley for final confirmation: "About to run `git checkout main; git merge dev; git checkout dev`. Confirm? Reply 'yes'." If confirmed, run those commands using PowerShell semicolons and report the merge result and commit hash on main.]

**Step 8 — If using Windows service deployment, restart the FinLens service through the approved NSSM operations process.**
[This step is manual. Remind Riley to restart the FinLens Windows service if the app runs as a service. CC cannot drive NSSM directly without additional permissions.]

**Step 9 — Check service logs if the app does not start.**
[ADDITION: if Riley reports the app is not starting after the service restart, run `Get-Content logs\service_stderr.log -Tail 50` to surface recent errors and report them.]
