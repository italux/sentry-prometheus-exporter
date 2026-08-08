"""Test fixtures and utilities for Sentry API audit tests."""

from libs.sentry import SentryAPI

BASE_URL = "https://sentry.example.com/api/0/"


def sentry_api():
    """Create a test SentryAPI instance."""
    return SentryAPI(base_url=BASE_URL, auth_token="test-token")
