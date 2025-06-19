import pytest
from unittest.mock import AsyncMock, MagicMock
import datetime
import uuid

from case_management_service.infrastructure.database import document_requirements_store as store
from case_management_service.infrastructure.database.schemas import RequiredDocumentDB, StoredEventMetaData
from case_management_service.app.models.required_document_db import RequiredDocumentStatus # Enum for status

@pytest.fixture
def mock_db():
    db = AsyncMock()
    # Mock the collection directly
    db.document_requirements = AsyncMock()
    return db

@pytest.mark.asyncio
async def test_store_document_requirement(mock_db):
    doc_id = str(uuid.uuid4())
    case_id = str(uuid.uuid4())
    entity_id = str(uuid.uuid4())
    now = datetime.datetime.now(datetime.timezone.utc)

    doc_requirement_data = RequiredDocumentDB(
        id=doc_id,
        case_id=case_id,
        entity_id=entity_id,
        entity_type="PERSON",
        document_type="PASSPORT",
        status=RequiredDocumentStatus.AWAITING_UPLOAD,
        is_required=True,
        version=1,
        created_at=now,
        updated_at=now,
        metadata={},
        notes=[]
    )

    # Mock the insert_one operation
    mock_db.document_requirements.insert_one = AsyncMock()

    result = await store.store_document_requirement(mock_db, doc_requirement_data)

    assert result == doc_requirement_data
    mock_db.document_requirements.insert_one.assert_called_once()
    inserted_doc = mock_db.document_requirements.insert_one.call_args[0][0]
    assert inserted_doc["id"] == doc_id
    assert inserted_doc["case_id"] == case_id
    assert inserted_doc["document_type"] == "PASSPORT"

@pytest.mark.asyncio
async def test_get_required_document_by_id_found(mock_db):
    doc_id = str(uuid.uuid4())
    now = datetime.datetime.now(datetime.timezone.utc)
    expected_doc_dict = {
        "id": doc_id, "case_id": "c1", "entity_id": "e1", "entity_type": "PERSON",
        "document_type": "PASSPORT", "status": "AWAITING_UPLOAD", "is_required": True,
        "version": 1, "created_at": now, "updated_at": now, "metadata": {}, "notes": []
    }
    mock_db.document_requirements.find_one.return_value = expected_doc_dict

    result = await store.get_required_document_by_id(mock_db, doc_id)

    assert result is not None
    assert result.id == doc_id
    assert result.document_type == "PASSPORT"
    mock_db.document_requirements.find_one.assert_called_once_with({"id": doc_id})

@pytest.mark.asyncio
async def test_get_required_document_by_id_not_found(mock_db):
    doc_id = str(uuid.uuid4())
    mock_db.document_requirements.find_one.return_value = None

    result = await store.get_required_document_by_id(mock_db, doc_id)

    assert result is None
    mock_db.document_requirements.find_one.assert_called_once_with({"id": doc_id})

@pytest.mark.asyncio
async def test_list_required_documents_all_filters(mock_db):
    case_id_filter = str(uuid.uuid4())
    entity_id_filter = str(uuid.uuid4())
    entity_type_filter = "PERSON"
    status_filter = RequiredDocumentStatus.UPLOADED
    is_required_filter = True
    now = datetime.datetime.now(datetime.timezone.utc)

    doc_list_from_db = [
        {
            "id": str(uuid.uuid4()), "case_id": case_id_filter, "entity_id": entity_id_filter,
            "entity_type": entity_type_filter, "document_type": "PASSPORT", "status": status_filter.value,
            "is_required": is_required_filter, "version": 1, "created_at": now, "updated_at": now,
            "metadata": {}, "notes": []
        }
    ]

    mock_cursor = MagicMock()
    mock_cursor.sort.return_value = mock_cursor # find().sort()
    mock_cursor.to_list = AsyncMock(return_value=doc_list_from_db) # sort().to_list()
    mock_db.document_requirements.find.return_value = mock_cursor

    results = await store.list_required_documents(
        db=mock_db,
        case_id=case_id_filter,
        entity_id=entity_id_filter,
        entity_type=entity_type_filter,
        status=status_filter,
        is_required=is_required_filter
    )

    assert len(results) == 1
    assert results[0].id == doc_list_from_db[0]["id"]

    expected_query_filter = {
        "case_id": case_id_filter,
        "entity_id": entity_id_filter,
        "entity_type": entity_type_filter,
        "status": status_filter.value,
        "is_required": is_required_filter
    }
    mock_db.document_requirements.find.assert_called_once_with(expected_query_filter)
    mock_cursor.sort.assert_called_once_with("created_at", 1) # pymongo.ASCENDING
    mock_cursor.to_list.assert_called_once_with(length=None)


@pytest.mark.asyncio
async def test_list_required_documents_no_filters(mock_db):
    now = datetime.datetime.now(datetime.timezone.utc)
    doc_list_from_db = [
        {
            "id": str(uuid.uuid4()), "case_id": "c1", "entity_id": "e1",
            "entity_type": "PERSON", "document_type": "PASSPORT", "status": "AWAITING_UPLOAD",
            "is_required": True, "version": 1, "created_at": now, "updated_at": now,
            "metadata": {}, "notes": []
        }
    ]
    mock_cursor = MagicMock()
    mock_cursor.sort.return_value = mock_cursor
    mock_cursor.to_list = AsyncMock(return_value=doc_list_from_db)
    mock_db.document_requirements.find.return_value = mock_cursor

    results = await store.list_required_documents(db=mock_db)

    assert len(results) == 1
    mock_db.document_requirements.find.assert_called_once_with({}) # Empty filter
    mock_cursor.sort.assert_called_once_with("created_at", 1)
    mock_cursor.to_list.assert_called_once_with(length=None)


@pytest.mark.asyncio
async def test_update_document_requirement_status_success(mock_db):
    doc_id = str(uuid.uuid4())
    new_status = RequiredDocumentStatus.VERIFIED_MANUAL
    now = datetime.datetime.now(datetime.timezone.utc)

    # Mock find_one to return the document *after* update for verification
    updated_doc_dict = {
        "id": doc_id, "case_id": "c1", "entity_id": "e1", "entity_type": "PERSON",
        "document_type": "PASSPORT", "status": new_status.value, "is_required": True,
        "version": 2, "created_at": now, "updated_at": now, # updated_at should be new
        "metadata": {}, "notes": ["Status updated"]
    }
    mock_db.document_requirements.find_one.return_value = updated_doc_dict
    mock_db.document_requirements.update_one.return_value = MagicMock(matched_count=1, modified_count=1)

    result = await store.update_document_requirement_status(mock_db, doc_id, new_status, ["Status updated"])

    assert result is not None
    assert result.id == doc_id
    assert result.status == new_status
    assert "Status updated" in result.notes

    mock_db.document_requirements.update_one.assert_called_once()
    update_call_args = mock_db.document_requirements.update_one.call_args[0]
    assert update_call_args[0] == {"id": doc_id} # Filter
    assert update_call_args[1]["$set"]["status"] == new_status.value
    assert update_call_args[1]["$inc"]["version"] == 1
    assert "$currentDate" in update_call_args[1]
    assert "updated_at" in update_call_args[1]["$currentDate"]
    assert update_call_args[1]["$push"]["notes"]["$each"] == ["Status updated"]

@pytest.mark.asyncio
async def test_update_document_requirement_status_not_found(mock_db):
    doc_id = str(uuid.uuid4())
    new_status = RequiredDocumentStatus.REJECTED

    mock_db.document_requirements.update_one.return_value = MagicMock(matched_count=0, modified_count=0)
    # find_one should also return None if update failed due to not found
    mock_db.document_requirements.find_one.return_value = None

    result = await store.update_document_requirement_status(mock_db, doc_id, new_status)

    assert result is None
    mock_db.document_requirements.update_one.assert_called_once()

@pytest.mark.asyncio
async def test_update_document_is_required_success(mock_db):
    doc_id = str(uuid.uuid4())
    is_required_new_value = False
    now = datetime.datetime.now(datetime.timezone.utc)

    updated_doc_dict = {
        "id": doc_id, "case_id": "c1", "entity_id": "e1", "entity_type": "PERSON",
        "document_type": "PASSPORT", "status": "AWAITING_UPLOAD", "is_required": is_required_new_value,
        "version": 2, "created_at": now, "updated_at": now,
        "metadata": {}, "notes": ["Is_required updated"]
    }
    mock_db.document_requirements.find_one.return_value = updated_doc_dict
    mock_db.document_requirements.update_one.return_value = MagicMock(matched_count=1, modified_count=1)

    result = await store.update_document_is_required(mock_db, doc_id, is_required_new_value, ["Is_required updated"])

    assert result is not None
    assert result.id == doc_id
    assert result.is_required == is_required_new_value
    assert "Is_required updated" in result.notes

    mock_db.document_requirements.update_one.assert_called_once()
    update_call_args = mock_db.document_requirements.update_one.call_args[0]
    assert update_call_args[0] == {"id": doc_id}
    assert update_call_args[1]["$set"]["is_required"] == is_required_new_value
    assert update_call_args[1]["$inc"]["version"] == 1
    assert "$currentDate" in update_call_args[1]
    assert "updated_at" in update_call_args[1]["$currentDate"]
    assert update_call_args[1]["$push"]["notes"]["$each"] == ["Is_required updated"]

@pytest.mark.asyncio
async def test_update_document_is_required_not_found(mock_db):
    doc_id = str(uuid.uuid4())
    is_required_new_value = False

    mock_db.document_requirements.update_one.return_value = MagicMock(matched_count=0, modified_count=0)
    mock_db.document_requirements.find_one.return_value = None

    result = await store.update_document_is_required(mock_db, doc_id, is_required_new_value)

    assert result is None
    mock_db.document_requirements.update_one.assert_called_once()
