from __future__ import annotations

from typing import TYPE_CHECKING

from guardrails import pii

if TYPE_CHECKING:
    from pathlib import Path


def test_detects_and_redacts_email() -> None:
    text = "contact me at jane.doe@example.com please"
    finding = pii.detect(text)
    assert [s.type for s in finding.spans] == ["email"]
    assert pii.redact(text, finding) == "contact me at [EMAIL] please"


def test_same_value_twice_gets_same_placeholder() -> None:
    assert pii.redact("from a@b.com to a@b.com") == "from [EMAIL] to [EMAIL]"


def test_two_distinct_values_get_distinguishing_placeholders() -> None:
    assert pii.redact("from a@b.com to c@d.com") == "from [EMAIL_1] to [EMAIL_2]"


def test_detects_valid_credit_card_via_luhn() -> None:
    finding = pii.detect("card 4111 1111 1111 1111 exp 12/30")
    assert [s.type for s in finding.spans] == ["credit_card"]


def test_rejects_invalid_credit_card_candidate() -> None:
    # same length as a card number but fails the Luhn check
    finding = pii.detect("order id 1234 5678 9012 3456 confirmed")
    assert finding.spans == []


def test_detects_ip_address() -> None:
    finding = pii.detect("server at 192.168.1.10 responded")
    assert [s.type for s in finding.spans] == ["ip_address"]


def test_detects_indian_mobile_number() -> None:
    finding = pii.detect("call me on 9876543210 today")
    assert [s.type for s in finding.spans] == ["phone"]


def test_detects_known_prefixed_api_key() -> None:
    finding = pii.detect("key: AKIAIOSFODNN7EXAMPLE")
    assert [s.type for s in finding.spans] == ["api_key"]


def test_detects_high_entropy_token_without_known_prefix() -> None:
    finding = pii.detect("token=Xk29fQzL8mP3vRtN7wYb2")
    assert [s.type for s in finding.spans] == ["api_key"]


def test_plain_prose_is_not_flagged_as_high_entropy_token() -> None:
    finding = pii.detect("this is just a perfectly ordinary sentence with no secrets in it")
    assert finding.spans == []


def test_aadhaar_off_by_default() -> None:
    # phone disabled too: a bare 12-digit run also satisfies the generic phone
    # regex's flexible digit-count window, which would otherwise mask what
    # this test is actually checking (the aadhaar toggle).
    config = {**pii.DEFAULT_PII_CONFIG, "phone": False}
    assert pii.detect("my aadhaar is 234567890123", config).spans == []


def test_aadhaar_detected_as_possible_when_enabled() -> None:
    config = {**pii.DEFAULT_PII_CONFIG, "aadhaar": True}
    finding = pii.detect("my aadhaar is 2345 6789 0123", config)
    assert [s.type for s in finding.spans] == ["aadhaar_possible"]


def test_pan_off_by_default() -> None:
    assert pii.detect("my pan is ABCPZ1234C").spans == []


def test_pan_detected_as_possible_when_enabled() -> None:
    config = {**pii.DEFAULT_PII_CONFIG, "pan": True}
    finding = pii.detect("my pan is ABCPZ1234C", config)
    assert [s.type for s in finding.spans] == ["pan_possible"]


def test_type_disabled_via_config_is_not_detected() -> None:
    config = {**pii.DEFAULT_PII_CONFIG, "email": False}
    assert pii.detect("mail me at a@b.com", config).spans == []


def test_no_raw_value_in_span_replacements() -> None:
    finding = pii.detect("email a@b.com and card 4111 1111 1111 1111")
    for span in finding.spans:
        assert span.replacement is not None
        assert "@" not in span.replacement
        assert "4111" not in span.replacement


def test_original_values_absent_from_redacted_output_when_enabled() -> None:
    text = "email a@b.com, card 4111 1111 1111 1111, ip 10.0.0.5"
    redacted = pii.redact(text)
    assert "a@b.com" not in redacted
    assert "4111" not in redacted
    assert "10.0.0.5" not in redacted


def test_plain_text_has_no_findings() -> None:
    assert pii.detect("what is the weather like today?").spans == []


def test_load_pii_config_missing_file_returns_defaults(tmp_path: Path) -> None:
    config = pii.load_pii_config(tmp_path / "does-not-exist.yaml")
    assert config == pii.DEFAULT_PII_CONFIG


def test_load_pii_config_overrides_only_given_keys(tmp_path: Path) -> None:
    config_file = tmp_path / "pii.yaml"
    config_file.write_text("email: false\naadhaar: true\n", encoding="utf-8")
    config = pii.load_pii_config(config_file)
    assert config["email"] is False
    assert config["aadhaar"] is True
    assert config["phone"] == pii.DEFAULT_PII_CONFIG["phone"]
