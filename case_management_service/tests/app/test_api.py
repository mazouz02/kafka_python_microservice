# Unit Tests for API Endpoints (Refactored API Routers)
import unittest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient
import datetime
import uuid # Added for generating test IDs

from case_management_service.app.main import app
# Import the instrumentor to uninstrument
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from case_management_service.infrastructure.database import schemas as db_schemas
# Added for checking command types passed to handlers
from case_management_service.app.service.commands import models as command_models
# Import the actual get_database dependency for overriding
from case_management_service.infrastructure.database.connection import get_database


class TestApiEndpoints(unittest.IsolatedAsyncioTestCase):

    # Removed setUpClass and tearDownClass related to OTel uninstrumentation

    def setUp(self):
        # Create a sophisticated mock for the database instance
        self.mock_db_instance = AsyncMock(name="mock_db_instance")
        mock_collection = AsyncMock(name="mock_collection")
        mock_collection.find_one = AsyncMock(return_value=None) # Default for "not found"
        mock_collection.update_one = AsyncMock()
        mock_collection.insert_one = AsyncMock()
        mock_collection.find = MagicMock() # For find().sort().limit().skip()
        self.mock_db_instance.__getitem__ = MagicMock(return_value=mock_collection)
        self.mock_db_instance.command = AsyncMock(return_value={"ok": 1})

        # This is the mock function that will be returned by patched get_database calls
        async def actual_mock_get_database():
            return self.mock_db_instance

        # Patch get_database where it's imported directly by modules under test
        # Patch for document_requirements_store.py
        self.patch_doc_store_get_db = patch(
            'case_management_service.infrastructure.database.document_requirements_store.get_database',
            new_callable=lambda: AsyncMock(side_effect=actual_mock_get_database)
        )
        self.mock_doc_store_get_db = self.patch_doc_store_get_db.start()

        # Patch for event_store.py
        self.patch_event_store_get_db = patch(
            'case_management_service.infrastructure.database.event_store.get_database',
            new_callable=lambda: AsyncMock(side_effect=actual_mock_get_database)
        )
        self.mock_event_store_get_db = self.patch_event_store_get_db.start()

        # Patch for read_models.py
        self.patch_read_models_get_db = patch(
            'case_management_service.infrastructure.database.read_models.get_database',
            new_callable=lambda: AsyncMock(side_effect=actual_mock_get_database)
        )
        self.mock_read_models_get_db = self.patch_read_models_get_db.start()

        # Setup the dependency override for FastAPI's DI system (for routers)
        app.dependency_overrides[get_database] = actual_mock_get_database

        self.client = TestClient(app)

    def tearDown(self):
        self.patch_doc_store_get_db.stop()
        self.patch_event_store_get_db.stop()
        self.patch_read_models_get_db.stop()
        app.dependency_overrides = {} # Clear overrides after each test
        # It's important that mock_db_instance does not persist state across tests
        # if it were more complex (e.g. holding data). AsyncMock is generally stateless for basic usage.

    # --- Health Router Tests ---
    # No longer need to patch get_database for each router if overridden globally
    def test_health_check_db_ok(self):
        # self.mock_db_instance is already configured by setUp for a successful ping
        # Or, can be more specific here if needed:
        self.mock_db_instance.command = AsyncMock(return_value={"ok": 1})
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["components"]["mongodb"], "connected")
        # We can't easily assert_called_once on the override directly,
        # but we can check calls on self.mock_db_instance.command

    def test_health_check_db_fail(self):
        self.mock_db_instance.command = AsyncMock(side_effect=ConnectionError("Ping failed"))
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200) # Health check itself should be 200
        data = response.json()
        self.assertEqual(data["components"]["mongodb"], "disconnected")

    # --- Raw Events Router Tests ---
    def test_list_raw_events(self):
        # mock_db_instance is self.mock_db_instance from setUp
        now = datetime.datetime.now(datetime.UTC)
        # Pydantic v2 serializes UTC datetimes with 'Z' by default.
        now_iso = now.isoformat().replace("+00:00", "Z")

        raw_event_docs_from_db = [
            {"id": "re1", "event_type": "TestEvent", "payload": {"data": "test1"}, "received_at": now},
        ]

        mock_cursor_final = AsyncMock()
        mock_cursor_final.to_list = AsyncMock(return_value=raw_event_docs_from_db)
        mock_fluent_cursor = MagicMock()
        mock_fluent_cursor.limit.return_value = mock_fluent_cursor
        mock_fluent_cursor.skip.return_value = mock_fluent_cursor
        mock_fluent_cursor.sort.return_value = mock_cursor_final

        # Configure the global mock_db_instance for this test
        # .find itself should be a mock that returns the fluent_cursor mock
        self.mock_db_instance.raw_events.find = MagicMock(return_value=mock_fluent_cursor)

        response = self.client.get("/api/v1/events/raw?limit=5")
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertEqual(len(response_data), 1)
        self.assertEqual(response_data[0]["id"], "re1")
        self.assertEqual(response_data[0]["received_at"], now_iso)
        self.mock_db_instance.raw_events.find.assert_called_once_with()
        mock_fluent_cursor.limit.assert_called_once_with(5)
        mock_fluent_cursor.skip.assert_called_once_with(0)
        mock_fluent_cursor.sort.assert_called_once_with("received_at", -1)
        mock_cursor_final.to_list.assert_called_once_with(length=5)

    # --- Cases Router Tests ---
    @patch('case_management_service.app.api.v1.endpoints.cases.read_model_ops.get_case_by_id_from_read_model', new_callable=AsyncMock)
    def test_get_case_by_id_found(self, mock_get_case_op):
        case_id_to_test = "case123"
        now = datetime.datetime.now(datetime.UTC)
        # CaseManagementDB now requires traitement_type and status
        expected_case_obj = db_schemas.CaseManagementDB(
            id=case_id_to_test, client_id="clientXYZ", version="1.0", type="KYC",
            traitement_type="KYC", status="OPEN", # Added required fields
            created_at=now, updated_at=now
        )
        mock_get_case_op.return_value = expected_case_obj

        response = self.client.get(f"/api/v1/cases/{case_id_to_test}")
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertEqual(response_data["id"], case_id_to_test)
        # Compare epoch timestamps for robustness
        response_dt = datetime.datetime.fromisoformat(response_data["created_at"].replace("Z", "+00:00"))
        self.assertEqual(response_dt.timestamp(), now.timestamp())
        mock_get_case_op.assert_called_once_with(case_id=case_id_to_test)

    @patch('case_management_service.app.api.v1.endpoints.cases.read_model_ops.get_case_by_id_from_read_model', new_callable=AsyncMock)
    def test_get_case_by_id_not_found_cases_router(self, mock_get_case_op):
        mock_get_case_op.return_value = None
        response = self.client.get("/api/v1/cases/nonexistentcase")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json())

    @patch('case_management_service.app.api.v1.endpoints.cases.read_model_ops.list_cases_from_read_model', new_callable=AsyncMock)
    def test_list_cases_cases_router(self, mock_list_cases_op):
        now = datetime.datetime.now(datetime.UTC)
        mock_case_list = [
            db_schemas.CaseManagementDB(id="c1", client_id="cli1", version="1", type="T1", traitement_type="KYC", status="OPEN", created_at=now, updated_at=now),
        ]
        mock_list_cases_op.return_value = mock_case_list
        response = self.client.get("/api/v1/cases?limit=5&skip=0")
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertEqual(len(response_data), 1)
        self.assertEqual(response_data[0]["id"], "c1")
        mock_list_cases_op.assert_called_once_with(limit=5, skip=0)

    # --- Persons Router Tests ---
    @patch('case_management_service.app.api.v1.endpoints.persons.read_model_ops.list_persons_for_case_from_read_model', new_callable=AsyncMock)
    def test_list_persons_for_case_persons_router(self, mock_list_persons_op):
        case_id_filter = "case_for_persons"
        now = datetime.datetime.now(datetime.UTC)
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

    # --- Document Requirements API Router Tests (prefix /api/v1/documents) ---

    @patch('case_management_service.app.api.v1.endpoints.documents.command_handlers.handle_determine_initial_document_requirements', new_callable=AsyncMock)
    async def test_determine_document_requirements_api(self, mock_handle_determine_docs): # Test method must be async for await
        request_payload = {
            "case_id": "case_xyz",
            "entity_id": "person_xyz",
            "entity_type": "PERSON",
            "traitement_type": "KYC",
            "case_type": "STANDARD"
        }
        mock_handle_determine_docs.return_value = [str(uuid.uuid4())]

        # TestClient calls are synchronous, but the endpoint function is async.
        # If the test method itself is async, TestClient needs careful handling or an async client.
        # For TestClient, keep test method sync. It handles the loop for the endpoint.
        # The mock_handle_determine_docs is AsyncMock, so its call within endpoint is awaited.

        # Reverting this test method to sync, as TestClient is sync.
        # The endpoint itself is async and will be run by TestClient's event loop.
        response = self.client.post("/api/v1/documents/determine-requirements", json=request_payload)

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json(), {"message": "Document requirement determination process initiated."})

        mock_handle_determine_docs.assert_called_once()
        called_cmd = mock_handle_determine_docs.call_args.args[0]
        self.assertIsInstance(called_cmd, command_models.DetermineInitialDocumentRequirementsCommand)
        self.assertEqual(called_cmd.case_id, "case_xyz")

    @patch('case_management_service.app.api.v1.endpoints.documents.document_requirements_store.get_required_document_by_id', new_callable=AsyncMock)
    @patch('case_management_service.app.api.v1.endpoints.documents.command_handlers.handle_update_document_status', new_callable=AsyncMock)
    def test_update_document_status_api_success(self, mock_handle_update_status, mock_get_doc_by_id_store): # Sync test method
        doc_req_id = str(uuid.uuid4())
        request_payload = {
            "new_status": "UPLOADED",
            "updated_by_actor_id": "user_test"
        }
        mock_handle_update_status.return_value = doc_req_id

        now = datetime.datetime.now(datetime.UTC)
        updated_doc_db = db_schemas.RequiredDocumentDB(
            id=doc_req_id, case_id="c1", entity_id="e1", entity_type="PERSON",
            document_type="PASSPORT", status="UPLOADED", is_required=True,
            metadata={"updated_by": "user_test"}, created_at=now, updated_at=now
        )
        mock_get_doc_by_id_store.return_value = updated_doc_db

        response = self.client.put(f"/api/v1/documents/{doc_req_id}/status", json=request_payload)

        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertEqual(response_data["id"], doc_req_id)
        self.assertEqual(response_data["status"], "UPLOADED")

        mock_handle_update_status.assert_called_once()
        called_cmd = mock_handle_update_status.call_args.args[0]
        self.assertIsInstance(called_cmd, command_models.UpdateDocumentStatusCommand)
        self.assertEqual(called_cmd.document_requirement_id, doc_req_id)
        self.assertEqual(called_cmd.new_status, "UPLOADED")

        mock_get_doc_by_id_store.assert_called_once_with(doc_req_id)


    # Removed patch for this test to rely on global DB mock
    def test_update_document_status_api_not_found_by_handler(self): # Removed mock_handle_update_status argument
        doc_req_id = "non_existent_id"
        request_payload = {"new_status": "UPLOADED"}
        # No mock_handle_update_status.return_value = None needed here
        # The command handler will call get_required_document_by_id,
        # which will use the globally mocked db that returns None for find_one.

        response = self.client.put(f"/api/v1/documents/{doc_req_id}/status", json=request_payload)
        self.assertEqual(response.status_code, 404)

    @patch('case_management_service.app.api.v1.endpoints.documents.document_requirements_store.get_required_document_by_id', new_callable=AsyncMock)
    def test_get_document_requirement_details_api_found(self, mock_get_doc_by_id_store):
        doc_req_id = str(uuid.uuid4())
        now = datetime.datetime.now(datetime.UTC)
        doc_db = db_schemas.RequiredDocumentDB(
            id=doc_req_id, case_id="c1", entity_id="e1", entity_type="PERSON",
            document_type="PASSPORT", status="AWAITING_UPLOAD", is_required=True,
            created_at=now, updated_at=now
        )
        mock_get_doc_by_id_store.return_value = doc_db

        response = self.client.get(f"/api/v1/documents/{doc_req_id}")
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertEqual(response_data["id"], doc_req_id)
        mock_get_doc_by_id_store.assert_called_once_with(doc_req_id)

    # Removed patch for this test to rely on global DB mock
    def test_get_document_requirement_details_api_not_found(self): # Removed mock_get_doc_by_id_store argument
        # No mock_get_doc_by_id_store.return_value = None needed here
        # The store's get_required_document_by_id will use the globally mocked db
        # that returns None for find_one.
        response = self.client.get(f"/api/v1/documents/not_found_id")
        self.assertEqual(response.status_code, 404)


    @patch('case_management_service.app.api.v1.endpoints.documents.document_requirements_store.list_required_documents', new_callable=AsyncMock)
    def test_list_document_requirements_for_case_api(self, mock_list_docs_store): # Renamed from ..._for_entity_api
        case_id_filter = str(uuid.uuid4()) # Changed from entity_id to case_id for path
        now = datetime.datetime.now(datetime.UTC)
        docs_list_db = [
            db_schemas.RequiredDocumentDB(
                id=str(uuid.uuid4()), case_id=case_id_filter, entity_id="entity1", entity_type="PERSON",
                document_type="PASSPORT", status="AWAITING_UPLOAD", is_required=True,
                created_at=now, updated_at=now
            )
        ]
        mock_list_docs_store.return_value = docs_list_db

        response = self.client.get(f"/api/v1/documents/case/{case_id_filter}?entity_type=PERSON&status=AWAITING_UPLOAD")

        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertEqual(len(response_data), 1)
        self.assertEqual(response_data[0]["case_id"], case_id_filter)
        mock_list_docs_store.assert_called_once_with(
            case_id=case_id_filter, entity_id=None, entity_type="PERSON", status="AWAITING_UPLOAD", is_required=None
        )
