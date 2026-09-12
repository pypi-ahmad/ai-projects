from obs_legacy.redact import redact


def test_redact_returns_hash_and_preview() -> None:
    text = "a" * 200
    digest, preview = redact(text)
    assert digest is not None
    assert len(digest) == 64
    assert preview == "a" * 120


def test_redact_none() -> None:
    assert redact(None) == (None, None)


def test_redact_short_text_preview_unchanged() -> None:
    digest, preview = redact("hello")
    assert preview == "hello"
    assert digest is not None
