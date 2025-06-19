import pytest
import uuid
from unittest.mock import AsyncMock, patch, ANY

from fastapi.testclient import TestClient
from app.main import app # Import the FastAPI app instance
from app.db import db_schemas
from app.service.models import Role # For creating sample PersonDB

# --- Fixtures ---

@pytest.fixture
def client():
    return TestClient(app)

# Sample data for tests
SAMPLE_CASE_ID = str(uuid.uuid4())
SAMPLE_PERSON_ID_1 = str(uuid.uuid4())
SAMPLE_PERSON_ID_2 = str(uuid.uuid4())

def create_sample_person_db(person_id: str, case_id: str) -> db_schemas.PersonDB:
    # This PersonDB schema is a simplified representation of what might be in PersonCaseLinkDB
    # or a dedicated Person read model. Adjust fields as necessary.
    return db_schemas.PersonDB(
        id=str(uuid.uuid4()), # Primary key of the read model entry
        person_id=person_id,
        case_id=case_id,
        name="Test Person",
        email="test.person@example.com",
        role=Role.PRIMARY_CONTACT.value,
        version=1,
        created_at="2023-01-01T00:00:00Z",
        updated_at="2023-01-01T00:00:00Z"
    )

# --- Tests for GET /persons/case/{case_id} ---

MODULE_PATH_PERSONS_API = "app.api.v1.endpoints.persons"

@patch(f"{MODULE_PATH_PERSONS_API}.read_model_ops.list_persons_for_case_from_read_model", new_callable=AsyncMock)
async def test_list_persons_for_case_success(mock_list_persons: AsyncMock, client: TestClient):
    person1 = create_sample_person_db(person_id=SAMPLE_PERSON_ID_1, case_id=SAMPLE_CASE_ID)
    person2 = create_sample_person_db(person_id=SAMPLE_PERSON_ID_2, case_id=SAMPLE_CASE_ID)
    mock_list_persons.return_value = [person1, person2]

    response = client.get(f"/api/v1/persons/case/{SAMPLE_CASE_ID}")

    assert response.status_code == 200
    expected_json = [person1.model_dump(by_alias=True), person2.model_dump(by_alias=True)]
    assert response.json() == expected_json
    mock_list_persons.assert_called_once_with(db=ANY, case_id=SAMPLE_CASE_ID, skip=0, limit=10) # Default pagination

@patch(f"{MODULE_PATH_PERSONS_API}.read_model_ops.list_persons_for_case_from_read_model", new_callable=AsyncMock)
async def test_list_persons_for_case_with_pagination(mock_list_persons: AsyncMock, client: TestClient):
    mock_list_persons.return_value = [] # Content doesn't matter for this test

    response = client.get(f"/api/v1/persons/case/{SAMPLE_CASE_ID}?skip=5&limit=50")

    assert response.status_code == 200
    mock_list_persons.assert_called_once_with(db=ANY, case_id=SAMPLE_CASE_ID, skip=5, limit=50)

@patch(f"{MODULE_PATH_PERSONS_API}.read_model_ops.list_persons_for_case_from_read_model", new_callable=AsyncMock)
async def test_list_persons_for_case_empty(mock_list_persons: AsyncMock, client: TestClient):
    mock_list_persons.return_value = []

    response = client.get(f"/api/v1/persons/case/{SAMPLE_CASE_ID}")

    assert response.status_code == 200
    assert response.json() == []
    mock_list_persons.assert_called_once_with(db=ANY, case_id=SAMPLE_CASE_ID, skip=0, limit=10)

@patch(f"{MODULE_PATH_PERSONS_API}.read_model_ops.list_persons_for_case_from_read_model", new_callable=AsyncMock)
async def test_list_persons_for_case_server_error(mock_list_persons: AsyncMock, client: TestClient):
    mock_list_persons.side_effect = Exception("DB error")

    response = client.get(f"/api/v1/persons/case/{SAMPLE_CASE_ID}")

    assert response.status_code == 500
    assert response.json()["detail"] == f"Failed to list persons for case {SAMPLE_CASE_ID}: DB error"
