# Unit Tests for API Endpoints (Refactored API Routers)
import unittest
from unittest.mock import patch, AsyncMock, MagicMock # Added MagicMock
from fastapi.testclient import TestClient
import datetime

from case_management_service.app.main import app # Main app for TestClient
from case_management_service.infrastructure.database import schemas as db_schemas

class TestApiEndpoints(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(app)

    # --- Health Router Tests ---
    # Patch target for get_database is now where it's imported in health.py
    @patch('case_management_service.app.api.routers.health.get_database', new_callable=AsyncMock)
    def test_health_check_db_ok(self, mock_get_db):
        mock_db_instance = AsyncMock()
        mock_db_instance.command = AsyncMock(return_value={"ok": 1})
        mock_get_db.return_value = mock_db_instance
        response = self.client.get("/health") # No prefix for health router
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["components"]["mongodb"], "connected")
        mock_get_db.assert_called_once()

    @patch('case_management_service.app.api.routers.health.get_database', new_callable=AsyncMock)
    def test_health_check_db_fail(self, mock_get_db):
        mock_db_instance = AsyncMock()
        mock_db_instance.command = AsyncMock(side_effect=ConnectionError("Ping failed"))
        mock_get_db.return_value = mock_db_instance
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["components"]["mongodb"], "disconnected")

    # --- Raw Events Router Tests ---
    # Path in raw_events router is /events/raw. It's included with prefix /api/v1 in main.py.
    # So, the full path is /api/v1/events/raw.
    @patch('case_management_service.app.api.routers.raw_events.get_database', new_callable=AsyncMock)
    def test_list_raw_events(self, mock_get_db):
        mock_db_instance = AsyncMock()
        now = datetime.datetime.utcnow()
        now_iso = now.isoformat() # For comparing JSON string

        # Simulating documents from MongoDB (as dicts)
        raw_event_docs_from_db = [
            {"id": "re1", "event_type": "TestEvent", "payload": {"data": "test1"}, "received_at": now},
        ]

        # Correct mocking for async cursor methods: to_list is awaited
        mock_cursor_final = AsyncMock()
        mock_cursor_final.to_list = AsyncMock(return_value=raw_event_docs_from_db)

        mock_fluent_cursor = MagicMock()
        mock_fluent_cursor.limit.return_value = mock_fluent_cursor
        mock_fluent_cursor.skip.return_value = mock_fluent_cursor
        mock_fluent_cursor.sort.return_value = mock_cursor_final

        mock_db_instance.raw_events.find.return_value = mock_fluent_cursor
        mock_get_db.return_value = mock_db_instance

        response = self.client.get("/api/v1/events/raw?limit=5")
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertEqual(len(response_data), 1)
        self.assertEqual(response_data[0]["id"], "re1")
        self.assertEqual(response_data[0]["received_at"], now_iso)

        mock_db_instance.raw_events.find.assert_called_once_with()
        mock_fluent_cursor.limit.assert_called_once_with(5)
        mock_fluent_cursor.skip.assert_called_once_with(0)
        # sort is called on the object returned by skip, which is mock_fluent_cursor
        mock_fluent_cursor.sort.assert_called_once_with("received_at", -1)
        # to_list is called on the object returned by sort, which is mock_cursor_final
        mock_cursor_final.to_list.assert_called_once_with(length=5)


    # --- Cases Router Tests ---
    # Path in cases router is /{case_id}. It's included with prefix /api/v1 in main.py.
    # So, the full path is /api/v1/cases/{case_id}.
    @patch('case_management_service.app.api.routers.cases.read_model_ops.get_case_by_id_from_read_model', new_callable=AsyncMock)
    def test_get_case_by_id_found(self, mock_get_case_op):
        case_id_to_test = "case123"
        now = datetime.datetime.utcnow()
        expected_case_obj = db_schemas.CaseManagementDB(
            id=case_id_to_test, client_id="clientXYZ", version="1.0", type="KYC",
            created_at=now, updated_at=now
        )
        mock_get_case_op.return_value = expected_case_obj

        response = self.client.get(f"/api/v1/cases/{case_id_to_test}")
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertEqual(response_data["id"], case_id_to_test)
        self.assertEqual(response_data["created_at"], now.isoformat())
        mock_get_case_op.assert_called_once_with(case_id=case_id_to_test)

    @patch('case_management_service.app.api.routers.cases.read_model_ops.get_case_by_id_from_read_model', new_callable=AsyncMock)
    def test_get_case_by_id_not_found_cases_router(self, mock_get_case_op):
        mock_get_case_op.return_value = None
        response = self.client.get("/api/v1/cases/nonexistentcase")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json())

    # Path in cases router is /. It's included with prefix /api/v1 in main.py.
    # So, the full path is /api/v1/cases.
    @patch('case_management_service.app.api.routers.cases.read_model_ops.list_cases_from_read_model', new_callable=AsyncMock)
    def test_list_cases_cases_router(self, mock_list_cases_op):
        now = datetime.datetime.utcnow()
        mock_case_list = [
            db_schemas.CaseManagementDB(id="c1", client_id="cli1", version="1", type="T1", created_at=now, updated_at=now),
        ]
        mock_list_cases_op.return_value = mock_case_list
        response = self.client.get("/api/v1/cases?limit=5&skip=0") # No trailing slash needed if router uses "/"
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertEqual(len(response_data), 1)
        self.assertEqual(response_data[0]["id"], "c1")
        mock_list_cases_op.assert_called_once_with(limit=5, skip=0)

    # --- Persons Router Tests ---
    # Path in persons router is /case/{case_id}. It's included with prefix /api/v1 in main.py.
    # So, the full path is /api/v1/persons/case/{case_id}.
    @patch('case_management_service.app.api.routers.persons.read_model_ops.list_persons_for_case_from_read_model', new_callable=AsyncMock)
    def test_list_persons_for_case_persons_router(self, mock_list_persons_op):
        case_id_filter = "case_for_persons"
        now = datetime.datetime.utcnow()
        mock_person_list = [
            db_schemas.PersonDB(id="p1", case_id=case_id_filter, firstname="F1", lastname="L1", created_at=now, updated_at=now),
        ]
        mock_list_persons_op.return_value = mock_person_list
        response = self.client.get(f"/api/v1/persons/case/{case_id_filter}?limit=10&skip=0")
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertEqual(len(response_data), 1)
        self.assertEqual(response_data[0]["id"], "p1")
        mock_list_persons_op.assert_called_once_with(case_id=case_id_filter, limit=10, skip=0)
