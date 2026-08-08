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


@responses.activate
def test_issue_events_without_environment_calls_expected_endpoint(sentry_api):
    url = BASE_URL + "issues/123/events/"
    responses.add(responses.GET, url, json=[])
    sentry_api.issue_events("123")
    assert responses.calls[0].request.url == url


@responses.activate
def test_issue_events_with_environment_builds_valid_query_string(sentry_api):
    url = BASE_URL + "issues/123/events/?environment=production&sort=date"
    responses.add(responses.GET, url, json=[])
    sentry_api.issue_events("123", environment="production")
    assert responses.calls[0].request.url == url


@responses.activate
def test_issue_release_without_environment_calls_expected_endpoint(sentry_api):
    url = BASE_URL + "issues/123/current-release/"
    responses.add(
        responses.GET,
        url,
        json={"currentRelease": {"release": {"version": "1.0.0"}}},
    )
    release = sentry_api.issue_release("123")
    assert responses.calls[0].request.url == url
    assert release == "1.0.0"


@responses.activate
def test_issue_release_with_environment_calls_expected_endpoint(sentry_api):
    url = BASE_URL + "issues/123/current-release/?environment=production"
    responses.add(
        responses.GET,
        url,
        json={"currentRelease": {"release": {"version": "1.0.0"}}},
    )
    release = sentry_api.issue_release("123", environment="production")
    assert responses.calls[0].request.url == url
    assert release == "1.0.0"


@responses.activate
def test_environments_calls_expected_endpoint(sentry_api):
    project = {"slug": "backend"}
    url = BASE_URL + "projects/acme/backend/environments/"
    responses.add(responses.GET, url, json=[])
    sentry_api.environments("acme", project)
    assert responses.calls[0].request.url == url


@responses.activate
def test_issues_calls_expected_endpoint(sentry_api):
    # `issues(org_slug, project, environment=None, age="24h")` -- project is a
    # dict (not a slug string), and the default use_legacy_api=True keeps the
    # project-scoped, now-deprecated endpoint's exact current URL shape.
    project = {"slug": "backend", "id": "123"}
    url = BASE_URL + "projects/acme/backend/issues/?project=123&sort=date&query=age%3A-24h"
    responses.add(responses.GET, url, json=[])
    sentry_api.issues("acme", project)
    assert responses.calls[0].request.url == url


@responses.activate
def test_issues_with_legacy_api_disabled_calls_organization_scoped_endpoint():
    # Sentry's live docs mark the project-scoped issues endpoint deprecated in
    # favor of the Organization Issues endpoint. use_legacy_api=False opts in.
    sentry_api = SentryAPI(base_url=BASE_URL, auth_token="test-token", use_legacy_api=False)
    project = {"slug": "backend", "id": "123"}
    url = BASE_URL + "organizations/acme/issues/?project=123&sort=date&query=age%3A-24h"
    responses.add(responses.GET, url, json=[])
    sentry_api.issues("acme", project)
    assert responses.calls[0].request.url == url
