"""Tests for Sentry API endpoints audit."""

import pytest
import responses
from tests import BASE_URL, sentry_api


class TestSentryAPIEndpoints:
    """Test suite for auditing Sentry API endpoints used by the exporter."""

    @pytest.fixture
    def api_client(self):
        """Provide a test SentryAPI instance."""
        return sentry_api()

    @responses.activate
    def test_api_base_url(self, api_client):
        """Test that API client uses correct base URL."""
        assert api_client.base_url == BASE_URL

    @responses.activate
    def test_api_auth_token(self, api_client):
        """Test that API client has auth token."""
        # Token is stored as private _SentryAPI__token
        assert api_client._SentryAPI__token == "test-token"
