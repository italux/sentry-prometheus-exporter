"""Tests for the stats_v2 API call and SentryStatsV2Collector."""

from datetime import datetime
from unittest import mock

import pytest
import responses

from helpers.prometheus import SentryStatsV2Collector
from libs.sentry import SentryAPI

BASE_URL = "https://sentry.example.com/api/0/"
PROJECTS_URL = BASE_URL + "organizations/acme/projects/?all_projects=1"
STATS_URL = BASE_URL + "organizations/acme/stats_v2/"

STATS_RESPONSE = {
    "groups": [
        {"by": {"project": 1, "outcome": "accepted"}, "totals": {"sum(quantity)": 42}},
        {"by": {"project": 1, "outcome": "rate_limited"}, "totals": {"sum(quantity)": 7}},
        {"by": {"project": 2, "outcome": "accepted"}, "totals": {"sum(quantity)": 3}},
    ]
}
PROJECTS_RESPONSE = [
    {"id": "1", "slug": "backend", "name": "backend", "status": "active"},
    {"id": "2", "slug": "frontend", "name": "frontend", "status": "active"},
]


@pytest.fixture
def sentry_api():
    return SentryAPI(base_url=BASE_URL, auth_token="test-token")


@pytest.fixture(autouse=True)
def reset_collector_cache():
    SentryStatsV2Collector._cached_data = None
    SentryStatsV2Collector._cache_timestamp = None
    SentryStatsV2Collector._last_success_ts = None
    SentryStatsV2Collector._consecutive_failures = 0
    SentryStatsV2Collector._stale_logged = False
    yield


def add_stats_responses():
    responses.add(responses.GET, STATS_URL, json=STATS_RESPONSE)
    responses.add(responses.GET, PROJECTS_URL, json=PROJECTS_RESPONSE)


@responses.activate
def test_org_stats_v2_groups_by_project_slug(sentry_api):
    add_stats_responses()
    result = sentry_api.org_stats_v2("acme", stats_period="7d", categories=["error"])

    url = responses.calls[0].request.url
    assert "statsPeriod=7d" in url and "category=error" in url
    assert "groupBy=project" in url and "groupBy=outcome" in url
    assert result == {"backend": {"accepted": 42, "rate_limited": 7}, "frontend": {"accepted": 3}}


@responses.activate
def test_org_stats_v2_start_end_override_period(sentry_api):
    add_stats_responses()
    sentry_api.org_stats_v2("acme", start="2026-09-25T00:00:00Z", end="2026-09-29T00:00:00Z")

    url = responses.calls[0].request.url
    assert "start=2026-09-25T00:00:00Z" in url and "end=2026-09-29T00:00:00Z" in url
    assert "statsPeriod" not in url


@pytest.mark.parametrize(
    "now, expected_start",
    [
        (datetime(2026, 9, 29, 12, 0), "2026-09-25T00:00:00Z"),
        (datetime(2026, 9, 10, 12, 0), "2026-08-25T00:00:00Z"),
        (datetime(2026, 1, 3, 12, 0), "2025-12-25T00:00:00Z"),
    ],
)
def test_billing_period_start(sentry_api, now, expected_start):
    collector = SentryStatsV2Collector(sentry_api, "acme", billing_cycle_day=25)
    with mock.patch("helpers.prometheus.datetime") as fake_datetime:
        fake_datetime.utcnow.return_value = now
        start, end = collector._get_billing_period()
    assert start == expected_start
    assert end == now.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_billing_period_disabled(sentry_api):
    assert SentryStatsV2Collector(sentry_api, "acme")._get_billing_period() == (None, None)


def samples_by_name(collector):
    samples = {}
    for family in collector.collect():
        for sample in family.samples:
            samples.setdefault(sample.name, []).append(sample)
    return samples


@responses.activate
def test_collect_serves_refreshed_cache_without_calling_api(sentry_api):
    add_stats_responses()
    collector = SentryStatsV2Collector(sentry_api, "acme")
    collector._refresh_once()
    calls_after_refresh = len(responses.calls)

    samples = samples_by_name(collector)

    assert len(responses.calls) == calls_after_refresh
    accepted = {s.labels["project_slug"]: s.value for s in samples["sentry_accepted_events"]}
    assert accepted == {"backend": 42, "frontend": 3}
    quota = {s.labels["project_slug"]: s.value for s in samples["sentry_quota_exceeded"]}
    assert quota == {"backend": 7}
    assert len(samples["sentry_stats_v2_last_success_timestamp_seconds"]) == 1


@responses.activate
def test_failed_refresh_keeps_last_good_data(sentry_api):
    add_stats_responses()
    collector = SentryStatsV2Collector(sentry_api, "acme")
    collector._refresh_once()

    responses.replace(responses.GET, STATS_URL, status=500)
    collector._refresh_once()

    assert SentryStatsV2Collector._consecutive_failures == 1
    accepted = {
        s.labels["project_slug"]: s.value
        for s in samples_by_name(collector)["sentry_accepted_events"]
    }
    assert accepted == {"backend": 42, "frontend": 3}


def test_collect_before_first_refresh_is_empty(sentry_api):
    samples = samples_by_name(SentryStatsV2Collector(sentry_api, "acme"))
    assert samples == {}
