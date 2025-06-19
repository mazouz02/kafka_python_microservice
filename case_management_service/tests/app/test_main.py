import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi import FastAPI
import httpx # For type hinting and errors

# Module to test - importing the specific event handlers and the app object
from case_management_service.app.main import startup_event, shutdown_event, app as main_app_instance
from case_management_service.app.config import settings


@pytest.fixture
def mock_app():
    """Provides a mock FastAPI app instance with a state."""
    app = FastAPI()
    app.state = MagicMock() # Allows arbitrary attributes to be set/checked
    # Ensure http_client is not set initially for some startup tests
    if hasattr(app.state, 'http_client'):
        del app.state.http_client
    return app

@pytest.mark.asyncio
@patch('case_management_service.app.main.httpx.AsyncClient')
@patch('case_management_service.app.main.HTTPXClientInstrumentor')
@patch('case_management_service.app.main.connect_to_mongo')
@patch('case_management_service.app.main.get_db') # Mock the async generator
@patch('case_management_service.app.main.PymongoInstrumentor')
@patch('case_management_service.app.main.startup_kafka_producer', new_callable=AsyncMock)
@patch('case_management_service.app.main.logger')
async def test_startup_event_success(
    mock_logger,
    mock_startup_kafka_producer,
    mock_pymongo_instrumentor,
    mock_get_db,
    mock_connect_to_mongo,
    mock_httpx_instrumentor,
    mock_async_client_constructor,
    mock_app # Use the fixture
):
    # Arrange
    mock_async_client_instance = AsyncMock(spec=httpx.AsyncClient)
    mock_async_client_constructor.return_value = mock_async_client_instance

    # Configure mock_get_db to be an async generator that yields once
    async def mock_get_db_generator():
        yield AsyncMock() # Yield a mock DB connection/session if needed by other code
        # No more yields to simulate it running once
    mock_get_db.return_value = mock_get_db_generator()

    # Act
    # Temporarily assign our mock_app to the global 'app' variable in main.py
    # This is because startup_event directly references the global 'app'
    with patch('case_management_service.app.main.app', mock_app):
        await startup_event()

    # Assert
    mock_async_client_constructor.assert_called_once_with(timeout=settings.DEFAULT_HTTP_TIMEOUT)
    assert mock_app.state.http_client == mock_async_client_instance
    mock_httpx_instrumentor.return_value.instrument.assert_called_once()

    mock_connect_to_mongo.assert_called_once()
    mock_get_db.assert_called_once() # Check if the generator was entered

    mock_pymongo_instrumentor.return_value.instrument.assert_called_once()
    mock_startup_kafka_producer.assert_called_once()

    # Check for specific log messages
    mock_logger.info.assert_any_call("FastAPI application startup (with routers)...")
    mock_logger.info.assert_any_call(f"HTTPX AsyncClient initialized with timeout {settings.DEFAULT_HTTP_TIMEOUT} and instrumented.")
    mock_logger.info.assert_any_call("MongoDB connection established via get_db call.")
    mock_logger.info.assert_any_call("PyMongo instrumentation complete.")
    mock_logger.info.assert_any_call("Kafka Producer polling started.")


@pytest.mark.asyncio
@patch('case_management_service.app.main.httpx.AsyncClient') # Still need to mock client creation
@patch('case_management_service.app.main.HTTPXClientInstrumentor') # and instrumentor
@patch('case_management_service.app.main.connect_to_mongo')
@patch('case_management_service.app.main.logger')
async def test_startup_event_connect_to_mongo_failure(
    mock_logger,
    mock_connect_to_mongo,
    mock_httpx_instrumentor, # To avoid UnboundLocalError if connect_to_mongo fails early
    mock_async_client_constructor, # To avoid UnboundLocalError
    mock_app
):
    # Arrange
    mock_async_client_constructor.return_value = AsyncMock(spec=httpx.AsyncClient) # Basic mock for http client
    mock_connect_to_mongo.side_effect = Exception("Mongo connection failed miserably")

    # Act
    with patch('case_management_service.app.main.app', mock_app):
        await startup_event()

    # Assert
    # HTTPX client setup should still happen before connect_to_mongo
    mock_async_client_constructor.assert_called_once()
    mock_httpx_instrumentor.return_value.instrument.assert_called_once()

    mock_connect_to_mongo.assert_called_once() # It was called
    mock_logger.error.assert_called_once()
    log_message = mock_logger.error.call_args[0][0]
    assert "Failed during startup: Mongo connection failed miserably" in log_message


@pytest.mark.asyncio
@patch('case_management_service.app.main.shutdown_kafka_producer', new_callable=AsyncMock)
@patch('case_management_service.app.main.close_mongo_connection')
@patch('case_management_service.app.main.logger')
async def test_shutdown_event_success(
    mock_logger,
    mock_close_mongo_connection,
    mock_shutdown_kafka_producer,
    mock_app # Use the fixture
):
    # Arrange
    mock_http_client_instance = AsyncMock(spec=httpx.AsyncClient)
    mock_app.state.http_client = mock_http_client_instance

    # Act
    # Patch the global 'app' instance in main.py for the duration of this call
    with patch('case_management_service.app.main.app', mock_app):
        await shutdown_event()

    # Assert
    mock_http_client_instance.aclose.assert_called_once()
    mock_shutdown_kafka_producer.assert_called_once()
    mock_close_mongo_connection.assert_called_once()

    mock_logger.info.assert_any_call("FastAPI application shutdown...")
    mock_logger.info.assert_any_call("HTTPX AsyncClient closed.")
    mock_logger.info.assert_any_call("Kafka Producer shutdown initiated and flushed.")
    mock_logger.info.assert_any_call("MongoDB connection closed.")


@pytest.mark.asyncio
@patch('case_management_service.app.main.shutdown_kafka_producer', new_callable=AsyncMock)
@patch('case_management_service.app.main.close_mongo_connection')
@patch('case_management_service.app.main.logger')
async def test_shutdown_event_no_http_client(
    mock_logger,
    mock_close_mongo_connection,
    mock_shutdown_kafka_producer,
    mock_app # Use the fixture
):
    # Arrange: Ensure no http_client is on app.state
    if hasattr(mock_app.state, 'http_client'):
        del mock_app.state.http_client

    # Act
    with patch('case_management_service.app.main.app', mock_app):
        await shutdown_event()

    # Assert
    # aclose should not be called if client doesn't exist
    # No direct way to assert it wasn't called on a non-existent attribute without more complex mocking.
    # The check `hasattr(app.state, 'http_client')` in shutdown_event handles this.

    mock_shutdown_kafka_producer.assert_called_once()
    mock_close_mongo_connection.assert_called_once()

    # Verify that "HTTPX AsyncClient closed." was NOT logged
    log_info_calls = [call_args[0][0] for call_args in mock_logger.info.call_args_list]
    assert "HTTPX AsyncClient closed." not in log_info_calls
    assert "FastAPI application shutdown..." in log_info_calls # Ensure other logs are present
