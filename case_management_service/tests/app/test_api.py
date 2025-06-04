# Unit Tests for API Endpoints (Refactored API Routers)
import unittest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient
import datetime
import uuid # Added for generating test IDs

from case_management_service.app.main import app
from case_management_service.infrastructure.database import schemas as db_schemas
# Added for checking command types passed to handlers
from case_management_service.core.commands import models as command_models

class TestApiEndpoints(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(app)

    # --- Health Router Tests ---
    @patch('case_management_service.app.api.routers.health.get_database', new_callable=AsyncMock)
    def test_health_check_db_ok(self, mock_get_db):
        mock_db_instance = AsyncMock()
        mock_db_instance.command = AsyncMock(return_value={"ok": 1})
        mock_get_db.return_value = mock_db_instance
        response = self.client.get("/health")
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
    @patch('case_management_service.app.api.routers.raw_events.get_database', new_callable=AsyncMock)
    def test_list_raw_events(self, mock_get_db):
        mock_db_instance = AsyncMock()
        now = datetime.datetime.utcnow()
        now_iso = now.isoformat()

        raw_event_docs_from_db = [
            {"id": "re1", "event_type": "TestEvent", "payload": {"data": "test1"}, "received_at": now},
        ]

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
        mock_fluent_cursor.sort.assert_called_once_with("received_at", -1)
        mock_cursor_final.to_list.assert_called_once_with(length=5)

    # --- Cases Router Tests ---
    @patch('case_management_service.app.api.routers.cases.read_model_ops.get_case_by_id_from_read_model', new_callable=AsyncMock)
    def test_get_case_by_id_found(self, mock_get_case_op):
        case_id_to_test = "case123"
        now = datetime.datetime.utcnow()
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
        self.assertEqual(response_data["created_at"], now.isoformat())
        mock_get_case_op.assert_called_once_with(case_id=case_id_to_test)

    @patch('case_management_service.app.api.routers.cases.read_model_ops.get_case_by_id_from_read_model', new_callable=AsyncMock)
    def test_get_case_by_id_not_found_cases_router(self, mock_get_case_op):
        mock_get_case_op.return_value = None
        response = self.client.get("/api/v1/cases/nonexistentcase")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json())

    @patch('case_management_service.app.api.routers.cases.read_model_ops.list_cases_from_read_model', new_callable=AsyncMock)
    def test_list_cases_cases_router(self, mock_list_cases_op):
        now = datetime.datetime.utcnow()
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

    # --- Document Requirements API Router Tests (prefix /api/v1/documents) ---

    @patch('case_management_service.app.api.routers.documents.command_handlers.handle_determine_initial_document_requirements', new_callable=AsyncMock)
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

    @patch('case_management_service.app.api.routers.documents.document_requirements_store.get_required_document_by_id', new_callable=AsyncMock)
    @patch('case_management_service.app.api.routers.documents.command_handlers.handle_update_document_status', new_callable=AsyncMock)
    def test_update_document_status_api_success(self, mock_handle_update_status, mock_get_doc_by_id_store): # Sync test method
        doc_req_id = str(uuid.uuid4())
        request_payload = {
            "new_status": "UPLOADED",
            "updated_by_actor_id": "user_test"
        }
        mock_handle_update_status.return_value = doc_req_id

        now = datetime.datetime.utcnow()
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


    @patch('case_management_service.app.api.routers.documents.command_handlers.handle_update_document_status', new_callable=AsyncMock)
    def test_update_document_status_api_not_found_by_handler(self, mock_handle_update_status):
        doc_req_id = "non_existent_id"
        request_payload = {"new_status": "UPLOADED"}
        mock_handle_update_status.return_value = None

        response = self.client.put(f"/api/v1/documents/{doc_req_id}/status", json=request_payload)
        self.assertEqual(response.status_code, 404)

    @patch('case_management_service.app.api.routers.documents.document_requirements_store.get_required_document_by_id', new_callable=AsyncMock)
    def test_get_document_requirement_details_api_found(self, mock_get_doc_by_id_store):
        doc_req_id = str(uuid.uuid4())
        now = datetime.datetime.utcnow()
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

    @patch('case_management_service.app.api.routers.documents.document_requirements_store.get_required_document_by_id', new_callable=AsyncMock)
    def test_get_document_requirement_details_api_not_found(self, mock_get_doc_by_id_store):
        mock_get_doc_by_id_store.return_value = None
        response = self.client.get(f"/api/v1/documents/not_found_id")
        self.assertEqual(response.status_code, 404)


    @patch('case_management_service.app.api.routers.documents.document_requirements_store.list_required_documents', new_callable=AsyncMock)
    def test_list_document_requirements_for_case_api(self, mock_list_docs_store): # Renamed from ..._for_entity_api
        case_id_filter = str(uuid.uuid4()) # Changed from entity_id to case_id for path
        now = datetime.datetime.utcnow()
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
