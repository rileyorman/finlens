"""ask_fable.py — run a FinLens design session with Fable via the API.

The architect seat of the three-agent pipeline (Fable designs, Sterling
implements, Claude Code reviews/commits, Riley ratifies). Fable-in-CLI
access ended 2026-07-07; this keeps the design-session capability by
sending a design brief to claude-fable-5 and saving the ruling to disk.

Usage (regular PowerShell, from the repo root):

    .\\venv\\Scripts\\python.exe scripts\\ask_fable.py docs\\design_briefs\\2026-07-07-sector-aware-red-flags.md

The response lands in docs/design_sessions/<brief-name>__fable.md.
Cost: a design session with a few thousand words of brief typically runs
a few dollars on the Fable tier — the brief file IS the spend control:
keep evidence tight and relevant.
"""

import ssl
import sys
from datetime import datetime
from pathlib import Path

import anthropic
import httpx
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
SESSIONS_DIR = REPO_ROOT / "docs" / "design_sessions"

# claude-fable-5 is a verified live model ID (CLAUDE.md "Valid Anthropic
# Model IDs") — do not "correct" it from training-data model lists.
FABLE_MODEL = "claude-fable-5"
MAX_OUTPUT_TOKENS = 16_000

SYSTEM_PROMPT = """You are Fable, the architect seat of the FinLens three-agent \
pipeline (Fable designs -> Sterling implements -> Claude Code reviews and \
commits -> Riley ratifies every ruling).

FinLens is an AI-powered investment analysis platform whose moat is the Data \
Integrity Engine: honest failure beats confident wrong numbers, silent \
behavior is never acceptable, and every judgment call is recorded in a \
casebook with its rationale.

You will receive a design brief containing a question, an evidence pack, and \
constraints. Respond in the FinLens design-session format:

1. RULINGS — numbered, each with a recommendation and the WHY (rationale \
grounded in the evidence supplied; name the evidence you relied on).
2. SPEC FOR THE IMPLEMENTER — module boundaries, function signatures, data \
shapes, and behavior in edge cases. Spec only: do NOT write implementation code.
3. ACCEPTANCE TESTS — concrete, pinnable test cases (inputs -> expected \
outputs) the implementation must pass.
4. OPEN QUESTIONS — anything the evidence cannot settle, framed as decisions \
for Riley. Do not paper over gaps.

House rules: integrity-first (no silent suppression or silent fallbacks — \
absence and suppression must be visible); deterministic over model-driven \
where possible; honest 'this evidence is n=1' framing; if the brief's \
evidence seems wrong or incomplete, SAY SO rather than designing around it \
silently."""


def _build_client(api_key: str) -> anthropic.Anthropic:
    # Known-good Windows SSL pattern (Avast HTTPS inspection) — same as
    # modules/claude_analyzer.py. Do not swap for certifi/create_default_context
    # without retesting on this machine (CLAUDE.md Windows SSL note).
    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ssl_ctx.load_default_certs()
    ssl_ctx.check_hostname = True
    return anthropic.Anthropic(
        api_key=api_key,
        http_client=httpx.Client(verify=ssl_ctx, trust_env=False),
    )


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/ask_fable.py <path-to-design-brief.md>")
        return 1

    brief_path = Path(sys.argv[1])
    if not brief_path.exists():
        print(f"Brief not found: {brief_path}")
        return 1

    brief_text = brief_path.read_text(encoding="utf-8")

    load_dotenv(REPO_ROOT / ".env")
    import os

    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        print("ANTHROPIC_API_KEY not found — run under sops exec-env or Import-Secrets first (no .env since the 2026-07-08 SOPS migration).")
        return 1

    client = _build_client(api_key)
    print(f"Sending brief to {FABLE_MODEL} ({len(brief_text):,} chars)...")

    try:
        # Streaming keeps long design responses reliable at this output budget.
        with client.messages.stream(
            model=FABLE_MODEL,
            max_tokens=MAX_OUTPUT_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": brief_text}],
        ) as stream:
            message = stream.get_final_message()
    except Exception as e:
        print(f"API call failed: {e}")
        return 1

    response_text = "".join(
        block.text for block in message.content if block.type == "text"
    )

    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d")
    out_path = SESSIONS_DIR / f"{brief_path.stem}__fable.md"
    header = (
        f"# Fable design session — {brief_path.name}\n\n"
        f"- **Date:** {stamp}\n"
        f"- **Model:** {FABLE_MODEL}\n"
        f"- **Tokens:** {message.usage.input_tokens:,} in / "
        f"{message.usage.output_tokens:,} out\n"
        f"- **Status:** UNRATIFIED — rulings take effect only after Riley "
        f"ratifies them (casebook rule)\n\n---\n\n"
    )
    out_path.write_text(header + response_text, encoding="utf-8")

    print(f"Design session saved: {out_path}")
    print(
        f"Tokens: {message.usage.input_tokens:,} in / "
        f"{message.usage.output_tokens:,} out"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
