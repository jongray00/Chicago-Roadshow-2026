"""Outbound destination normalization: fix sloppy input, reject nonsense."""
import main


def test_already_e164_passthrough():
    assert main._normalize_e164("+15204363368") == "+15204363368"


def test_bare_10_digits_defaults_to_north_america():
    assert main._normalize_e164("5204363368") == "+15204363368"


def test_dashes_parens_spaces_are_cleaned():
    assert main._normalize_e164("(520) 436-3368") == "+15204363368"
    assert main._normalize_e164("520.436.3368") == "+15204363368"


def test_leading_1_without_plus():
    assert main._normalize_e164("15204363368") == "+15204363368"


def test_us_international_prefix_011_stripped():
    assert main._normalize_e164("011 44 20 7946 0000") == "+442079460000"


def test_intl_number_with_plus_kept():
    assert main._normalize_e164("+44 20 7946 0000") == "+442079460000"


def test_too_short_is_rejected():
    assert main._normalize_e164("12345") == ""


def test_empty_is_rejected():
    assert main._normalize_e164("") == ""
    assert main._normalize_e164("abc") == ""
