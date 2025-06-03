# Unit Tests for API Endpoints (Refactored Structure)
import asyncio
import unittest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient
import datetime

# Module to test - FastAPI app (new location)
from case_management_service.app.main import app # The FastAPI application
from case_management_service.infrastructure.database import schemas as db_schemas # For response model verification

# Note on OpenTelemetry for tests:
# The app.main now initializes OpenTelemetry. For unit tests, if this involves actual exporting
# or complex setup, it might be desirable to mock 'setup_opentelemetry' from app.observability
# or use environment flags to disable OTel during tests.
# For this subtask, we'll assume the default console exporters or that OTel setup doesn't break tests.

class TestApiEndpoints(unittest.TestCase): # Changed to TestCase as TestClient is sync

    def setUp(self):
        # It's important that any OTel auto-instrumentation (like FastAPIInstrumentor)
        # happens on the app object *before* TestClient wraps it.
        # The app from app.main should already be instrumented.
        self.client = TestClient(app)

    # Patch where 'get_database' is *used by the dependency injection system* in app.main.
    # app.main imports get_database from ...infrastructure.database.connection
    # and FastAPI's Depends() uses this imported reference.
    # For endpoints calling read_model_ops, we mock those directly.

    @patch('case_management_service.app.main.read_model_ops.get_case_by_id_from_read_model', new_callable=AsyncMock)
    def test_get_case_by_id_found(self, mock_get_case_op): # Renamed from async_mock test
        # Arrange
        case_id_to_test = "case123"
        # Ensure timestamps are strings if they are serialized as such by Pydantic V1's .json()/.dict()
        # For direct model comparison, datetime objects are fine.
        now = datetime.datetime.utcnow()
        expected_case_doc = db_schemas.CaseManagementDB(
            id=case_id_to_test, client_id="clientXYZ", version="1.0", type="KYC",
            created_at=now, updated_at=now
        )
        mock_get_case_op.return_value = expected_case_doc

        # Act
        response = self.client.get(f"/cases/{case_id_to_test}")

        # Assert
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertEqual(response_data["id"], case_id_to_test)
        self.assertEqual(response_data["client_id"], "clientXYZ")
        # Pydantic serializes datetimes to ISO strings in JSON.
        self.assertEqual(response_data["created_at"], now.isoformat())
        mock_get_case_op.assert_called_once_with(case_id=case_id_to_test)


    @patch('case_management_service.app.main.read_model_ops.get_case_by_id_from_read_model', new_callable=AsyncMock)
    def test_get_case_by_id_not_found(self, mock_get_case_op):
        # Arrange
        mock_get_case_op.return_value = None

        # Act
        response = self.client.get("/cases/nonexistentcase")

        # Assert
        # The endpoint returns Optional[CaseManagementDB]. If None, FastAPI returns HTTP 200 with null body.
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()) # Body should be null
        mock_get_case_op.assert_called_once_with(case_id="nonexistentcase")


    @patch('case_management_service.app.main.read_model_ops.list_cases_from_read_model', new_callable=AsyncMock)
    def test_list_cases(self, mock_list_cases_op):
        # Arrange
        now = datetime.datetime.utcnow()
        mock_case_list = [
            db_schemas.CaseManagementDB(id="c1", client_id="cli1", version="1", type="T1", created_at=now, updated_at=now),
            db_schemas.CaseManagementDB(id="c2", client_id="cli2", version="1", type="T2", created_at=now, updated_at=now)
        ]
        mock_list_cases_op.return_value = mock_case_list

        # Act
        response = self.client.get("/cases?limit=5&skip=0")

        # Assert
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertEqual(len(response_data), 2)
        self.assertEqual(response_data[0]["id"], "c1")
        mock_list_cases_op.assert_called_once_with(limit=5, skip=0)


    @patch('case_management_service.app.main.read_model_ops.list_persons_for_case_from_read_model', new_callable=AsyncMock)
    def test_list_persons_for_case(self, mock_list_persons_op):
        # Arrange
        case_id_filter = "case_for_persons"
        now = datetime.datetime.utcnow()
        mock_person_list = [
            db_schemas.PersonDB(id="p1", case_id=case_id_filter, firstname="F1", lastname="L1", created_at=now, updated_at=now),
        ]
        mock_list_persons_op.return_value = mock_person_list

        # Act
        response = self.client.get(f"/persons/case/{case_id_filter}?limit=10&skip=0")

        # Assert
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertEqual(len(response_data), 1)
        self.assertEqual(response_data[0]["id"], "p1")
        mock_list_persons_op.assert_called_once_with(case_id=case_id_filter, limit=10, skip=0)

    @patch('case_management_service.app.main.get_database', new_callable=AsyncMock)
    def test_health_check_db_ok(self, mock_get_database_in_main):
        # Arrange
        mock_db_instance = AsyncMock()
        mock_db_instance.command = AsyncMock(return_value={"ok": 1})
        mock_get_database_in_main.return_value = mock_db_instance

        # Act
        response = self.client.get("/health")

        # Assert
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["components"]["mongodb"], "connected")
        mock_get_database_in_main.assert_called_once()
        mock_db_instance.command.assert_called_once_with('ping')


    @patch('case_management_service.app.main.get_database', new_callable=AsyncMock)
    def test_health_check_db_fail(self, mock_get_database_in_main):
        # Arrange
        mock_db_instance = AsyncMock()
        mock_db_instance.command = AsyncMock(side_effect=ConnectionError("Ping failed"))
        mock_get_database_in_main.return_value = mock_db_instance

        # Act
        response = self.client.get("/health")

        # Assert
        self.assertEqual(response.status_code, 200) # Health check itself should be robust
        data = response.json()
        self.assertEqual(data["status"], "ok") # Service is "ok", component is not
        self.assertEqual(data["components"]["mongodb"], "disconnected")
        mock_get_database_in_main.assert_called_once()
        mock_db_instance.command.assert_called_once_with('ping')

    @patch('case_management_service.app.main.get_database', new_callable=AsyncMock)
    def test_list_raw_events(self, mock_get_database_in_main):
        # Arrange
        mock_db_instance = AsyncMock()
        now = datetime.datetime.utcnow()
        # Ensure datetime is converted to string for comparison if checking raw JSON
        # For model comparison, datetime objects are fine.
        raw_event_docs_from_db = [ # Simulating documents from MongoDB
            {"id": "re1", "event_type": "TestEvent", "payload": {"data": "test1"}, "received_at": now},
        ]

        mock_cursor = MagicMock()
        mock_cursor.limit.return_value = mock_cursor
        mock_cursor.skip.return_value = mock_cursor
        mock_cursor.sort.return_value = mock_cursor
        mock_cursor.to_list = AsyncMock(return_value=raw_event_docs_from_db) # to_list returns list of dicts

        mock_db_instance.raw_events.find.return_value = mock_cursor
        mock_get_database_in_main.return_value = mock_db_instance

        # Act
        response = self.client.get("/events/raw?limit=5")

        # Assert
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertEqual(len(response_data), 1)
        self.assertEqual(response_data[0]["id"], "re1")
        self.assertEqual(response_data[0]["received_at"], now.isoformat()) # Compare with ISO format string
        mock_db_instance.raw_events.find.assert_called_once_with()
        mock_cursor.limit.assert_called_once_with(5)
        mock_cursor.skip.assert_called_once_with(0)
        mock_cursor.sort.assert_called_once_with("received_at", -1)
