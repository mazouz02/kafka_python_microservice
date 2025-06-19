import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch, ANY

from fastapi.testclient import TestClient
from app.main import app # Import the FastAPI app instance
from app.db import db_schemas
from app.service.commands import commands as service_commands # To avoid collision with pydantic 'commands'
from app.service.models import CaseType, Role, PersonProfile, CompanyProfile
from app.shared.errors import ConcurrencyConflictError, KafkaProducerError

# --- Fixtures ---

@pytest.fixture
def client():
    return TestClient(app)

# Sample data for tests
SAMPLE_CASE_ID = str(uuid.uuid4())
SAMPLE_USER_ID = "test_api_user"

def create_sample_case_db(case_id: str = SAMPLE_CASE_ID, version: int = 1) -> db_schemas.CaseManagementDB:
    return db_schemas.CaseManagementDB(
        case_id=case_id,
        version=version,
        case_type=CaseType.KYC.value,
        status="PENDING",
        created_by=SAMPLE_USER_ID,
        created_at="2023-01-01T10:00:00Z",
        updated_at="2023-01-01T10:00:00Z",
        # Optional fields
        company_id=None,
        persons=[],
        required_documents=[]
    )

def create_sample_create_case_command_payload() -> dict:
    person1_id = str(uuid.uuid4())
    return {
        "case_type": CaseType.KYC.value,
        "created_by": SAMPLE_USER_ID,
        "persons": [
            {
                "person_id": person1_id,
                "profile": {"name": "John API Doe", "email": "john.api@example.com"},
                "role": Role.PRIMARY_CONTACT.value
            }
        ],
        "company_profile": None,
        "beneficial_owners": None
    }

# --- Tests for GET /cases/{case_id} ---

@patch("app.api.v1.endpoints.cases.read_model_ops.get_case_by_id_from_read_model", new_callable=AsyncMock)
async def test_get_case_by_id_found(mock_get_case: AsyncMock, client: TestClient):
    sample_case = create_sample_case_db()
    mock_get_case.return_value = sample_case

    response = client.get(f"/api/v1/cases/{SAMPLE_CASE_ID}")

    assert response.status_code == 200
    assert response.json() == sample_case.model_dump(by_alias=True) # Use model_dump for FastAPI response matching
    mock_get_case.assert_called_once_with(db=ANY, case_id=SAMPLE_CASE_ID)

@patch("app.api.v1.endpoints.cases.read_model_ops.get_case_by_id_from_read_model", new_callable=AsyncMock)
async def test_get_case_by_id_not_found(mock_get_case: AsyncMock, client: TestClient):
    mock_get_case.return_value = None

    response = client.get(f"/api/v1/cases/{SAMPLE_CASE_ID}")

    assert response.status_code == 200 # The API returns 200 with null body as per current router logic
    assert response.json() is None
    mock_get_case.assert_called_once_with(db=ANY, case_id=SAMPLE_CASE_ID)

@patch("app.api.v1.endpoints.cases.read_model_ops.get_case_by_id_from_read_model", new_callable=AsyncMock)
async def test_get_case_by_id_server_error(mock_get_case: AsyncMock, client: TestClient):
    mock_get_case.side_effect = Exception("DB is down")

    response = client.get(f"/api/v1/cases/{SAMPLE_CASE_ID}")

    assert response.status_code == 500
    assert "Internal server error" in response.json()["detail"]
    # assert "DB is down" in response.json()["detail"] # Or more specific if error propagation is set up

# --- Tests for GET /cases ---

@patch("app.api.v1.endpoints.cases.read_model_ops.list_cases_from_read_model", new_callable=AsyncMock)
async def test_list_cases_success(mock_list_cases: AsyncMock, client: TestClient):
    sample_case1 = create_sample_case_db(case_id=str(uuid.uuid4()), version=1)
    sample_case2 = create_sample_case_db(case_id=str(uuid.uuid4()), version=2)
    mock_list_cases.return_value = [sample_case1, sample_case2]

    response = client.get("/api/v1/cases")

    assert response.status_code == 200
    expected_json = [sample_case1.model_dump(by_alias=True), sample_case2.model_dump(by_alias=True)]
    assert response.json() == expected_json
    mock_list_cases.assert_called_once_with(db=ANY, skip=0, limit=100) # Default pagination

@patch("app.api.v1.endpoints.cases.read_model_ops.list_cases_from_read_model", new_callable=AsyncMock)
async def test_list_cases_with_pagination(mock_list_cases: AsyncMock, client: TestClient):
    mock_list_cases.return_value = [] # Content doesn't matter for this test

    response = client.get("/api/v1/cases?skip=5&limit=50")

    assert response.status_code == 200
    mock_list_cases.assert_called_once_with(db=ANY, skip=5, limit=50)

@patch("app.api.v1.endpoints.cases.read_model_ops.list_cases_from_read_model", new_callable=AsyncMock)
async def test_list_cases_empty(mock_list_cases: AsyncMock, client: TestClient):
    mock_list_cases.return_value = []

    response = client.get("/api/v1/cases")

    assert response.status_code == 200
    assert response.json() == []
    mock_list_cases.assert_called_once_with(db=ANY, skip=0, limit=100)

@patch("app.api.v1.endpoints.cases.read_model_ops.list_cases_from_read_model", new_callable=AsyncMock)
async def test_list_cases_server_error(mock_list_cases: AsyncMock, client: TestClient):
    mock_list_cases.side_effect = Exception("DB is really down")

    response = client.get("/api/v1/cases")

    assert response.status_code == 500
    assert "Internal server error" in response.json()["detail"]
    # assert "DB is really down" in response.json()["detail"]


# --- Tests for POST /cases ---

@patch("app.api.v1.endpoints.cases.handle_create_case_command", new_callable=AsyncMock)
async def test_create_case_success(mock_handle_command: AsyncMock, client: TestClient):
    payload = create_sample_create_case_command_payload()
    expected_case_id = str(uuid.uuid4())
    mock_handle_command.return_value = expected_case_id # The handler returns the case_id

    response = client.post("/api/v1/cases", json=payload)

    assert response.status_code == 202 # Accepted
    assert response.json() == {"case_id": expected_case_id}

    mock_handle_command.assert_called_once()
    call_args = mock_handle_command.call_args[0]
    assert isinstance(call_args[0], service_commands.CreateCaseCommand)
    assert call_args[0].case_type == CaseType(payload["case_type"])
    assert call_args[0].created_by == payload["created_by"]
    assert len(call_args[0].persons) == len(payload["persons"])
    assert call_args[0].persons[0]["person_id"] == uuid.UUID(payload["persons"][0]["person_id"]) # Ensure conversion
    assert call_args[0].persons[0]["profile"].name == payload["persons"][0]["profile"]["name"]
    # db argument is call_args[1]
    assert call_args[1] is not None # Check that a DB session/mock was passed


@patch("app.api.v1.endpoints.cases.handle_create_case_command", new_callable=AsyncMock)
async def test_create_case_validation_error(mock_handle_command: AsyncMock, client: TestClient):
    invalid_payload = {"case_type": "INVALID_TYPE"} # Missing created_by, etc.

    response = client.post("/api/v1/cases", json=invalid_payload)

    assert response.status_code == 422 # Unprocessable Entity for Pydantic validation errors
    mock_handle_command.assert_not_called()


@patch("app.api.v1.endpoints.cases.handle_create_case_command", new_callable=AsyncMock)
async def test_create_case_concurrency_conflict(mock_handle_command: AsyncMock, client: TestClient):
    payload = create_sample_create_case_command_payload()
    mock_handle_command.side_effect = ConcurrencyConflictError("Test version conflict")

    response = client.post("/api/v1/cases", json=payload)

    assert response.status_code == 409 # Conflict
    assert response.json()["detail"] == "Test version conflict"
    mock_handle_command.assert_called_once()


@patch("app.api.v1.endpoints.cases.handle_create_case_command", new_callable=AsyncMock)
async def test_create_case_kafka_error(mock_handle_command: AsyncMock, client: TestClient):
    payload = create_sample_create_case_command_payload()
    mock_handle_command.side_effect = KafkaProducerError("Kafka is down for testing")

    response = client.post("/api/v1/cases", json=payload)

    assert response.status_code == 502 # Bad Gateway (as Kafka is an external system)
    assert response.json()["detail"] == "Error sending notification event to Kafka: Kafka is down for testing"
    mock_handle_command.assert_called_once()


@patch("app.api.v1.endpoints.cases.handle_create_case_command", new_callable=AsyncMock)
async def test_create_case_value_error_from_handler(mock_handle_command: AsyncMock, client: TestClient):
    payload = create_sample_create_case_command_payload()
    mock_handle_command.side_effect = ValueError("Some internal validation failed in handler")

    response = client.post("/api/v1/cases", json=payload)

    assert response.status_code == 400 # Bad Request
    assert response.json()["detail"] == "Some internal validation failed in handler"
    mock_handle_command.assert_called_once()


@patch("app.api.v1.endpoints.cases.handle_create_case_command", new_callable=AsyncMock)
async def test_create_case_unexpected_server_error(mock_handle_command: AsyncMock, client: TestClient):
    payload = create_sample_create_case_command_payload()
    mock_handle_command.side_effect = Exception("Totally unexpected error")

    response = client.post("/api/v1/cases", json=payload)

    assert response.status_code == 500 # Internal Server Error
    assert "Internal server error" in response.json()["detail"]
    # assert "Totally unexpected error" in response.json()["detail"] # Depending on error propagation
    mock_handle_command.assert_called_once()
