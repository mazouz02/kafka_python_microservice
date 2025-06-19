import pytest
from unittest.mock import AsyncMock, MagicMock
import datetime
import uuid

from motor.motor_asyncio import AsyncIOMotorDatabase, AsyncIOMotorCollection

# Modules to test
from case_management_service.infrastructure.database.event_store import save_event, get_events_for_aggregate, EVENT_STORE_COLLECTION
from case_management_service.app.service.events.models import BaseEvent, EventMetaData, CaseCreatedEvent, CaseCreatedEventPayload
from case_management_service.app.models import StoredEventDB

# Custom Exceptions
from case_management_service.app.service.exceptions import ConcurrencyConflictError


@pytest.fixture
def mock_db_collection():
    collection = AsyncMock(spec=AsyncIOMotorCollection)
    return collection

@pytest.fixture
def mock_db(mock_db_collection: AsyncIOMotorCollection):
    db = AsyncMock(spec=AsyncIOMotorDatabase)
    db.__getitem__.return_value = mock_db_collection # Make db["collection_name"] work
    return db

@pytest.fixture
def sample_event_data() -> CaseCreatedEvent:
    return CaseCreatedEvent(
        aggregate_id=str(uuid.uuid4()),
        version=1,
        payload=CaseCreatedEventPayload(client_id="client1", case_type="KYC", case_version="v1", traitement_type="INDIVIDUAL"),
        metadata=EventMetaData()
    )

@pytest.mark.asyncio
async def test_save_event_success_first_event(mock_db: AsyncIOMotorDatabase, mock_db_collection: AsyncIOMotorCollection, sample_event_data: CaseCreatedEvent):
    mock_db_collection.find_one.return_value = None # No existing event for this aggregate

    returned_event = await save_event(mock_db, sample_event_data)

    mock_db_collection.find_one.assert_called_once_with(
        {"aggregate_id": sample_event_data.aggregate_id}, sort=[("version", -1)]
    )
    mock_db_collection.insert_one.assert_called_once()

    # Check the argument passed to insert_one
    inserted_doc = mock_db_collection.insert_one.call_args[0][0]
    assert inserted_doc["event_id"] == sample_event_data.event_id
    assert inserted_doc["aggregate_id"] == sample_event_data.aggregate_id
    assert inserted_doc["version"] == sample_event_data.version
    assert inserted_doc["payload"] == sample_event_data.payload.model_dump()

    assert returned_event == sample_event_data

@pytest.mark.asyncio
async def test_save_event_success_subsequent_event(mock_db: AsyncIOMotorDatabase, mock_db_collection: AsyncIOMotorCollection, sample_event_data: CaseCreatedEvent):
    existing_event_doc = {
        "aggregate_id": sample_event_data.aggregate_id,
        "version": 1, # Previous version
        # ... other fields
    }
    mock_db_collection.find_one.return_value = existing_event_doc

    sample_event_data.version = 2 # New event version

    await save_event(mock_db, sample_event_data)

    mock_db_collection.insert_one.assert_called_once()
    inserted_doc = mock_db_collection.insert_one.call_args[0][0]
    assert inserted_doc["version"] == 2


@pytest.mark.asyncio
async def test_save_event_concurrency_conflict(mock_db: AsyncIOMotorDatabase, mock_db_collection: AsyncIOMotorCollection, sample_event_data: CaseCreatedEvent):
    existing_event_doc = StoredEventDB( # Use StoredEventDB for more realistic mock
        event_id=str(uuid.uuid4()),
        event_type="SomeEvent",
        aggregate_id=sample_event_data.aggregate_id,
        timestamp=datetime.datetime.now(datetime.UTC),
        version=2, # DB has version 2
        payload={},
        metadata=EventMetaData().model_dump()
    ).model_dump()
    mock_db_collection.find_one.return_value = existing_event_doc

    sample_event_data.version = 2 # Attempting to save event with same or older version

    with pytest.raises(ConcurrencyConflictError) as exc_info:
        await save_event(mock_db, sample_event_data)

    assert exc_info.value.aggregate_id == sample_event_data.aggregate_id
    assert exc_info.value.actual_version == 2
    # Expected version in error message might be based on command's expectation,
    # but here we test against the event's version vs DB.
    # The error message is "Attempted event version {event_data.version}, but latest version in DB is {latest_version}."
    # So, exc_info.value.expected_version in the error is event_data.version -1, which is 1 here.
    assert exc_info.value.expected_version == 1 # sample_event_data.version - 1

    mock_db_collection.insert_one.assert_not_called()


@pytest.mark.asyncio
async def test_get_events_for_aggregate_success(mock_db: AsyncIOMotorDatabase, mock_db_collection: AsyncIOMotorCollection):
    agg_id = str(uuid.uuid4())
    event_payload_dict = CaseCreatedEventPayload(client_id="c1", case_type="t1", case_version="v1", traitement_type="KYC").model_dump()

    # Mock events from DB
    mock_event_docs = [
        StoredEventDB(event_id="e1", event_type="CaseCreated", aggregate_id=agg_id, version=1, payload=event_payload_dict, metadata=EventMetaData().model_dump()).model_dump(),
        StoredEventDB(event_id="e2", event_type="CaseCreated", aggregate_id=agg_id, version=2, payload=event_payload_dict, metadata=EventMetaData().model_dump()).model_dump(),
    ]

    mock_cursor = AsyncMock()
    mock_cursor.to_list.return_value = mock_event_docs
    mock_db_collection.find.return_value = mock_cursor

    # Register CaseCreatedEvent for deserialization if not already (it is by default)
    # from case_management_service.infrastructure.database.event_store import EVENT_CLASS_MAP, PAYLOAD_CLASS_MAP
    # EVENT_CLASS_MAP["CaseCreated"] = CaseCreatedEvent
    # PAYLOAD_CLASS_MAP["CaseCreatedEventPayload"] = CaseCreatedEventPayload

    events = await get_events_for_aggregate(mock_db, agg_id)

    mock_db_collection.find.assert_called_once_with({"aggregate_id": agg_id})
    mock_cursor.sort.assert_called_once_with("version", 1)

    assert len(events) == 2
    assert isinstance(events[0], CaseCreatedEvent)
    assert events[0].event_id == "e1"
    assert events[0].version == 1
    assert events[1].version == 2
    assert events[0].payload.client_id == "c1"

@pytest.mark.asyncio
async def test_get_events_for_aggregate_no_events(mock_db: AsyncIOMotorDatabase, mock_db_collection: AsyncIOMotorCollection):
    agg_id = str(uuid.uuid4())
    mock_cursor = AsyncMock()
    mock_cursor.to_list.return_value = [] # No events found
    mock_db_collection.find.return_value = mock_cursor

    events = await get_events_for_aggregate(mock_db, agg_id)

    assert len(events) == 0

# TODO: Add tests for deserialization errors, missing mappers in get_events_for_aggregate
# For example, if an event_type in DB doesn't map to a class in EVENT_CLASS_MAP
# or if payload doesn't match the Pydantic model.
# These would involve more specific mocking of the event_doc content.
