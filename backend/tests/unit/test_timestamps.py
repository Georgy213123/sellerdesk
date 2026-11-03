"""FR-03 / US-01: время площадок приводится к UTC, лента сортируется по реальному времени."""

from datetime import UTC, datetime, timedelta, timezone

from app.marketplaces.base import parse_marketplace_ts
from app.marketplaces.mock import MSK, _fmt
from app.models import Marketplace


def test_utc_z_suffix():
    assert parse_marketplace_ts("2026-10-30T09:15:00Z", MSK) == datetime(2026, 10, 30, 9, 15, tzinfo=UTC)


def test_explicit_offset_is_respected():
    assert parse_marketplace_ts("2026-10-30T12:20:00+03:00", MSK) == datetime(2026, 10, 30, 9, 20, tzinfo=UTC)


def test_naive_uses_marketplace_default_zone():
    assert parse_marketplace_ts("2026-10-30T12:05:00", MSK) == datetime(2026, 10, 30, 9, 5, tzinfo=UTC)


def test_result_is_always_aware_utc():
    ts = parse_marketplace_ts("2026-10-30T12:05:00+05:00", timezone(timedelta(hours=-4)))
    assert ts.tzinfo is UTC


def test_bug02_order_across_marketplaces_follows_real_time():
    """BUG-02: с отброшенной зоной сообщение Ozon (12:20 MSK = 09:20 UTC) оказывалось
    «позже» сообщения Wildberries в 09:30 UTC, и лента показывала их не в том порядке."""
    wb = parse_marketplace_ts("2026-10-30T09:30:00Z", MSK)
    oz = parse_marketplace_ts("2026-10-30T12:20:00+03:00", MSK)
    ym = parse_marketplace_ts("2026-10-30T12:25:00", MSK)
    ordered = sorted([("oz", oz), ("wb", wb), ("ym", ym)], key=lambda x: x[1], reverse=True)
    assert [k for k, _ in ordered] == ["wb", "ym", "oz"]


def test_mock_formats_roundtrip_for_every_marketplace():
    moment = datetime(2026, 10, 30, 7, 45, tzinfo=UTC)
    for code in Marketplace:
        assert parse_marketplace_ts(_fmt(code, moment), MSK) == moment
