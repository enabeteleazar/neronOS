from pathlib import Path

from modules.context import neron_context


def test_has_neron_context_true_when_non_empty_file(monkeypatch, tmp_path):
    neron_file = tmp_path / "NERON.md"
    neron_file.write_text("Contexte global", encoding="utf-8")

    monkeypatch.setattr(neron_context, "NERON_CONTEXT_PATH", Path(neron_file))
    monkeypatch.setattr(neron_context, "_cached_context", None)
    monkeypatch.setattr(neron_context, "_cached_at", 0.0)

    assert neron_context.has_neron_context(force_reload=True) is True


def test_has_neron_context_false_when_file_missing(monkeypatch, tmp_path):
    neron_file = tmp_path / "MISSING_NERON.md"

    monkeypatch.setattr(neron_context, "NERON_CONTEXT_PATH", Path(neron_file))
    monkeypatch.setattr(neron_context, "_cached_context", None)
    monkeypatch.setattr(neron_context, "_cached_at", 0.0)

    assert neron_context.has_neron_context(force_reload=True) is False
