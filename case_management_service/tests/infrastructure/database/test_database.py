# Unit Tests for Database Functions (Refactored Structure)
import asyncio # Keep for clarity
import pytest
from unittest.mock import patch, AsyncMock, MagicMock, call
import datetime
import uuid

# Modules to test - new locations
from case_management_service.infrastructure.database import connection as db_connection
from case_management_service.infrastructure.database import event_store as db_event_store
# Removed: read_models, raw_event_store, document_requirements_store imports as their tests are now separate
# Updated schema import to include all necessary schemas
from case_management_service.infrastructure.database import schemas as db_schemas # Keep for schema tests
from case_management_service.app.service.events import models as domain_event_models # Keep for event_store tests
# Import ConcurrencyConflictError for testing
from case_management_service.app.service.exceptions import ConcurrencyConflictError
from case_management_service.app import config
from case_management_service.infrastructure.kafka.schemas import AddressData


# Helper to reset global db client in database.connection module
def reset_db_connection_module_state():
    db_connection.client = None
    db_connection.db = None

# Helper for async iterable mock - can be removed if not used elsewhere after refactor
# async def async_iterable(items):
# for item in items:
# yield item

TEST_DB_NAME = config.settings.DB_NAME # Use a constant for the DB Name

@pytest.fixture(autouse=True)
def auto_reset_db_module_state():
    """Ensures db_connection module is reset before and after each test."""
    reset_db_connection_module_state()
    yield
    reset_db_connection_module_state()

# --- Tests for infrastructure.database.connection ---
@pytest.mark.asyncio
@patch('case_management_service.infrastructure.database.connection.MongoClient')
async def test_connect_to_mongo_success(mock_mongo_client_cls):
    mock_client_instance = MagicMock()
    mock_client_instance.admin.command.return_value = {"ok": 1}
    mock_mongo_client_cls.return_value = mock_client_instance

    db_connection.connect_to_mongo()

    mock_mongo_client_cls.assert_called_once_with(config.settings.MONGO_DETAILS)
    mock_client_instance.admin.command.assert_called_once_with('ping')
    assert db_connection.db == mock_client_instance[TEST_DB_NAME]

    db_instance = await db_connection.get_database()
    assert db_instance == mock_client_instance[TEST_DB_NAME]
    assert mock_mongo_client_cls.call_count == 1

@pytest.mark.asyncio
@patch('case_management_service.infrastructure.database.connection.MongoClient', side_effect=ConnectionError("Mock Connection Error"))
async def test_connect_to_mongo_failure(mock_mongo_client_cls):
    with pytest.raises(ConnectionError, match="Failed to connect to MongoDB: Mock Connection Error"):
        db_connection.connect_to_mongo()
    with pytest.raises(ConnectionError, match="Failed to connect to MongoDB: Mock Connection Error"):
        await db_connection.get_database()

# --- Tests for infrastructure.database.event_store ---
@pytest.mark.asyncio
@patch('case_management_service.infrastructure.database.event_store.get_database')
async def test_save_event_new_aggregate(mock_get_db_for_event_store):
    mock_db_instance = AsyncMock()
    # Ensure the collection mock is properly configured on the db_instance mock
    mock_collection = AsyncMock()
    mock_db_instance.__getitem__.return_value = mock_collection
    mock_collection.find_one.return_value = None
    mock_collection.insert_one = AsyncMock()
    mock_get_db_for_event_store.return_value = mock_db_instance

    agg_id = str(uuid.uuid4())
    event_payload_model = domain_event_models.CaseCreatedEventPayload(
        client_id="c1", case_type="t1", case_version="v1", traitement_type="KYC"
    )
    event_to_save = domain_event_models.CaseCreatedEvent(
        aggregate_id=agg_id, payload=event_payload_model, version=1, event_type="CaseCreated"
    )

    returned_event = await db_event_store.save_event(event_to_save)

    mock_collection.insert_one.assert_called_once()
    inserted_doc = mock_collection.insert_one.call_args.args[0]
    assert isinstance(inserted_doc, dict)
    assert inserted_doc["aggregate_id"] == agg_id
    assert inserted_doc["event_type"] == "CaseCreated"
    assert inserted_doc["payload"]["client_id"] == "c1"
    assert returned_event == event_to_save

@pytest.mark.asyncio
@patch('case_management_service.infrastructure.database.event_store.get_database')
async def test_save_event_subsequent_event(mock_get_db_for_event_store):
    mock_db_instance = AsyncMock()
    mock_collection = AsyncMock()
    mock_db_instance.__getitem__.return_value = mock_collection

    agg_id = str(uuid.uuid4())
    existing_event_doc = {
        "aggregate_id": agg_id, "version": 1, "event_type": "CaseCreated",
        "payload": {}, "metadata": {}, "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "event_id": str(uuid.uuid4())
    }
    mock_collection.find_one.return_value = existing_event_doc
    mock_collection.insert_one = AsyncMock()
    mock_get_db_for_event_store.return_value = mock_db_instance

    event_payload_model = domain_event_models.CaseStatusUpdatedEventPayload(
        old_status="OPEN", new_status="PENDING"
    )
    event_to_save = domain_event_models.CaseStatusUpdatedEvent(
        aggregate_id=agg_id, payload=event_payload_model, version=2
    )

    returned_event = await db_event_store.save_event(event_to_save)

    mock_collection.find_one.assert_called_once_with(
        {"aggregate_id": agg_id}, sort=[("version", -1)]
    )
    mock_collection.insert_one.assert_called_once()
    inserted_doc = mock_collection.insert_one.call_args.args[0]
    assert inserted_doc["version"] == 2
    assert returned_event == event_to_save

@pytest.mark.asyncio
@patch('case_management_service.infrastructure.database.event_store.get_database')
async def test_save_event_concurrency_conflict(mock_get_db_for_event_store):
    mock_db_instance = AsyncMock()
    mock_collection = AsyncMock()
    mock_db_instance.__getitem__.return_value = mock_collection

    agg_id = str(uuid.uuid4())
    existing_event_doc = {
        "aggregate_id": agg_id, "version": 2, "event_type": "SomeEvent",
        "payload": {}, "metadata": {}, "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "event_id": str(uuid.uuid4())
    }
    mock_collection.find_one.return_value = existing_event_doc
    mock_get_db_for_event_store.return_value = mock_db_instance

    event_payload_model = domain_event_models.CaseCreatedEventPayload(
        client_id="c_conflict", case_type="t_conflict", case_version="v_conflict", traitement_type="KYC_CONFLICT"
    )
    event_with_conflict_version = domain_event_models.CaseCreatedEvent(
        aggregate_id=agg_id, payload=event_payload_model, version=2
    )

    with pytest.raises(ConcurrencyConflictError) as exc_info:
        await db_event_store.save_event(event_with_conflict_version)

    assert exc_info.value.aggregate_id == agg_id
    assert exc_info.value.actual_version == 2
    assert exc_info.value.expected_version == 1
    mock_collection.insert_one.assert_not_called()

@pytest.mark.asyncio
@patch('case_management_service.infrastructure.database.event_store.get_database')
async def test_get_events_for_aggregate_no_events(mock_get_db_for_event_store):
    mock_db_instance = AsyncMock()
    mock_collection = AsyncMock()
    mock_db_instance.__getitem__.return_value = mock_collection

    agg_id = str(uuid.uuid4())
    mock_sort_result = MagicMock()
    mock_sort_result.__aiter__.return_value = iter([])
    mock_find_result = MagicMock()
    mock_find_result.sort.return_value = mock_sort_result
    mock_collection.find.return_value = mock_find_result
    mock_get_db_for_event_store.return_value = mock_db_instance

    events = await db_event_store.get_events_for_aggregate(agg_id)

    assert len(events) == 0
    mock_collection.find.assert_called_once_with({"aggregate_id": agg_id})
    mock_find_result.sort.assert_called_once_with("version", 1)

# Test for new DB Schemas (Instantiation) - These are not async, no mark needed
def test_company_profile_db_schema_instantiation():
    addr = AddressData(street="1 Corp Ave", city="Corpville", country="CY", postal_code="123")
    company_db = db_schemas.CompanyProfileDB(
        id="comp_123", registered_name="Corp Inc", registration_number="C123",
        country_of_incorporation="CY", registered_address=addr
    )
    assert company_db.id == "comp_123"
    assert company_db.registered_address.city == "Corpville"
    assert company_db.created_at is not None
    assert company_db.updated_at is not None

def test_beneficial_owner_db_schema_instantiation():
    bo_db = db_schemas.BeneficialOwnerDB(
        id="bo_123", company_id="comp_123", firstname="Beneficial",
        lastname="Owner", is_ubo=True
    )
    assert bo_db.id == "bo_123"
    assert bo_db.firstname == "Beneficial"
    assert bo_db.created_at is not None
    assert bo_db.updated_at is not None

def test_required_document_db_schema_instantiation():
    doc_req = db_schemas.RequiredDocumentDB(
        case_id="case_doc_test", entity_id="entity_doc_test",
        entity_type="PERSON", document_type="PASSPORT"
    )
    assert doc_req.id is not None
    assert doc_req.case_id == "case_doc_test"
    assert doc_req.status == "AWAITING_UPLOAD"
    assert doc_req.is_required is True

# Removed tests for read_models, raw_event_store, and document_requirements_store
# as they are now in their specific test files.

# Kept event_store tests and schema instantiation tests.
@pytest.mark.asyncio
@patch('case_management_service.infrastructure.database.event_store.get_database')
async def test_get_events_for_aggregate_with_new_event_types(mock_get_db_for_event_store):
    mock_db_instance = AsyncMock()
    # Ensure the collection mock is properly configured on the db_instance mock
    mock_collection = AsyncMock()
    mock_db_instance.__getitem__.return_value = mock_collection

    agg_id_case = str(uuid.uuid4())
    agg_id_company = str(uuid.uuid4())
    # ... (rest of the setup is the same)
    addr_data = AddressData(street="s", city="c", country="US", postal_code="123")
    addr_data_dict = addr_data.model_dump()
    bo_person_details = domain_event_models.PersonData(firstname="BO", lastname="User", birthdate="1977-07-07")
    bo_person_details_dict = bo_person_details.model_dump()
    meta_dict = db_schemas.StoredEventMetaData().model_dump()

    case_event_doc = db_schemas.StoredEventDB(event_id=str(uuid.uuid4()), event_type="CaseCreated", aggregate_id=agg_id_case, timestamp=datetime.datetime.now(datetime.UTC), version=1, payload={"client_id": "c1", "case_type": "KYB", "case_version": "v1", "traitement_type": "KYB", "company_id": agg_id_company}, metadata=meta_dict).model_dump()
    company_event_docs = [
        db_schemas.StoredEventDB(event_id=str(uuid.uuid4()), event_type="CompanyProfileCreated", aggregate_id=agg_id_company, timestamp=datetime.datetime.now(datetime.UTC), version=1, payload={"registered_name": "Comp Ltd", "registration_number": "R1", "country_of_incorporation": "US", "registered_address": addr_data_dict}, metadata=meta_dict).model_dump(),
        db_schemas.StoredEventDB(event_id=str(uuid.uuid4()), event_type="BeneficialOwnerAdded", aggregate_id=agg_id_company, timestamp=datetime.datetime.now(datetime.UTC), version=2, payload={"beneficial_owner_id": str(uuid.uuid4()), "person_details": bo_person_details_dict, "is_ubo": True, "ownership_percentage": 50.0, "types_of_control": ["Voting Rights"]}, metadata=meta_dict).model_dump(),
        db_schemas.StoredEventDB(event_id=str(uuid.uuid4()), event_type="PersonLinkedToCompany", aggregate_id=agg_id_company, timestamp=datetime.datetime.now(datetime.UTC), version=3, payload={"person_id": str(uuid.uuid4()), "firstname": "Dir", "lastname": "Ector", "role_in_company": "Director", "birthdate": "1980-08-08"}, metadata=meta_dict).model_dump()
    ]

    mock_sort_result_case = MagicMock()
    mock_sort_result_case.__aiter__.return_value = iter([case_event_doc])
    mock_sort_result_company = MagicMock()
    mock_sort_result_company.__aiter__.return_value = iter(company_event_docs)
    mock_sort_result_empty = MagicMock()
    mock_sort_result_empty.__aiter__.return_value = iter([])

    def mock_find_side_effect(query_filter):
        agg_filter_id = query_filter.get("aggregate_id")
        current_find_mock = MagicMock()
        if agg_filter_id == agg_id_case:
            current_find_mock.sort.return_value = mock_sort_result_case
        elif agg_filter_id == agg_id_company:
            current_find_mock.sort.return_value = mock_sort_result_company
        else:
            current_find_mock.sort.return_value = mock_sort_result_empty
        return current_find_mock

    mock_collection.find.side_effect = mock_find_side_effect
    mock_get_db_for_event_store.return_value = mock_db_instance

    retrieved_events_case = await db_event_store.get_events_for_aggregate(agg_id_case)
    retrieved_events_company = await db_event_store.get_events_for_aggregate(agg_id_company)

    assert len(retrieved_events_case) == 1
    assert isinstance(retrieved_events_case[0], domain_event_models.CaseCreatedEvent)
    assert retrieved_events_case[0].payload.traitement_type == "KYB"
    assert retrieved_events_case[0].payload.company_id == agg_id_company

    assert len(retrieved_events_company) == 3
    assert isinstance(retrieved_events_company[0], domain_event_models.CompanyProfileCreatedEvent)
    assert retrieved_events_company[0].payload.registered_name == "Comp Ltd"
    assert isinstance(retrieved_events_company[1], domain_event_models.BeneficialOwnerAddedEvent)
    assert retrieved_events_company[1].payload.person_details.firstname == "BO"
    assert isinstance(retrieved_events_company[2], domain_event_models.PersonLinkedToCompanyEvent)
    assert retrieved_events_company[2].payload.role_in_company == "Director"
