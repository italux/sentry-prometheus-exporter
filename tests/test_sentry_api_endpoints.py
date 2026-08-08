"""Tests for Sentry API endpoints audit."""

import pytest
import responses

from libs.sentry import SentryAPI

BASE_URL = "https://sentry.example.com/api/0/"


@pytest.fixture
def sentry_api():
    return SentryAPI(base_url=BASE_URL, auth_token="test-token")


@responses.activate
def test_organizations_calls_expected_endpoint(sentry_api):
    responses.add(responses.GET, BASE_URL + "organizations/", json=[])
    sentry_api.organizations()
    assert responses.calls[0].request.url == BASE_URL + "organizations/"


@responses.activate
def test_projects_calls_expected_endpoint(sentry_api):
    url = BASE_URL + "organizations/acme/projects/?all_projects=1"
    responses.add(responses.GET, url, json=[])
    sentry_api.projects("acme")
    assert responses.calls[0].request.url == url


@responses.activate
def test_get_project_calls_expected_endpoint(sentry_api):
    url = BASE_URL + "projects/acme/backend/"
    responses.add(responses.GET, url, json={})
    sentry_api.get_project("acme", "backend")
    assert responses.calls[0].request.url == url


@responses.activate
def test_project_stats_calls_expected_endpoint(sentry_api):
    # project_stats(org_slug, project_slug) internally issues one GET per stat
    # name (received, rejected, blacklisted) with since/until timestamps, so
    # we pin the path + query param shape rather than a single exact URL.
    base = BASE_URL + "projects/acme/backend/stats/"
    responses.add(responses.GET, base, json=[])
    sentry_api.project_stats("acme", "backend")

    called_urls = [call.request.url for call in responses.calls]
    assert len(called_urls) == 3
    for stat in ("received", "rejected", "blacklisted"):
        assert any(
            url.startswith(base) and "stat={0}".format(stat) in url and "since=" in url and "until=" in url
            for url in called_urls
        ), "expected a call for stat={0}, got: {1}".format(stat, called_urls)
