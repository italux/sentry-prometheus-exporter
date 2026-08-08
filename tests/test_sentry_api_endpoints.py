"""Tests for Sentry API endpoints audit."""

import pytest
import responses

from libs.sentry import SentryAPI

BASE_URL = "https://sentry.example.com/api/0/"


@pytest.fixture
def sentry_api():
    return SentryAPI(base_url=BASE_URL, auth_token="test-token")
