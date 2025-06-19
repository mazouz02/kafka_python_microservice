# Unit Tests for API Endpoints (Refactored API Routers)
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient
import datetime
import uuid # Added for generating test IDs

from case_management_service.app.main import app
# Import the instrumentor to uninstrument
# from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor # Not used directly in tests
from case_management_service.infrastructure.database import schemas as db_schemas
# Added for checking command types passed to handlers
from case_management_service.app.service.commands import models as command_models
# Import the actual get_database dependency for overriding
from case_management_service.infrastructure.database.connection import get_database

# Import exceptions for testing error handling
from case_management_service.app.service.exceptions import DocumentNotFoundError, ConcurrencyConflictError, KafkaProducerError


@pytest.fixture
def mock_db_instance_main(): # Renamed to avoid conflict if other mock_db_instance fixtures exist
    # Create a sophisticated mock for the database instance
    _mock_db_instance = AsyncMock(name="mock_db_instance")
    mock_collection = AsyncMock(name="mock_collection")
    mock_collection.find_one = AsyncMock(return_value=None) # Default for "not found"
    mock_collection.update_one = AsyncMock()
    mock_collection.insert_one = AsyncMock()
    mock_collection.find = MagicMock() # For find().sort().limit().skip()
    _mock_db_instance.__getitem__ = MagicMock(return_value=mock_collection)
    _mock_db_instance.command = AsyncMock(return_value={"ok": 1})
    return _mock_db_instance

@pytest.fixture
def client_fixture(mock_db_instance_main):
    # This is the mock function that will be returned by patched get_database calls
    async def actual_mock_get_database():
        return mock_db_instance_main

    # Patch get_database where it's imported directly by modules under test
    patch_doc_store_get_db = patch(
        'case_management_service.infrastructure.database.document_requirements_store.get_database',
        new_callable=lambda: AsyncMock(side_effect=actual_mock_get_database)
    )
    patch_event_store_get_db = patch(
        'case_management_service.infrastructure.database.event_store.get_database',
        new_callable=lambda: AsyncMock(side_effect=actual_mock_get_database)
    )
    patch_read_models_get_db = patch(
        'case_management_service.infrastructure.database.read_models.get_database',
        new_callable=lambda: AsyncMock(side_effect=actual_mock_get_database)
    )

    mock_doc_store_get_db = patch_doc_store_get_db.start()
    mock_event_store_get_db = patch_event_store_get_db.start()
    mock_read_models_get_db = patch_read_models_get_db.start()

    # Setup the dependency override for FastAPI's DI system (for routers)
    app.dependency_overrides[get_database] = actual_mock_get_database

    test_client = TestClient(app)
    yield test_client # This is what the tests will use

    # Teardown
    patch_doc_store_get_db.stop()
    patch_event_store_get_db.stop()
    patch_read_models_get_db.stop()
    app.dependency_overrides = {}


# --- Health Router Tests ---
@pytest.mark.asyncio
async def test_health_check_db_ok(client_fixture: TestClient, mock_db_instance_main: AsyncMock):
    mock_db_instance_main.command = AsyncMock(return_value={"ok": 1}) # Ensure it's set for this test
    response = client_fixture.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["components"]["mongodb"] == "connected"

@pytest.mark.asyncio
async def test_health_check_db_fail(client_fixture: TestClient, mock_db_instance_main: AsyncMock):
    mock_db_instance_main.command = AsyncMock(side_effect=ConnectionError("Ping failed"))
    response = client_fixture.get("/health")
    assert response.status_code == 200 # Health check itself should be 200
    data = response.json()
    assert data["components"]["mongodb"] == "disconnected"

# --- Raw Events Router Tests ---
@pytest.mark.asyncio
async def test_list_raw_events(client_fixture: TestClient, mock_db_instance_main: AsyncMock):
    now = datetime.datetime.now(datetime.UTC)
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

    # Configure the mock_db_instance for this test
    mock_db_instance_main.raw_events.find = MagicMock(return_value=mock_fluent_cursor)

    response = client_fixture.get("/api/v1/events/raw?limit=5")
    assert response.status_code == 200
    response_data = response.json()
    assert len(response_data) == 1
    assert response_data[0]["id"] == "re1"
    assert response_data[0]["received_at"] == now_iso

    mock_db_instance_main.raw_events.find.assert_called_once_with()
    mock_fluent_cursor.limit.assert_called_once_with(5)
    mock_fluent_cursor.skip.assert_called_once_with(0)
    mock_fluent_cursor.sort.assert_called_once_with("received_at", -1)
    mock_cursor_final.to_list.assert_called_once_with(length=5)

# --- Cases Router Tests ---
@pytest.mark.asyncio
@patch('case_management_service.app.api.v1.endpoints.cases.read_model_ops.get_case_by_id_from_read_model', new_callable=AsyncMock)
async def test_get_case_by_id_found(mock_get_case_op, client_fixture: TestClient):
    case_id_to_test = "case123"
    now = datetime.datetime.now(datetime.UTC)
    expected_case_obj = db_schemas.CaseManagementDB(
        id=case_id_to_test, client_id="clientXYZ", version="1.0", type="KYC",
        traitement_type="KYC", status="OPEN",
        created_at=now, updated_at=now
    )
    mock_get_case_op.return_value = expected_case_obj

    response = client_fixture.get(f"/api/v1/cases/{case_id_to_test}")
    assert response.status_code == 200
    response_data = response.json()
    assert response_data["id"] == case_id_to_test
    response_dt = datetime.datetime.fromisoformat(response_data["created_at"].replace("Z", "+00:00"))
    assert response_dt.timestamp() == now.timestamp()
    mock_get_case_op.assert_called_once_with(case_id=case_id_to_test)

@pytest.mark.asyncio
@patch('case_management_service.app.api.v1.endpoints.cases.read_model_ops.get_case_by_id_from_read_model', new_callable=AsyncMock)
async def test_get_case_by_id_not_found_cases_router(mock_get_case_op, client_fixture: TestClient):
    mock_get_case_op.return_value = None
    response = client_fixture.get("/api/v1/cases/nonexistentcase")
    assert response.status_code == 200
    assert response.json() is None

@pytest.mark.asyncio
@patch('case_management_service.app.api.v1.endpoints.cases.read_model_ops.list_cases_from_read_model', new_callable=AsyncMock)
async def test_list_cases_cases_router(mock_list_cases_op, client_fixture: TestClient):
    now = datetime.datetime.now(datetime.UTC)
    mock_case_list = [
        db_schemas.CaseManagementDB(id="c1", client_id="cli1", version="1", type="T1", traitement_type="KYC", status="OPEN", created_at=now, updated_at=now),
    ]
    mock_list_cases_op.return_value = mock_case_list
    response = client_fixture.get("/api/v1/cases?limit=5&skip=0")
    assert response.status_code == 200
    response_data = response.json()
    assert len(response_data) == 1
    assert response_data[0]["id"] == "c1"
    mock_list_cases_op.assert_called_once_with(limit=5, skip=0)

# --- Persons Router Tests ---
@pytest.mark.asyncio
@patch('case_management_service.app.api.v1.endpoints.persons.read_model_ops.list_persons_for_case_from_read_model', new_callable=AsyncMock)
async def test_list_persons_for_case_persons_router(mock_list_persons_op, client_fixture: TestClient):
    case_id_filter = "case_for_persons"
    now = datetime.datetime.now(datetime.UTC)
    mock_person_list = [
        db_schemas.PersonDB(id="p1", case_id=case_id_filter, firstname="F1", lastname="L1", created_at=now, updated_at=now),
    ]
    mock_list_persons_op.return_value = mock_person_list
    response = client_fixture.get(f"/api/v1/persons/case/{case_id_filter}?limit=10&skip=0")
    assert response.status_code == 200
    response_data = response.json()
    assert len(response_data) == 1
    assert response_data[0]["id"] == "p1"
    mock_list_persons_op.assert_called_once_with(case_id=case_id_filter, limit=10, skip=0)

# --- Document Requirements API Router Tests (prefix /api/v1/documents) ---
@pytest.mark.asyncio
@patch('case_management_service.app.api.v1.endpoints.documents.command_handlers.handle_determine_initial_document_requirements', new_callable=AsyncMock)
async def test_determine_document_requirements_api(mock_handle_determine_docs, client_fixture: TestClient):
    request_payload = {
        "case_id": "case_xyz", "entity_id": "person_xyz", "entity_type": "PERSON",
        "traitement_type": "KYC", "case_type": "STANDARD"
    }
    mock_handle_determine_docs.return_value = [str(uuid.uuid4())]
    response = client_fixture.post("/api/v1/documents/determine-requirements", json=request_payload)
    assert response.status_code == 202
    assert response.json() == {"message": "Document requirement determination process initiated."}
    mock_handle_determine_docs.assert_called_once()
    called_cmd = mock_handle_determine_docs.call_args.args[0]
    assert isinstance(called_cmd, command_models.DetermineInitialDocumentRequirementsCommand)
    assert called_cmd.case_id == "case_xyz"

@pytest.mark.asyncio
@patch('case_management_service.app.api.v1.endpoints.documents.document_requirements_store.get_required_document_by_id', new_callable=AsyncMock)
@patch('case_management_service.app.api.v1.endpoints.documents.command_handlers.handle_update_document_status', new_callable=AsyncMock)
async def test_update_document_status_api_success(mock_handle_update_status, mock_get_doc_by_id_store, client_fixture: TestClient):
    doc_req_id = str(uuid.uuid4())
    request_payload = {"new_status": "UPLOADED", "updated_by_actor_id": "user_test"}
    mock_handle_update_status.return_value = doc_req_id
    now = datetime.datetime.now(datetime.UTC)
    updated_doc_db = db_schemas.RequiredDocumentDB(
        id=doc_req_id, case_id="c1", entity_id="e1", entity_type="PERSON",
        document_type="PASSPORT", status="UPLOADED", is_required=True,
        metadata={"updated_by": "user_test"}, created_at=now, updated_at=now
    )
    mock_get_doc_by_id_store.return_value = updated_doc_db
    response = client_fixture.put(f"/api/v1/documents/{doc_req_id}/status", json=request_payload)
    assert response.status_code == 200
    response_data = response.json()
    assert response_data["id"] == doc_req_id
    assert response_data["status"] == "UPLOADED"
    mock_handle_update_status.assert_called_once()
    called_cmd = mock_handle_update_status.call_args.args[0]
    assert isinstance(called_cmd, command_models.UpdateDocumentStatusCommand)
    assert called_cmd.document_requirement_id == doc_req_id
    assert called_cmd.new_status == "UPLOADED"
    mock_get_doc_by_id_store.assert_called_once_with(doc_req_id)

@pytest.mark.asyncio
# This test relies on the global DB mock setup in client_fixture to simulate not found
async def test_update_document_status_api_not_found_by_handler(client_fixture: TestClient, mock_db_instance_main: AsyncMock):
    doc_req_id = "non_existent_id"
    request_payload = {"new_status": "UPLOADED"}

    # Ensure the mock_db_instance (via get_required_document_by_id -> find_one) returns None
    # The default behavior for mock_collection.find_one in mock_db_instance_main is already None
    # If a more specific collection (e.g. 'document_requirements') is used by the store, ensure that one returns None.
    # Assuming the store uses a collection that's covered by the generic mock_db_instance_main.__getitem__().find_one

    # For this test to work as intended, the *command handler* should raise DocumentNotFoundError.
    # This means we might need to patch the handler itself if it doesn't use the store that's being globally mocked,
    # or ensure the global mock correctly simulates the "not found" for the specific store call.
    # The original test relied on the global DB mock. Let's assume the handler uses a store that would
    # eventually call `mock_db_instance_main['some_collection'].find_one(...)` which returns None by default.

    # To be more explicit, if `handle_update_document_status` calls `get_required_document_by_id_from_read_model` (which is patched in other tests)
    # or `document_requirements_store.get_required_document_by_id` (which uses the global mock via `get_database`),
    # the global mock should suffice.
    # Let's refine the mock for the specific collection if known, e.g., 'document_requirements'
    mock_db_instance_main.document_requirements.find_one = AsyncMock(return_value=None)


    response = client_fixture.put(f"/api/v1/documents/{doc_req_id}/status", json=request_payload)
    assert response.status_code == 404
    # Add assert for detail message if the endpoint provides one for DocumentNotFoundError

@pytest.mark.asyncio
@patch('case_management_service.app.api.v1.endpoints.documents.document_requirements_store.get_required_document_by_id', new_callable=AsyncMock)
async def test_get_document_requirement_details_api_found(mock_get_doc_by_id_store, client_fixture: TestClient):
    doc_req_id = str(uuid.uuid4())
    now = datetime.datetime.now(datetime.UTC)
    doc_db = db_schemas.RequiredDocumentDB(
        id=doc_req_id, case_id="c1", entity_id="e1", entity_type="PERSON",
        document_type="PASSPORT", status="AWAITING_UPLOAD", is_required=True,
        created_at=now, updated_at=now
    )
    mock_get_doc_by_id_store.return_value = doc_db
    response = client_fixture.get(f"/api/v1/documents/{doc_req_id}")
    assert response.status_code == 200
    response_data = response.json()
    assert response_data["id"] == doc_req_id
    mock_get_doc_by_id_store.assert_called_once_with(doc_req_id)

@pytest.mark.asyncio
# Relies on global mock via client_fixture for not found
async def test_get_document_requirement_details_api_not_found(client_fixture: TestClient, mock_db_instance_main: AsyncMock):
    # Ensure the store call (e.g., document_requirements_store.get_required_document_by_id)
    # will result in a find_one call on a collection that's mocked to return None.
    # Default is already None for find_one in the main mock_db_instance_main.
    mock_db_instance_main.document_requirements.find_one = AsyncMock(return_value=None) # More specific

    response = client_fixture.get(f"/api/v1/documents/not_found_id")
    assert response.status_code == 404

@pytest.mark.asyncio
@patch('case_management_service.app.api.v1.endpoints.documents.document_requirements_store.list_required_documents', new_callable=AsyncMock)
async def test_list_document_requirements_for_case_api(mock_list_docs_store, client_fixture: TestClient):
    case_id_filter = str(uuid.uuid4())
    now = datetime.datetime.now(datetime.UTC)
    docs_list_db = [
        db_schemas.RequiredDocumentDB(
            id=str(uuid.uuid4()), case_id=case_id_filter, entity_id="entity1", entity_type="PERSON",
            document_type="PASSPORT", status="AWAITING_UPLOAD", is_required=True,
            created_at=now, updated_at=now
        )
    ]
    mock_list_docs_store.return_value = docs_list_db
    response = client_fixture.get(f"/api/v1/documents/case/{case_id_filter}?entity_type=PERSON&status=AWAITING_UPLOAD")
    assert response.status_code == 200
    response_data = response.json()
    assert len(response_data) == 1
    assert response_data[0]["case_id"] == case_id_filter
    mock_list_docs_store.assert_called_once_with(
        case_id=case_id_filter, entity_id=None, entity_type="PERSON", status="AWAITING_UPLOAD", is_required=None
    )

# --- Tests merged from tests/app/test_api.py (already pytest style, but adapted for client_fixture) ---
@pytest.mark.asyncio
@patch('case_management_service.app.api.v1.endpoints.cases.handle_create_case_command', new_callable=AsyncMock)
async def test_create_case_api_concurrency_conflict(mock_handler, client_fixture: TestClient):
    mock_handler.side_effect = ConcurrencyConflictError("agg123", 1, 2)
    response = client_fixture.post("/api/v1/cases", json={
        "client_id": "client1", "case_type": "KYC_STANDARD", "case_version": "1.0",
        "traitement_type": "KYC", "persons": [{"firstname": "John", "lastname": "Doe", "birthdate": "1990-01-01"}]
    })
    assert response.status_code == 409
    assert "Concurrency conflict" in response.json()["detail"]

@pytest.mark.asyncio
@patch('case_management_service.app.api.v1.endpoints.cases.handle_create_case_command', new_callable=AsyncMock)
async def test_create_case_api_kafka_error(mock_handler, client_fixture: TestClient):
    mock_handler.side_effect = KafkaProducerError("Failed to send to Kafka")
    response = client_fixture.post("/api/v1/cases", json={
        "client_id": "client2", "case_type": "KYB_ENHANCED", "case_version": "1.1",
        "traitement_type": "KYB", "company_profile": {"registered_name": "Test Corp", "registration_number": "REG123"}
    })
    assert response.status_code == 502
    assert "Failed to publish essential notification event" in response.json()["detail"]

@pytest.mark.asyncio
@patch('case_management_service.app.api.v1.endpoints.documents.handle_update_document_status', new_callable=AsyncMock)
async def test_update_document_status_api_not_found_merged(mock_handler, client_fixture: TestClient):
    doc_req_id = "non_existent_doc_id_123"
    mock_handler.side_effect = DocumentNotFoundError(doc_req_id)
    response = client_fixture.put(f"/api/v1/documents/{doc_req_id}/status", json={"new_status": "UPLOADED"})
    assert response.status_code == 404
    assert f"Document requirement with ID '{doc_req_id}' not found" in response.json()["detail"]

@pytest.mark.asyncio
@patch('case_management_service.app.api.v1.endpoints.documents.handle_update_document_status', new_callable=AsyncMock)
async def test_update_document_status_api_concurrency_conflict_merged(mock_handler, client_fixture: TestClient):
    doc_req_id = "doc_id_for_concurrency_test_456"
    mock_handler.side_effect = ConcurrencyConflictError(doc_req_id, 1, 2)
    response = client_fixture.put(f"/api/v1/documents/{doc_req_id}/status", json={"new_status": "VERIFIED_AUTO"})
    assert response.status_code == 409
    assert "Concurrency conflict" in response.json()["detail"]
