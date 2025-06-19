import pytest
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from app.main import app # Import the FastAPI app instance
from app.db import db_schemas # For RawEventDB

# --- Fixtures ---

@pytest.fixture
def client():
    # Ensure dependency overrides are clear before and after each test using this client
    app.dependency_overrides = {}
    yield TestClient(app)
    app.dependency_overrides = {}

@pytest.fixture
def mock_db_session_for_raw_events():
    db_session = MagicMock()

    # Mock the fluent interface for raw_events collection
    mock_find_result = MagicMock()
    mock_limit_result = MagicMock()
    mock_skip_result = MagicMock()
    mock_sort_result = MagicMock()

    db_session.raw_events = MagicMock()
    db_session.raw_events.find.return_value = mock_find_result
    mock_find_result.limit.return_value = mock_limit_result
    mock_limit_result.skip.return_value = mock_skip_result
    mock_skip_result.sort.return_value = mock_sort_result
    # to_list is an async method
    mock_sort_result.to_list = AsyncMock()

    return db_session

# Sample data for tests
def create_sample_raw_event_dict(event_id: str = None) -> dict:
    return {
        "_id": str(uuid.uuid4()), # MongoDB primary key
        "event_id": event_id or str(uuid.uuid4()),
        "aggregate_id": str(uuid.uuid4()),
        "event_type": "CaseCreatedEvent",
        "payload": {"case_type": "KYC", "user": "test"},
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(), # Store as ISO string
        "received_at": datetime.now(timezone.utc).isoformat() # Store as ISO string
    }

# --- Tests for GET /events/raw ---

MODULE_PATH_RAW_EVENTS_API = "app.api.v1.endpoints.raw_events"

def test_list_raw_events_success(client: TestClient, mock_db_session_for_raw_events: MagicMock):
    sample_event1_dict = create_sample_raw_event_dict()
    sample_event2_dict = create_sample_raw_event_dict()

    # Configure the final to_list call
    mock_db_session_for_raw_events.raw_events.find().limit().skip().sort().to_list.return_value = [
        sample_event1_dict, sample_event2_dict
    ]

    # Override get_db dependency
    from app.api.dependencies import get_db
    app.dependency_overrides[get_db] = lambda: mock_db_session_for_raw_events

    response = client.get("/api/v1/events/raw")

    assert response.status_code == 200
    # FastAPI will automatically convert datetimes to ISO strings in the response
    # RawEventDB model expects datetime objects for created_at, received_at
    # For comparison, convert dicts to RawEventDB then dump, or ensure dict fields match response
    expected_response = [
        db_schemas.RawEventDB(**sample_event1_dict).model_dump(by_alias=True),
        db_schemas.RawEventDB(**sample_event2_dict).model_dump(by_alias=True)
    ]
    assert response.json() == expected_response

    # Verifications
    mock_db_session_for_raw_events.raw_events.find.assert_called_once_with({}) # Default filter
    mock_db_session_for_raw_events.raw_events.find().limit.assert_called_once_with(10) # Default limit
    mock_db_session_for_raw_events.raw_events.find().limit().skip.assert_called_once_with(0) # Default skip
    mock_db_session_for_raw_events.raw_events.find().limit().skip().sort.assert_called_once_with("received_at", -1) # Default sort


def test_list_raw_events_with_pagination(client: TestClient, mock_db_session_for_raw_events: MagicMock):
    mock_db_session_for_raw_events.raw_events.find().limit().skip().sort().to_list.return_value = [] # Content doesn't matter

    from app.api.dependencies import get_db
    app.dependency_overrides[get_db] = lambda: mock_db_session_for_raw_events

    response = client.get("/api/v1/events/raw?skip=5&limit=50")

    assert response.status_code == 200
    mock_db_session_for_raw_events.raw_events.find().limit.assert_called_once_with(50)
    mock_db_session_for_raw_events.raw_events.find().limit().skip.assert_called_once_with(5)
    mock_db_session_for_raw_events.raw_events.find().limit().skip().sort.assert_called_once_with("received_at", -1) # Default sort still applies


def test_list_raw_events_empty(client: TestClient, mock_db_session_for_raw_events: MagicMock):
    mock_db_session_for_raw_events.raw_events.find().limit().skip().sort().to_list.return_value = []

    from app.api.dependencies import get_db
    app.dependency_overrides[get_db] = lambda: mock_db_session_for_raw_events

    response = client.get("/api/v1/events/raw")

    assert response.status_code == 200
    assert response.json() == []


def test_list_raw_events_server_error(client: TestClient, mock_db_session_for_raw_events: MagicMock):
    mock_db_session_for_raw_events.raw_events.find().limit().skip().sort().to_list.side_effect = Exception("DB error")

    from app.api.dependencies import get_db
    app.dependency_overrides[get_db] = lambda: mock_db_session_for_raw_events

    response = client.get("/api/v1/events/raw")

    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to retrieve raw events: DB error"
