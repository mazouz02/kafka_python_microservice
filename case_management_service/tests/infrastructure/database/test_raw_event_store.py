import pytest
from unittest.mock import AsyncMock, MagicMock
import datetime
import uuid

from case_management_service.infrastructure.database import raw_event_store as store
from case_management_service.infrastructure.database.schemas import RawEventDB

@pytest.fixture
def mock_db():
    db = AsyncMock()
    # Mock the collection directly
    db.raw_events = AsyncMock()
    return db

@pytest.mark.asyncio
async def test_store_raw_event(mock_db):
    event_payload = {"data_key": "data_value", "source": "test_source"}
    event_type = "TEST_RAW_EVENT"

    # Mock the insert_one operation
    mock_db.raw_events.insert_one = AsyncMock()

    stored_event = await store.store_raw_event(mock_db, event_payload, event_type)

    assert isinstance(stored_event, RawEventDB)
    assert stored_event.payload == event_payload
    assert stored_event.event_type == event_type
    assert isinstance(stored_event.id, str) # Default UUID from model
    assert isinstance(stored_event.received_at, datetime.datetime)

    mock_db.raw_events.insert_one.assert_called_once()
    inserted_doc = mock_db.raw_events.insert_one.call_args[0][0]
    assert inserted_doc["payload"] == event_payload
    assert inserted_doc["event_type"] == event_type
    assert inserted_doc["id"] == stored_event.id
    assert inserted_doc["received_at"] == stored_event.received_at

@pytest.mark.asyncio
async def test_list_raw_events_with_filters(mock_db):
    start_time_filter = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
    end_time_filter = datetime.datetime.now(datetime.timezone.utc)
    event_type_filter = "SPECIFIC_EVENT_TYPE"
    limit_filter = 50

    # Sample documents that would be returned from the DB
    raw_event_docs_from_db = [
        {
            "id": str(uuid.uuid4()), "event_type": event_type_filter,
            "payload": {"key": "value1"},
            "received_at": start_time_filter + datetime.timedelta(minutes=10)
        },
        {
            "id": str(uuid.uuid4()), "event_type": event_type_filter,
            "payload": {"key": "value2"},
            "received_at": start_time_filter + datetime.timedelta(minutes=20)
        },
    ]

    mock_cursor = MagicMock()
    mock_cursor.sort.return_value = mock_cursor # find().sort()
    mock_cursor.limit.return_value = mock_cursor # sort().limit()
    mock_cursor.skip.return_value = mock_cursor  # limit().skip()
    mock_cursor.to_list = AsyncMock(return_value=raw_event_docs_from_db) # skip().to_list()
    mock_db.raw_events.find.return_value = mock_cursor

    results = await store.list_raw_events(
        db=mock_db,
        start_time=start_time_filter,
        end_time=end_time_filter,
        event_type=event_type_filter,
        limit=limit_filter,
        skip=0
    )

    assert len(results) == 2
    assert results[0].event_type == event_type_filter

    expected_query_filter = {
        "received_at": {
            "$gte": start_time_filter,
            "$lte": end_time_filter
        },
        "event_type": event_type_filter
    }
    mock_db.raw_events.find.assert_called_once_with(expected_query_filter)
    mock_cursor.sort.assert_called_once_with("received_at", -1) # pymongo.DESCENDING
    mock_cursor.limit.assert_called_once_with(limit_filter)
    mock_cursor.skip.assert_called_once_with(0)
    mock_cursor.to_list.assert_called_once_with(length=limit_filter)

@pytest.mark.asyncio
async def test_list_raw_events_no_filters(mock_db):
    now = datetime.datetime.now(datetime.timezone.utc)
    raw_event_docs_from_db = [
        {"id": str(uuid.uuid4()), "event_type": "ANY_TYPE", "payload": {}, "received_at": now}
    ]

    mock_cursor = MagicMock()
    mock_cursor.sort.return_value = mock_cursor
    mock_cursor.limit.return_value = mock_cursor
    mock_cursor.skip.return_value = mock_cursor
    mock_cursor.to_list = AsyncMock(return_value=raw_event_docs_from_db)
    mock_db.raw_events.find.return_value = mock_cursor

    results = await store.list_raw_events(db=mock_db, limit=10, skip=0) # Default limit is 100

    assert len(results) == 1
    mock_db.raw_events.find.assert_called_once_with({}) # Empty filter
    mock_cursor.sort.assert_called_once_with("received_at", -1)
    mock_cursor.limit.assert_called_once_with(10)
    mock_cursor.skip.assert_called_once_with(0)
    mock_cursor.to_list.assert_called_once_with(length=10)

@pytest.mark.asyncio
async def test_list_raw_events_only_start_time_filter(mock_db):
    start_time_filter = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)

    mock_cursor = MagicMock()
    mock_cursor.sort.return_value = mock_cursor
    mock_cursor.limit.return_value = mock_cursor
    mock_cursor.skip.return_value = mock_cursor
    mock_cursor.to_list = AsyncMock(return_value=[]) # Don't care about results for this, just filter
    mock_db.raw_events.find.return_value = mock_cursor

    await store.list_raw_events(db=mock_db, start_time=start_time_filter)

    expected_query_filter = {"received_at": {"$gte": start_time_filter}}
    mock_db.raw_events.find.assert_called_once_with(expected_query_filter)

@pytest.mark.asyncio
async def test_list_raw_events_only_end_time_filter(mock_db):
    end_time_filter = datetime.datetime.now(datetime.timezone.utc)

    mock_cursor = MagicMock()
    mock_cursor.sort.return_value = mock_cursor
    mock_cursor.limit.return_value = mock_cursor
    mock_cursor.skip.return_value = mock_cursor
    mock_cursor.to_list = AsyncMock(return_value=[])
    mock_db.raw_events.find.return_value = mock_cursor

    await store.list_raw_events(db=mock_db, end_time=end_time_filter)

    expected_query_filter = {"received_at": {"$lte": end_time_filter}}
    mock_db.raw_events.find.assert_called_once_with(expected_query_filter)

@pytest.mark.asyncio
async def test_list_raw_events_only_event_type_filter(mock_db):
    event_type_filter = "MY_EVENT"

    mock_cursor = MagicMock()
    mock_cursor.sort.return_value = mock_cursor
    mock_cursor.limit.return_value = mock_cursor
    mock_cursor.skip.return_value = mock_cursor
    mock_cursor.to_list = AsyncMock(return_value=[])
    mock_db.raw_events.find.return_value = mock_cursor

    await store.list_raw_events(db=mock_db, event_type=event_type_filter)

    expected_query_filter = {"event_type": event_type_filter}
    mock_db.raw_events.find.assert_called_once_with(expected_query_filter)
