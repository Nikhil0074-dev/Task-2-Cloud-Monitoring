import pytest

from cloudmon.timeutil import format_duration, parse_iso, to_iso, utc_now, utc_now_iso


def test_iso_roundtrip_and_format():
    s = utc_now_iso()
    assert s.endswith("Z") and len(s) == 24
    assert to_iso(parse_iso(s)) == s


def test_parse_without_fraction():
    assert parse_iso("2026-01-01T00:00:05Z").second == 5


def test_parse_invalid():
    with pytest.raises(ValueError):
        parse_iso("yesterday")


def test_utc_now_is_aware():
    assert utc_now().tzinfo is not None


@pytest.mark.parametrize("sec, text", [
    (0, "0s"), (45, "45s"), (125, "2m 05s"), (3720, "1h 02m"), (3 * 86400 + 4 * 3600, "3d 04h"), (-5, "0s"),
])
def test_format_duration(sec, text):
    assert format_duration(sec) == text
