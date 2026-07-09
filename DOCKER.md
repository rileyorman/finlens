# Running FinLens in Docker

Containerized deployment of FinLens. The app runs as Streamlit on port 8501,
reachable at **http://localhost:8501** (host loopback only).

## Prerequisites

- Docker Desktop running.
- Secrets available in the shell. Secrets are **never** stored in the image or
  a plaintext file — they are read from the shell environment at launch, the
  same SOPS-backed pattern as `run.bat`.

## Start (regular PowerShell, from the project root)

```powershell
cd "C:\Users\riley\OneDrive\Documents\Python Project\finlens"; Import-Secrets; docker compose up -d --build
```

`Import-Secrets` decrypts the SOPS store into the PowerShell session;
`docker compose` interpolates each `${VAR}` from that session. The `--build`
flag is only needed the first time or after changing code/deps.

Then open **http://localhost:8501**.

## Common commands (regular PowerShell)

```powershell
docker compose logs -f finlens      # tail logs
docker compose ps                   # status + health
docker compose restart finlens      # restart
docker compose down                 # stop and remove the container
docker compose up -d --build        # rebuild after code/requirements changes
```

## What's passed in

| Variable | Purpose |
|----------|---------|
| `ANTHROPIC_API_KEY` | **Required** — Claude analysis/extraction |
| `GEMINI_API_KEY` | Gemini second-extractor cross-check |
| `FISCAL_AI_KEY` | Fiscal.ai profile / shares / logo |
| `FMP_API_KEY` | Financial Modeling Prep |
| `SUPABASE_URL`, `SUPABASE_KEY` | Optional Supabase persistence |
| `APP_PASSWORD` | App password gate (defaults if unset) |
| `STREAMLIT_ENV` | Set to `dev` to bypass the password gate |

## Data persistence

App data (filing library, analysis cache, integrity log — everything under
`FINLENS_DATA_DIR`) lives in the named Docker volume **`finlens-data`**, mounted
at `/data` in the container. It survives `docker compose down` and rebuilds.

```powershell
docker volume inspect finlens_finlens-data     # find the data on disk
docker volume rm finlens_finlens-data          # wipe app data (destructive)
```

## Security notes

- The port is published to `127.0.0.1:8501` only — the container is not exposed
  to the local network, preserving the app's localhost-only posture.
- `.streamlit/secrets.toml`, `.env`, `venv/`, caches, and generated reports are
  excluded from the image via `.dockerignore`.
- Runs as a non-root user (`appuser`) inside the container.

## Notes

- This is a **Linux** container. `config.py` places the runtime cache at
  `/tmp/finlens_cache` on non-Windows and the library under `/data`
  (`FINLENS_DATA_DIR`). The Windows/Avast SSL workaround in
  `modules/claude_analyzer.py` is inert on Linux (it loads the system trust
  store, which is standard there).
- The image targets Python 3.11 to match CI (CLAUDE.md: "CI Python Version is
  Authoritative").
