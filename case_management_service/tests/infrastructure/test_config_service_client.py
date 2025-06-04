# Unit Tests for Configuration Service Client
import asyncio
import unittest
from unittest.mock import patch, AsyncMock, MagicMock
import httpx # For HTTPStatusError
import json # Added for JSONDecodeError simulation

# Module to test
from case_management_service.infrastructure import config_service_client
from case_management_service.infrastructure.config_service_client import NotificationRule
# Import settings to manipulate it for tests
from case_management_service.app import config as app_config

class TestConfigServiceClient(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        # Store original config service URL to restore it after tests that modify it
        self.original_config_service_url = app_config.settings.CONFIG_SERVICE_URL

    def tearDown(self):
        # Restore original config service URL
        app_config.settings.CONFIG_SERVICE_URL = self.original_config_service_url

    @patch('case_management_service.infrastructure.config_service_client.httpx.AsyncClient')
    async def test_get_notification_config_success_active_rule(self, MockAsyncClient):
        # Arrange
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        # Config service returns a list with one active rule
        mock_response.json.return_value = [{
            "rule_id": "rule123", "is_active": True,
            "notification_type": "EMAIL_WELCOME", "template_id": "tpl_welcome_email"
        }]

        mock_http_client_instance = AsyncMock()
        mock_http_client_instance.post = AsyncMock(return_value=mock_response)
        MockAsyncClient.return_value.__aenter__.return_value = mock_http_client_instance

        app_config.settings.CONFIG_SERVICE_URL = "http://fake-config-service.com/api"
        event_trigger = "CASE_CREATED_KYC"
        context = {"case_type": "STANDARD"}

        # Act
        rule = await config_service_client.get_notification_config(event_trigger, context)

        # Assert
        self.assertIsNotNone(rule)
        self.assertIsInstance(rule, NotificationRule)
        self.assertEqual(rule.rule_id, "rule123")
        self.assertTrue(rule.is_active)
        self.assertEqual(rule.notification_type, "EMAIL_WELCOME")
        mock_http_client_instance.post.assert_called_once_with(
            f"{app_config.settings.CONFIG_SERVICE_URL}/rules/match",
            json={"event_trigger": event_trigger, "context": context}
        )

    @patch('case_management_service.infrastructure.config_service_client.httpx.AsyncClient')
    async def test_get_notification_config_success_inactive_rule_in_list(self, MockAsyncClient):
        # Arrange
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        # Config service returns a list, first rule inactive, second active
        mock_response.json.return_value = [
            {"rule_id": "rule124", "is_active": False, "notification_type": "SMS_ALERT"},
            {"rule_id": "rule125", "is_active": True, "notification_type": "EMAIL_ALERT"}
        ]
        mock_http_client_instance = AsyncMock()
        mock_http_client_instance.post = AsyncMock(return_value=mock_response)
        MockAsyncClient.return_value.__aenter__.return_value = mock_http_client_instance
        app_config.settings.CONFIG_SERVICE_URL = "http://fake-config-service.com/api"

        # Act
        rule = await config_service_client.get_notification_config("TRIGGER", {})
        # Assert
        self.assertIsNotNone(rule) # Should find the active rule125
        self.assertEqual(rule.rule_id, "rule125")
        self.assertTrue(rule.is_active)


    @patch('case_management_service.infrastructure.config_service_client.httpx.AsyncClient')
    async def test_get_notification_config_all_inactive_rules_in_list(self, MockAsyncClient):
        # Arrange
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"rule_id": "rule126", "is_active": False, "notification_type": "SMS_ALERT_INACTIVE"}
        ]
        mock_http_client_instance = AsyncMock()
        mock_http_client_instance.post = AsyncMock(return_value=mock_response)
        MockAsyncClient.return_value.__aenter__.return_value = mock_http_client_instance
        app_config.settings.CONFIG_SERVICE_URL = "http://fake-config-service.com/api"
        # Act
        rule = await config_service_client.get_notification_config("TRIGGER", {})
        # Assert
        self.assertIsNone(rule)


    @patch('case_management_service.infrastructure.config_service_client.httpx.AsyncClient')
    async def test_get_notification_config_no_rule_found(self, MockAsyncClient):
        # Arrange
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = [] # Empty list
        mock_http_client_instance = AsyncMock()
        mock_http_client_instance.post = AsyncMock(return_value=mock_response)
        MockAsyncClient.return_value.__aenter__.return_value = mock_http_client_instance
        app_config.settings.CONFIG_SERVICE_URL = "http://fake-config-service.com/api"
        # Act
        rule = await config_service_client.get_notification_config("TRIGGER", {})
        # Assert
        self.assertIsNone(rule)

    async def test_get_notification_config_no_service_url(self):
        # Arrange
        app_config.settings.CONFIG_SERVICE_URL = None
        # Act
        rule = await config_service_client.get_notification_config("TRIGGER", {})
        # Assert
        self.assertIsNone(rule)
        # No need to restore here due to tearDown

    @patch('case_management_service.infrastructure.config_service_client.httpx.AsyncClient')
    async def test_get_notification_config_http_status_error(self, MockAsyncClient):
        # Arrange
        mock_http_client_instance = AsyncMock()
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 404
        mock_response.text = "Not Found Error Text"
        mock_response.request = MagicMock(spec=httpx.Request)
        mock_response.raise_for_status = MagicMock(side_effect=httpx.HTTPStatusError("Error 404", request=mock_response.request, response=mock_response))

        mock_http_client_instance.post = AsyncMock(return_value=mock_response)
        MockAsyncClient.return_value.__aenter__.return_value = mock_http_client_instance
        app_config.settings.CONFIG_SERVICE_URL = "http://fake-config-service.com/api"
        # Act
        rule = await config_service_client.get_notification_config("TRIGGER", {})
        # Assert
        self.assertIsNone(rule)

    @patch('case_management_service.infrastructure.config_service_client.httpx.AsyncClient')
    async def test_get_notification_config_request_error(self, MockAsyncClient):
        # Arrange
        mock_http_client_instance = AsyncMock()
        mock_http_client_instance.post = AsyncMock(side_effect=httpx.RequestError("Connection failed", request=MagicMock()))
        MockAsyncClient.return_value.__aenter__.return_value = mock_http_client_instance
        app_config.settings.CONFIG_SERVICE_URL = "http://fake-config-service.com/api"
        # Act
        rule = await config_service_client.get_notification_config("TRIGGER", {})
        # Assert
        self.assertIsNone(rule)

    @patch('case_management_service.infrastructure.config_service_client.httpx.AsyncClient')
    async def test_get_notification_config_json_decode_error(self, MockAsyncClient):
        # Arrange
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.side_effect = json.JSONDecodeError("Invalid JSON", "{}", 0)

        mock_http_client_instance = AsyncMock()
        mock_http_client_instance.post = AsyncMock(return_value=mock_response)
        MockAsyncClient.return_value.__aenter__.return_value = mock_http_client_instance
        app_config.settings.CONFIG_SERVICE_URL = "http://fake-config-service.com/api"

        # Act
        rule = await config_service_client.get_notification_config("TRIGGER", {})

        # Assert
        self.assertIsNone(rule) # Should handle parsing errors gracefully
