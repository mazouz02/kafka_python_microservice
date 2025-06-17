# Unit Tests for Health Check Endpoint
import unittest
from unittest.mock import patch, AsyncMock # Added AsyncMock for consistency if DB checks were async
from fastapi.testclient import TestClient

# Import the FastAPI app instance from main.py
# Assuming tests are run from python_microservice_template/ directory (project root for this template)
# and PYTHONPATH includes this directory.
from main import app
# Import settings to check service name in response; path relative to project root
from infra.config import settings

class TestHealthRoutes(unittest.TestCase): # Using unittest.TestCase as TestClient is sync

    def setUp(self):
        self.client = TestClient(app)
        # Store original service name to restore if a test modifies settings directly
        self.original_service_name = settings.SERVICE_NAME

    def tearDown(self):
        # Restore settings if they were changed directly in a test for some reason
        settings.SERVICE_NAME = self.original_service_name

    def test_health_check_success(self):
        # Act
        response = self.client.get("/api/v1/health") # Path includes /api/v1 prefix from main.py

        # Assert
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertEqual(response_data["status"], "ok")
        self.assertEqual(response_data["service_name"], settings.SERVICE_NAME)
        # If health check included DB status (it's commented out in template's health_routes.py):
        # self.assertEqual(response_data.get("database_status"), "connected_placeholder") # Example

    # Example of how to test if DB check was part of health (requires mocking get_database)
    # The actual get_database dependency is in health_routes.py
    # So, the patch target must be where it's looked up by FastAPI's dependency injection
    # which is 'python_microservice_template.app.api.v1.endpoints.health_routes.get_database'
    # if get_database was imported and used there.
    # Currently, health_routes.py imports SettingsDep, not get_database directly.
    # If a DB check were added to health_routes.py using a new DB dependency, that would be mocked.
    # For example, if health_routes.py had:
    # from .....infra.db.mongo import db_session_dependency # (or similar)
    # @router.get("/health")
    # async def health_check(settings: SettingsDep, db = Depends(db_session_dependency)):
    #    ...
    # Then the patch would be:
    # @patch('python_microservice_template.app.api.v1.endpoints.health_routes.db_session_dependency', new_callable=AsyncMock)
    # async def test_health_check_with_db_mock(self, mock_db_session_dep): # Test method becomes async
    #     mock_db_instance = AsyncMock()
    #     mock_db_instance.command = AsyncMock(return_value={'ok': 1})
    #     # If db_session_dependency is a generator, mock its __aenter__ and __aexit__ or the yielded value
    #     mock_db_session_dep.return_value = mock_db_instance

    #     response = self.client.get("/api/v1/health") # TestClient handles async endpoint
    #     self.assertEqual(response.status_code, 200)
    #     self.assertEqual(response.json().get("database_status"), "connected") # Check based on actual response
    #     mock_db_session_dep.assert_called_once()
    pass # Placeholder for the commented-out async test structure example
