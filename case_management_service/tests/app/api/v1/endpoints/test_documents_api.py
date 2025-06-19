import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch, ANY

from fastapi.testclient import TestClient
from app.main import app # Import the FastAPI app instance
from app.db import db_schemas
from app.service.commands import commands as service_commands
from app.api.v1.endpoints.documents import DetermineDocRequirementsRequest, UpdateDocStatusRequest # Request models
from app.service.models import CaseType, DocumentStatus, EntityType
from app.shared.errors import ConcurrencyConflictError, DocumentNotFoundError, KafkaProducerError # Assuming Kafka error is not directly raised by these endpoints

# --- Fixtures ---

@pytest.fixture
def client():
    return TestClient(app)

# Sample data for tests
SAMPLE_CASE_ID = str(uuid.uuid4())
SAMPLE_DOC_REQ_ID = str(uuid.uuid4())
SAMPLE_USER_ID = "test_doc_api_user"

def create_sample_determine_req_payload(case_id: str = SAMPLE_CASE_ID) -> dict:
    return {
        "case_id": case_id,
        "case_type": CaseType.KYC.value,
        "country_code": "US",
        "entity_type": EntityType.INDIVIDUAL.value, # Assuming entity_type is part of the request
        "created_by": SAMPLE_USER_ID
    }

def create_sample_update_status_payload(new_status: DocumentStatus = DocumentStatus.APPROVED) -> dict:
    return {
        "status": new_status.value,
        "updated_by": SAMPLE_USER_ID,
        "rejection_reason": "Looks good" if new_status == DocumentStatus.APPROVED else None,
        "s3_path": "/path/to/uploaded/doc.pdf" if new_status == DocumentStatus.APPROVED else None,
        "file_name": "doc.pdf" if new_status == DocumentStatus.APPROVED else None,
    }

def create_sample_required_document_db(
    doc_req_id: str = SAMPLE_DOC_REQ_ID,
    case_id: str = SAMPLE_CASE_ID
) -> db_schemas.RequiredDocumentDB:
    return db_schemas.RequiredDocumentDB(
        id=doc_req_id, # This is the primary key from the read model
        document_id=doc_req_id, # This is the business ID for the document requirement
        case_id=case_id,
        document_type="PASSPORT",
        description="Valid Passport",
        status=DocumentStatus.PENDING_UPLOAD.value,
        version=1,
        created_by=SAMPLE_USER_ID,
        created_at="2023-01-01T00:00:00Z",
        updated_at="2023-01-01T00:00:00Z",
        # other fields as necessary
        country_code="US",
        required_by_case_type=True,
        entity_id=None,
        entity_type=None,
        s3_path=None,
        file_name=None,
        rejection_reason=None,
        updated_by=None
    )

# --- Tests for POST /determine-requirements ---

MODULE_PATH_DOC_API = "app.api.v1.endpoints.documents"

@patch(f"{MODULE_PATH_DOC_API}.handle_determine_initial_document_requirements", new_callable=AsyncMock)
async def test_determine_requirements_success(mock_handler: AsyncMock, client: TestClient):
    payload = create_sample_determine_req_payload()
    mock_handler.return_value = None # This handler likely returns None or True, not an ID

    response = client.post("/api/v1/documents/determine-requirements", json=payload)

    assert response.status_code == 202 # Accepted
    assert response.json() == {"message": "Document requirements determination process started."}

    mock_handler.assert_called_once()
    call_args = mock_handler.call_args[0]
    assert isinstance(call_args[0], service_commands.DetermineInitialDocumentRequirementsCommand)
    assert call_args[0].case_id == uuid.UUID(payload["case_id"])
    assert call_args[0].case_type == CaseType(payload["case_type"])
    assert call_args[0].created_by == payload["created_by"]
    assert call_args[1] is not None # DB


@patch(f"{MODULE_PATH_DOC_API}.handle_determine_initial_document_requirements", new_callable=AsyncMock)
async def test_determine_requirements_validation_error(mock_handler: AsyncMock, client: TestClient):
    invalid_payload = {"case_id": "not-a-uuid"} # Example of invalid payload
    response = client.post("/api/v1/documents/determine-requirements", json=invalid_payload)
    assert response.status_code == 422
    mock_handler.assert_not_called()

@patch(f"{MODULE_PATH_DOC_API}.handle_determine_initial_document_requirements", new_callable=AsyncMock)
async def test_determine_requirements_handler_value_error(mock_handler: AsyncMock, client: TestClient):
    payload = create_sample_determine_req_payload()
    mock_handler.side_effect = ValueError("Invalid input for determination")
    response = client.post("/api/v1/documents/determine-requirements", json=payload)
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid input for determination"

@patch(f"{MODULE_PATH_DOC_API}.handle_determine_initial_document_requirements", new_callable=AsyncMock)
async def test_determine_requirements_concurrency_conflict(mock_handler: AsyncMock, client: TestClient):
    payload = create_sample_determine_req_payload()
    mock_handler.side_effect = ConcurrencyConflictError("Version mismatch during determination")
    response = client.post("/api/v1/documents/determine-requirements", json=payload)
    assert response.status_code == 409
    assert response.json()["detail"] == "Version mismatch during determination"

@patch(f"{MODULE_PATH_DOC_API}.handle_determine_initial_document_requirements", new_callable=AsyncMock)
async def test_determine_requirements_server_error(mock_handler: AsyncMock, client: TestClient):
    payload = create_sample_determine_req_payload()
    mock_handler.side_effect = Exception("Unexpected determination failure")
    response = client.post("/api/v1/documents/determine-requirements", json=payload)
    assert response.status_code == 500
    assert "Internal server error" in response.json()["detail"]


# --- Tests for PUT /{document_requirement_id}/status ---

@patch(f"{MODULE_PATH_DOC_API}.handle_update_document_status", new_callable=AsyncMock)
@patch(f"{MODULE_PATH_DOC_API}.document_requirements_store.get_required_document_by_id", new_callable=AsyncMock)
async def test_update_status_success(
    mock_get_doc_store: AsyncMock, mock_handler: AsyncMock, client: TestClient
):
    payload = create_sample_update_status_payload()
    # Handler is expected to return the document_requirement_id upon success in this API
    mock_handler.return_value = SAMPLE_DOC_REQ_ID

    # The API route then fetches this document from the store to return it
    sample_doc_db = create_sample_required_document_db(status=payload["status"])
    mock_get_doc_store.return_value = sample_doc_db

    response = client.put(f"/api/v1/documents/{SAMPLE_DOC_REQ_ID}/status", json=payload)

    assert response.status_code == 200
    assert response.json() == sample_doc_db.model_dump(by_alias=True)

    mock_handler.assert_called_once()
    call_args_handler = mock_handler.call_args[0]
    assert isinstance(call_args_handler[0], service_commands.UpdateDocumentStatusCommand)
    assert call_args_handler[0].document_id == uuid.UUID(SAMPLE_DOC_REQ_ID)
    assert call_args_handler[0].status == DocumentStatus(payload["status"])
    assert call_args_handler[0].updated_by == payload["updated_by"]
    assert call_args_handler[1] is not None # DB

    mock_get_doc_store.assert_called_once_with(db=ANY, document_id=SAMPLE_DOC_REQ_ID)


@patch(f"{MODULE_PATH_DOC_API}.handle_update_document_status", new_callable=AsyncMock)
async def test_update_status_handler_doc_not_found(mock_handler: AsyncMock, client: TestClient):
    payload = create_sample_update_status_payload()
    mock_handler.side_effect = DocumentNotFoundError(f"Document {SAMPLE_DOC_REQ_ID} not found by handler")

    response = client.put(f"/api/v1/documents/{SAMPLE_DOC_REQ_ID}/status", json=payload)

    assert response.status_code == 404
    assert response.json()["detail"] == f"Document {SAMPLE_DOC_REQ_ID} not found by handler"


@patch(f"{MODULE_PATH_DOC_API}.handle_update_document_status", new_callable=AsyncMock)
@patch(f"{MODULE_PATH_DOC_API}.document_requirements_store.get_required_document_by_id", new_callable=AsyncMock)
async def test_update_status_store_doc_not_found_post_handler(
    mock_get_doc_store: AsyncMock, mock_handler: AsyncMock, client: TestClient
):
    payload = create_sample_update_status_payload()
    mock_handler.return_value = SAMPLE_DOC_REQ_ID # Handler succeeds
    mock_get_doc_store.return_value = None # But store can't find it afterwards

    response = client.put(f"/api/v1/documents/{SAMPLE_DOC_REQ_ID}/status", json=payload)

    assert response.status_code == 404 # Should indicate not found if data consistency is an issue
    assert response.json()["detail"] == f"Updated document requirement with ID {SAMPLE_DOC_REQ_ID} not found in read model."


@patch(f"{MODULE_PATH_DOC_API}.handle_update_document_status", new_callable=AsyncMock)
async def test_update_status_validation_error(mock_handler: AsyncMock, client: TestClient):
    invalid_payload = {"status": "INVALID_STATUS_VALUE"}
    response = client.put(f"/api/v1/documents/{SAMPLE_DOC_REQ_ID}/status", json=invalid_payload)
    assert response.status_code == 422
    mock_handler.assert_not_called()


@patch(f"{MODULE_PATH_DOC_API}.handle_update_document_status", new_callable=AsyncMock)
async def test_update_status_handler_value_error(mock_handler: AsyncMock, client: TestClient):
    payload = create_sample_update_status_payload()
    mock_handler.side_effect = ValueError("Invalid status transition")
    response = client.put(f"/api/v1/documents/{SAMPLE_DOC_REQ_ID}/status", json=payload)
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid status transition"


@patch(f"{MODULE_PATH_DOC_API}.handle_update_document_status", new_callable=AsyncMock)
async def test_update_status_concurrency_conflict(mock_handler: AsyncMock, client: TestClient):
    payload = create_sample_update_status_payload()
    mock_handler.side_effect = ConcurrencyConflictError("Version mismatch during status update")
    response = client.put(f"/api/v1/documents/{SAMPLE_DOC_REQ_ID}/status", json=payload)
    assert response.status_code == 409
    assert response.json()["detail"] == "Version mismatch during status update"


@patch(f"{MODULE_PATH_DOC_API}.handle_update_document_status", new_callable=AsyncMock)
async def test_update_status_server_error_from_handler(mock_handler: AsyncMock, client: TestClient):
    payload = create_sample_update_status_payload()
    mock_handler.side_effect = Exception("Unexpected handler failure")
    response = client.put(f"/api/v1/documents/{SAMPLE_DOC_REQ_ID}/status", json=payload)
    assert response.status_code == 500
    assert "Internal server error" in response.json()["detail"]


@patch(f"{MODULE_PATH_DOC_API}.handle_update_document_status", new_callable=AsyncMock)
@patch(f"{MODULE_PATH_DOC_API}.document_requirements_store.get_required_document_by_id", new_callable=AsyncMock)
async def test_update_status_server_error_from_store(
    mock_get_doc_store: AsyncMock, mock_handler: AsyncMock, client: TestClient
):
    payload = create_sample_update_status_payload()
    mock_handler.return_value = SAMPLE_DOC_REQ_ID
    mock_get_doc_store.side_effect = Exception("Unexpected store failure")

    response = client.put(f"/api/v1/documents/{SAMPLE_DOC_REQ_ID}/status", json=payload)
    assert response.status_code == 500
    assert "Internal server error" in response.json()["detail"]


# --- Tests for GET /{document_requirement_id} ---

@patch(f"{MODULE_PATH_DOC_API}.document_requirements_store.get_required_document_by_id", new_callable=AsyncMock)
async def test_get_doc_req_details_found(mock_get_doc: AsyncMock, client: TestClient):
    sample_doc = create_sample_required_document_db()
    mock_get_doc.return_value = sample_doc

    response = client.get(f"/api/v1/documents/{SAMPLE_DOC_REQ_ID}")

    assert response.status_code == 200
    assert response.json() == sample_doc.model_dump(by_alias=True)
    mock_get_doc.assert_called_once_with(db=ANY, document_id=SAMPLE_DOC_REQ_ID)

@patch(f"{MODULE_PATH_DOC_API}.document_requirements_store.get_required_document_by_id", new_callable=AsyncMock)
async def test_get_doc_req_details_not_found(mock_get_doc: AsyncMock, client: TestClient):
    mock_get_doc.return_value = None

    response = client.get(f"/api/v1/documents/{SAMPLE_DOC_REQ_ID}")

    assert response.status_code == 404
    assert response.json()["detail"] == f"Document requirement with ID {SAMPLE_DOC_REQ_ID} not found."
    mock_get_doc.assert_called_once_with(db=ANY, document_id=SAMPLE_DOC_REQ_ID)

@patch(f"{MODULE_PATH_DOC_API}.document_requirements_store.get_required_document_by_id", new_callable=AsyncMock)
async def test_get_doc_req_details_server_error(mock_get_doc: AsyncMock, client: TestClient):
    mock_get_doc.side_effect = Exception("Store DB is down")

    response = client.get(f"/api/v1/documents/{SAMPLE_DOC_REQ_ID}")

    assert response.status_code == 500
    assert "Internal server error" in response.json()["detail"]


# --- Tests for GET /case/{case_id} --- (List doc reqs for case)

@patch(f"{MODULE_PATH_DOC_API}.document_requirements_store.list_required_documents", new_callable=AsyncMock)
async def test_list_doc_reqs_for_case_success(mock_list_docs: AsyncMock, client: TestClient):
    doc1 = create_sample_required_document_db(doc_req_id=str(uuid.uuid4()), case_id=SAMPLE_CASE_ID)
    doc2 = create_sample_required_document_db(doc_req_id=str(uuid.uuid4()), case_id=SAMPLE_CASE_ID)
    mock_list_docs.return_value = [doc1, doc2]

    response = client.get(f"/api/v1/documents/case/{SAMPLE_CASE_ID}")

    assert response.status_code == 200
    assert response.json() == [doc1.model_dump(by_alias=True), doc2.model_dump(by_alias=True)]
    mock_list_docs.assert_called_once_with(
        db=ANY,
        case_id=SAMPLE_CASE_ID,
        entity_id=None,
        entity_type=None,
        status=None,
        is_required=None
    )

@patch(f"{MODULE_PATH_DOC_API}.document_requirements_store.list_required_documents", new_callable=AsyncMock)
async def test_list_doc_reqs_for_case_with_filters(mock_list_docs: AsyncMock, client: TestClient):
    mock_list_docs.return_value = [] # Content doesn't matter for this test

    entity_id_filter = str(uuid.uuid4())
    entity_type_filter = EntityType.COMPANY.value
    status_filter = DocumentStatus.APPROVED.value
    is_required_filter = True

    url = (
        f"/api/v1/documents/case/{SAMPLE_CASE_ID}"
        f"?entity_id={entity_id_filter}"
        f"&entity_type={entity_type_filter}"
        f"&status={status_filter}"
        f"&is_required={is_required_filter}"
    )
    response = client.get(url)

    assert response.status_code == 200
    mock_list_docs.assert_called_once_with(
        db=ANY,
        case_id=SAMPLE_CASE_ID,
        entity_id=entity_id_filter,
        entity_type=EntityType(entity_type_filter),
        status=DocumentStatus(status_filter),
        is_required=is_required_filter
    )

@patch(f"{MODULE_PATH_DOC_API}.document_requirements_store.list_required_documents", new_callable=AsyncMock)
async def test_list_doc_reqs_for_case_empty(mock_list_docs: AsyncMock, client: TestClient):
    mock_list_docs.return_value = []
    response = client.get(f"/api/v1/documents/case/{SAMPLE_CASE_ID}")
    assert response.status_code == 200
    assert response.json() == []

@patch(f"{MODULE_PATH_DOC_API}.document_requirements_store.list_required_documents", new_callable=AsyncMock)
async def test_list_doc_reqs_for_case_server_error(mock_list_docs: AsyncMock, client: TestClient):
    mock_list_docs.side_effect = Exception("Store is down again")
    response = client.get(f"/api/v1/documents/case/{SAMPLE_CASE_ID}")
    assert response.status_code == 500
    assert "Internal server error" in response.json()["detail"]
