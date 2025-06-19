import pytest
from unittest.mock import AsyncMock, MagicMock
import datetime
import uuid

from case_management_service.infrastructure.database import read_models as store
from case_management_service.infrastructure.database.schemas import (
    CaseManagementDB, PersonDB, CompanyProfileDB, BeneficialOwnerDB, AddressData
)

@pytest.fixture
def mock_db():
    db = AsyncMock()
    # Mock collections used by read_models
    db.cases = AsyncMock()
    db.persons = AsyncMock()
    db.companies = AsyncMock()
    db.beneficial_owners = AsyncMock()
    return db

@pytest.fixture
def sample_case_data():
    return CaseManagementDB(
        id=str(uuid.uuid4()),
        client_id=str(uuid.uuid4()),
        case_type="KYC_STANDARD",
        status="OPEN",
        traitement_type="INDIVIDUAL",
        version=1,
        created_at=datetime.datetime.now(datetime.timezone.utc),
        updated_at=datetime.datetime.now(datetime.timezone.utc)
    )

@pytest.fixture
def sample_person_data(sample_case_data: CaseManagementDB):
    return PersonDB(
        id=str(uuid.uuid4()),
        case_id=sample_case_data.id,
        firstname="John",
        lastname="Doe",
        birthdate="1990-01-01",
        created_at=datetime.datetime.now(datetime.timezone.utc),
        updated_at=datetime.datetime.now(datetime.timezone.utc)
    )

@pytest.fixture
def sample_address_data():
    return AddressData(
        street="123 Main St", city="Anytown", country="US", postal_code="12345"
    )

@pytest.fixture
def sample_company_data(sample_address_data: AddressData):
    return CompanyProfileDB(
        id=str(uuid.uuid4()),
        registered_name="Test Corp",
        registration_number="REG123",
        country_of_incorporation="US",
        registered_address=sample_address_data,
        created_at=datetime.datetime.now(datetime.timezone.utc),
        updated_at=datetime.datetime.now(datetime.timezone.utc)
    )

@pytest.fixture
def sample_bo_data(sample_company_data: CompanyProfileDB, sample_person_data: PersonDB): # Using a generic person for details
    # For BO, person_details are embedded, not a full PersonDB schema from kafka, but a subset.
    # Re-creating a simpler PersonData for BO context as per event/domain model.
    from case_management_service.app.service.events.models import PersonData as EventPersonData
    bo_person_details = EventPersonData(firstname="Beneficial", lastname="Owner", birthdate="1980-01-01")

    return BeneficialOwnerDB(
        id=str(uuid.uuid4()),
        company_id=sample_company_data.id,
        person_details=bo_person_details.model_dump(), # BO stores dict, not full PersonDB
        firstname=bo_person_details.firstname, # Denormalized for querying
        lastname=bo_person_details.lastname,   # Denormalized for querying
        is_ubo=True,
        ownership_percentage=50.0,
        types_of_control=["VOTING_RIGHTS"],
        created_at=datetime.datetime.now(datetime.timezone.utc),
        updated_at=datetime.datetime.now(datetime.timezone.utc)
    )


@pytest.mark.asyncio
async def test_upsert_case_read_model(mock_db, sample_case_data: CaseManagementDB):
    mock_db.cases.replace_one = AsyncMock()

    result = await store.upsert_case_read_model(mock_db, sample_case_data)

    assert result == sample_case_data
    mock_db.cases.replace_one.assert_called_once()
    # First arg is filter, second is replacement doc, third is upsert=True
    call_args = mock_db.cases.replace_one.call_args
    assert call_args[0][0] == {"id": sample_case_data.id} # filter
    assert call_args[0][1]["id"] == sample_case_data.id # replacement doc content
    assert call_args[1]["upsert"] is True # upsert=True

@pytest.mark.asyncio
async def test_upsert_person_read_model(mock_db, sample_person_data: PersonDB):
    mock_db.persons.replace_one = AsyncMock()

    result = await store.upsert_person_read_model(mock_db, sample_person_data)

    assert result == sample_person_data
    mock_db.persons.replace_one.assert_called_once()
    call_args = mock_db.persons.replace_one.call_args
    assert call_args[0][0] == {"id": sample_person_data.id}
    assert call_args[0][1]["firstname"] == sample_person_data.firstname
    assert call_args[1]["upsert"] is True

@pytest.mark.asyncio
async def test_get_case_by_id_from_read_model_found(mock_db, sample_case_data: CaseManagementDB):
    mock_db.cases.find_one.return_value = sample_case_data.model_dump()

    result = await store.get_case_by_id_from_read_model(mock_db, sample_case_data.id)

    assert result is not None
    assert result.id == sample_case_data.id
    assert result.client_id == sample_case_data.client_id
    mock_db.cases.find_one.assert_called_once_with({"id": sample_case_data.id})

@pytest.mark.asyncio
async def test_get_case_by_id_from_read_model_not_found(mock_db):
    case_id = str(uuid.uuid4())
    mock_db.cases.find_one.return_value = None

    result = await store.get_case_by_id_from_read_model(mock_db, case_id)
    assert result is None
    mock_db.cases.find_one.assert_called_once_with({"id": case_id})

@pytest.mark.asyncio
async def test_list_cases_from_read_model(mock_db, sample_case_data: CaseManagementDB):
    doc_list = [sample_case_data.model_dump()]

    mock_cursor = MagicMock()
    mock_cursor.limit.return_value = mock_cursor
    mock_cursor.skip.return_value = mock_cursor
    mock_cursor.sort.return_value = mock_cursor
    mock_cursor.to_list = AsyncMock(return_value=doc_list)
    mock_db.cases.find.return_value = mock_cursor

    limit, skip = 10, 0
    results = await store.list_cases_from_read_model(mock_db, limit=limit, skip=skip)

    assert len(results) == 1
    assert results[0].id == sample_case_data.id
    mock_db.cases.find.assert_called_once_with()
    mock_cursor.limit.assert_called_once_with(limit)
    mock_cursor.skip.assert_called_once_with(skip)
    mock_cursor.sort.assert_called_once_with("created_at", -1)
    mock_cursor.to_list.assert_called_once_with(length=limit)

@pytest.mark.asyncio
async def test_list_persons_for_case_from_read_model(mock_db, sample_person_data: PersonDB):
    doc_list = [sample_person_data.model_dump()]
    case_id = sample_person_data.case_id

    mock_cursor = MagicMock()
    mock_cursor.limit.return_value = mock_cursor
    mock_cursor.skip.return_value = mock_cursor
    mock_cursor.sort.return_value = mock_cursor
    mock_cursor.to_list = AsyncMock(return_value=doc_list)
    mock_db.persons.find.return_value = mock_cursor

    limit, skip = 5, 0
    results = await store.list_persons_for_case_from_read_model(mock_db, case_id=case_id, limit=limit, skip=skip)

    assert len(results) == 1
    assert results[0].id == sample_person_data.id
    mock_db.persons.find.assert_called_once_with({"case_id": case_id})
    mock_cursor.limit.assert_called_once_with(limit)
    mock_cursor.skip.assert_called_once_with(skip)
    mock_cursor.sort.assert_called_once_with("created_at", 1)
    mock_cursor.to_list.assert_called_once_with(length=limit)

@pytest.mark.asyncio
async def test_upsert_company_read_model(mock_db, sample_company_data: CompanyProfileDB):
    mock_db.companies.replace_one = AsyncMock()

    result = await store.upsert_company_read_model(mock_db, sample_company_data)

    assert result == sample_company_data
    mock_db.companies.replace_one.assert_called_once()
    call_args = mock_db.companies.replace_one.call_args
    assert call_args[0][0] == {"id": sample_company_data.id}
    assert call_args[0][1]["registered_name"] == sample_company_data.registered_name
    assert call_args[1]["upsert"] is True

@pytest.mark.asyncio
async def test_upsert_beneficial_owner_read_model(mock_db, sample_bo_data: BeneficialOwnerDB):
    mock_db.beneficial_owners.replace_one = AsyncMock()

    result = await store.upsert_beneficial_owner_read_model(mock_db, sample_bo_data)

    assert result == sample_bo_data
    mock_db.beneficial_owners.replace_one.assert_called_once()
    call_args = mock_db.beneficial_owners.replace_one.call_args
    assert call_args[0][0] == {"id": sample_bo_data.id}
    assert call_args[0][1]["firstname"] == sample_bo_data.firstname
    assert call_args[1]["upsert"] is True
