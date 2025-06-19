import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from fastapi.testclient import TestClient
from app.main import app # Import the FastAPI app instance
from app.config import settings # To access settings.SERVICE_NAME_API

# --- Fixtures ---

@pytest.fixture
def client():
    # Ensure dependency overrides are clear before and after each test using this client
    app.dependency_overrides = {}
    yield TestClient(app)
    app.dependency_overrides = {}


@pytest.fixture
def mock_db_session():
    db = MagicMock() # Using MagicMock as get_db is a regular function returning a session-like object
    db.command = AsyncMock() # The 'ping' command is an async operation
    return db

# --- Tests for GET /health ---

def test_health_check_db_connected(client: TestClient, mock_db_session: MagicMock):
    # Configure mock_db to simulate successful ping
    mock_db_session.command.return_value = {"ok": 1}

    # Override the get_db dependency for this test
    from app.api.dependencies import get_db # Import here to avoid issues with app loading
    app.dependency_overrides[get_db] = lambda: mock_db_session

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "components": {"mongodb": "connected"},
        "service_name": settings.SERVICE_NAME_API
    }
    mock_db_session.command.assert_called_once_with('ping')

    # Clean up overrides
    app.dependency_overrides = {}


def test_health_check_db_disconnected(client: TestClient, mock_db_session: MagicMock):
    # Configure mock_db to simulate failed ping
    mock_db_session.command.side_effect = Exception("Connection failed")

    from app.api.dependencies import get_db
    app.dependency_overrides[get_db] = lambda: mock_db_session

    response = client.get("/api/v1/health")

    assert response.status_code == 200 # The endpoint itself should still return 200
    assert response.json() == {
        "status": "ok", # Overall status is 'ok' as per current logic, only component fails
        "components": {"mongodb": "disconnected"},
        "service_name": settings.SERVICE_NAME_API
    }
    mock_db_session.command.assert_called_once_with('ping')

    app.dependency_overrides = {}


# Using patch for settings directly as it's simpler for module-level constants
@patch("app.config.settings.SERVICE_NAME_API", "TestServiceName")
def test_health_check_service_name_configurable(client: TestClient, mock_db_session: MagicMock):
    mock_db_session.command.return_value = {"ok": 1}

    from app.api.dependencies import get_db
    app.dependency_overrides[get_db] = lambda: mock_db_session

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["service_name"] == "TestServiceName"

    app.dependency_overrides = {}
