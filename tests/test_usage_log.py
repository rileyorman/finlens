"""Regression tests for token-usage telemetry persistence.

log_cache_usage() must append one JSONL record per Claude call to
usage_log.jsonl so the Sunday cost audit has real per-tier data. All I/O here
uses tmp_path via monkeypatch — never the real ~/.finlens usage log.
"""
import json

from modules import claude_analyzer as ca


class _FakeUsage:
    """Stand-in for an Anthropic response.usage object."""

    cache_read_input_tokens = 1200
    cache_creation_input_tokens = 300
    input_tokens = 50
    output_tokens = 800


def test_log_cache_usage_appends_record(tmp_path, monkeypatch):
    log_path = tmp_path / "usage_log.jsonl"
    monkeypatch.setattr(ca, "USAGE_LOG_PATH", log_path)

    ret = ca.log_cache_usage("analyze_financials", _FakeUsage(), "claude-sonnet-5")

    # returned dict stays backward-compatible for the print() call sites
    assert ret["call"] == "analyze_financials"
    assert ret["model"] == "claude-sonnet-5"
    assert ret["output_tokens"] == 800

    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["call"] == "analyze_financials"
    assert rec["model"] == "claude-sonnet-5"
    assert rec["cache_read"] == 1200
    assert rec["cache_write"] == 300
    assert rec["input_tokens"] == 50
    assert rec["output_tokens"] == 800
    assert rec["ts"].endswith("+00:00")  # UTC ISO timestamp


def test_log_cache_usage_appends_not_overwrites(tmp_path, monkeypatch):
    log_path = tmp_path / "usage_log.jsonl"
    monkeypatch.setattr(ca, "USAGE_LOG_PATH", log_path)

    ca.log_cache_usage("analyze_financials", _FakeUsage(), "claude-sonnet-5")
    ca.log_cache_usage("analyze_summary", _FakeUsage(), "claude-haiku-4-5-20251001")

    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[1])["call"] == "analyze_summary"


def test_log_cache_usage_missing_model_is_none(tmp_path, monkeypatch):
    log_path = tmp_path / "usage_log.jsonl"
    monkeypatch.setattr(ca, "USAGE_LOG_PATH", log_path)

    ret = ca.log_cache_usage("legacy_caller", _FakeUsage())  # no model arg
    assert ret["model"] is None
    assert json.loads(log_path.read_text(encoding="utf-8").strip())["model"] is None


class _FakeMessage:
    usage = _FakeUsage()
    model = "claude-sonnet-5"
    stop_reason = "end_turn"


class _FakeStream:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return _FakeMessage()


class _FakeClient:
    class messages:  # noqa: N801 - mirrors the SDK attribute shape
        @staticmethod
        def stream(**_kwargs):
            return _FakeStream()


def test_sedar_call_claude_persists_usage(tmp_path, monkeypatch):
    """Sunday-audit 2026-07-12 rec #4: the targeted extractors (statement /
    hedging / MD&A passes through sedar_extractor._call_claude) must write
    usage records — they were invisible to the cost audit before this."""
    import sedar_extractor as se

    log_path = tmp_path / "usage_log.jsonl"
    monkeypatch.setattr(ca, "USAGE_LOG_PATH", log_path)

    msg = se._call_claude(_FakeClient(), "prompt", call_name="extract_mda_metrics")
    assert msg.stop_reason == "end_turn"  # message passthrough unchanged

    rec = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert rec["call"] == "extract_mda_metrics"
    assert rec["model"] == "claude-sonnet-5"
    assert rec["output_tokens"] == 800


def test_sedar_call_claude_default_call_name(tmp_path, monkeypatch):
    import sedar_extractor as se

    log_path = tmp_path / "usage_log.jsonl"
    monkeypatch.setattr(ca, "USAGE_LOG_PATH", log_path)

    se._call_claude(_FakeClient(), "prompt")
    rec = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert rec["call"] == "sedar_extract_statements"


def test_usage_write_failure_never_raises(tmp_path, monkeypatch):
    # Point the log at a path whose parent cannot be created (a file, not a dir)
    # to force an I/O error; telemetry must swallow it and still return the dict.
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file, not a directory", encoding="utf-8")
    monkeypatch.setattr(ca, "USAGE_LOG_PATH", blocker / "sub" / "usage_log.jsonl")

    ret = ca.log_cache_usage("analyze_financials", _FakeUsage(), "claude-sonnet-5")
    assert ret["call"] == "analyze_financials"  # analysis path unbroken
