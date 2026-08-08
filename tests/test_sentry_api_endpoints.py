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
