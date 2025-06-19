# Unit Tests for Event Projectors (Refactored Structure)
import asyncio # Keep for clarity, though pytest-asyncio handles it
import pytest
from unittest.mock import patch, AsyncMock, MagicMock, call
import datetime
import uuid

# Modules to test and their new locations
from case_management_service.app.service.events import models as domain_events
from case_management_service.app.service.events import projectors as event_projectors
from case_management_service.infrastructure.database import schemas as db_schemas
# Import the specific store for document requirements to mock its functions
# from case_management_service.infrastructure.database import document_requirements_store # Not directly used in mocks here
# AddressData is available via domain_events (imported from kafka.schemas there)
from opentelemetry.trace.status import StatusCode, Status # For checking span status
import logging # Added for logger mocking


# --- Tests for New Projectors (KYB/Company/BO related - from previous step) ---
@pytest.mark.asyncio
@patch('case_management_service.infrastructure.database.read_models.upsert_company_read_model', new_callable=AsyncMock)
async def test_project_company_profile_created(mock_upsert_company_rm):
    company_id = str(uuid.uuid4())
    event_timestamp = datetime.datetime.now(datetime.UTC)
    addr_data = domain_events.AddressData(street="Main St 123", city="ACity", country="US", postal_code="12345")
    payload = domain_events.CompanyProfileCreatedEventPayload(
        registered_name="Test Ltd",
        registration_number="REG123",
        country_of_incorporation="US",
        registered_address=addr_data
    )
    event = domain_events.CompanyProfileCreatedEvent(
        aggregate_id=company_id, payload=payload, timestamp=event_timestamp, version=1, event_type="CompanyProfileCreated"
    )
    await event_projectors.project_company_profile_created(event)
    mock_upsert_company_rm.assert_called_once()
    called_arg = mock_upsert_company_rm.call_args.args[0]
    assert isinstance(called_arg, db_schemas.CompanyProfileDB)
    assert called_arg.id == company_id
    assert called_arg.registered_name == "Test Ltd"
    assert called_arg.registered_address.street == "Main St 123"
    assert called_arg.created_at == event_timestamp
    assert called_arg.updated_at == event_timestamp

@pytest.mark.asyncio
@patch('case_management_service.infrastructure.database.read_models.upsert_beneficial_owner_read_model', new_callable=AsyncMock)
async def test_project_beneficial_owner_added(mock_upsert_bo_rm):
    company_id = str(uuid.uuid4())
    bo_id = str(uuid.uuid4())
    event_timestamp = datetime.datetime.now(datetime.UTC)
    bo_person_details = domain_events.PersonData(firstname="BO", lastname="One", birthdate="1980-01-01")
    payload = domain_events.BeneficialOwnerAddedEventPayload(
        beneficial_owner_id=bo_id,
        person_details=bo_person_details,
        ownership_percentage=75.0,
        is_ubo=True,
        types_of_control=["Voting Rights"]
    )
    event = domain_events.BeneficialOwnerAddedEvent(
        aggregate_id=company_id, payload=payload, timestamp=event_timestamp, version=2, event_type="BeneficialOwnerAdded"
    )
    await event_projectors.project_beneficial_owner_added(event)
    mock_upsert_bo_rm.assert_called_once()
    called_arg = mock_upsert_bo_rm.call_args.args[0]
    assert isinstance(called_arg, db_schemas.BeneficialOwnerDB)
    assert called_arg.id == bo_id
    assert called_arg.company_id == company_id
    assert called_arg.firstname == "BO"
    assert called_arg.is_ubo is True
    assert called_arg.ownership_percentage == 75.0
    assert called_arg.types_of_control == ["Voting Rights"]
    assert called_arg.created_at == event_timestamp

@pytest.mark.asyncio
@patch('case_management_service.infrastructure.database.read_models.upsert_person_read_model', new_callable=AsyncMock)
async def test_project_person_linked_to_company(mock_upsert_person_rm):
    company_id = str(uuid.uuid4())
    person_id_linked = str(uuid.uuid4())
    event_timestamp = datetime.datetime.now(datetime.UTC)
    payload = domain_events.PersonLinkedToCompanyEventPayload(
        person_id=person_id_linked,
        firstname="Director",
        lastname="Smith",
        birthdate="1975-05-15",
        role_in_company="Director"
    )
    event = domain_events.PersonLinkedToCompanyEvent(
        aggregate_id=company_id, payload=payload, timestamp=event_timestamp, version=3, event_type="PersonLinkedToCompany"
    )
    await event_projectors.project_person_linked_to_company(event)
    mock_upsert_person_rm.assert_called_once()
    called_arg = mock_upsert_person_rm.call_args.args[0]
    assert isinstance(called_arg, db_schemas.PersonDB)
    assert called_arg.id == person_id_linked
    assert called_arg.company_id == company_id
    assert called_arg.firstname == "Director"
    assert called_arg.role_in_company == "Director"
    assert called_arg.created_at == event_timestamp

# --- Modified existing tests ---
@pytest.mark.asyncio
@patch('case_management_service.infrastructure.database.read_models.upsert_case_read_model', new_callable=AsyncMock)
async def test_project_case_created_with_kyb_link(mock_upsert_case_rm):
    case_id = str(uuid.uuid4())
    company_id_linked = str(uuid.uuid4())
    event_timestamp = datetime.datetime.now(datetime.UTC)
    payload = domain_events.CaseCreatedEventPayload(
        client_id="client_xyz", case_type="KYB_CASE", case_version="1.0",
        traitement_type="KYB", company_id=company_id_linked
    )
    event = domain_events.CaseCreatedEvent(
        aggregate_id=case_id, payload=payload, timestamp=event_timestamp, version=1, event_type="CaseCreated"
    )
    await event_projectors.project_case_created(event)
    mock_upsert_case_rm.assert_called_once()
    called_arg = mock_upsert_case_rm.call_args.args[0]
    assert isinstance(called_arg, db_schemas.CaseManagementDB)
    assert called_arg.id == case_id
    assert called_arg.traitement_type == "KYB"
    assert called_arg.company_id == company_id_linked
    assert called_arg.status == "OPEN"

@pytest.mark.asyncio
@patch('case_management_service.infrastructure.database.read_models.upsert_person_read_model', new_callable=AsyncMock)
async def test_project_person_added_to_case_kyc(mock_upsert_person_rm):
    case_id = str(uuid.uuid4())
    person_id = str(uuid.uuid4())
    event_timestamp = datetime.datetime.now(datetime.UTC)
    event_payload = domain_events.PersonAddedToCaseEventPayload(
        person_id=person_id, firstname="Test", lastname="Person", birthdate="2000-01-01"
    )
    event = domain_events.PersonAddedToCaseEvent(
        aggregate_id=case_id, payload=event_payload, version=2, timestamp=event_timestamp, event_type="PersonAddedToCase"
    )
    await event_projectors.project_person_added_to_case(event)
    mock_upsert_person_rm.assert_called_once()
    called_arg = mock_upsert_person_rm.call_args.args[0]
    assert isinstance(called_arg, db_schemas.PersonDB)
    assert called_arg.id == person_id
    assert called_arg.case_id == case_id
    assert called_arg.company_id is None
    assert called_arg.role_in_company is None

# --- Tests for Document Requirement Projectors ---
@pytest.mark.asyncio
@patch('case_management_service.infrastructure.database.document_requirements_store.add_required_document', new_callable=AsyncMock)
async def test_project_document_requirement_determined(mock_add_required_doc):
    case_id = str(uuid.uuid4())
    person_id = str(uuid.uuid4())
    event_timestamp = datetime.datetime.now(datetime.UTC)

    payload = domain_events.DocumentRequirementDeterminedEventPayload(
        case_id=case_id,
        entity_id=person_id,
        entity_type="PERSON",
        document_type="NATIONAL_ID",
        is_required=True
    )
    event = domain_events.DocumentRequirementDeterminedEvent(
        aggregate_id=case_id,
        payload=payload,
        timestamp=event_timestamp,
        event_type="DocumentRequirementDetermined"
    )
    await event_projectors.project_document_requirement_determined(event)
    mock_add_required_doc.assert_called_once()
    called_arg = mock_add_required_doc.call_args.args[0]
    assert isinstance(called_arg, db_schemas.RequiredDocumentDB)
    assert called_arg.case_id == case_id
    assert called_arg.entity_id == person_id
    assert called_arg.document_type == "NATIONAL_ID"
    assert called_arg.is_required is True
    assert called_arg.status == "AWAITING_UPLOAD"
    assert called_arg.created_at == event_timestamp

@pytest.mark.asyncio
@patch('case_management_service.infrastructure.database.document_requirements_store.update_required_document_status_and_meta', new_callable=AsyncMock)
async def test_project_document_status_updated(mock_update_doc_status_meta):
    doc_req_id = str(uuid.uuid4())
    event_timestamp = datetime.datetime.now(datetime.UTC) # Not used by projector, but part of event

    payload = domain_events.DocumentStatusUpdatedEventPayload(
        document_requirement_id=doc_req_id,
        new_status="UPLOADED",
        old_status="AWAITING_UPLOAD",
        updated_by="user_x",
        metadata_update={"file_ref": "xyz.pdf"},
        notes_added=["User uploaded file."]
    )
    event = domain_events.DocumentStatusUpdatedEvent(
        aggregate_id=doc_req_id,
        payload=payload,
        timestamp=event_timestamp,
        event_type="DocumentStatusUpdated"
    )

    mock_update_doc_status_meta.return_value = db_schemas.RequiredDocumentDB(
        id=doc_req_id, case_id="c1", entity_id="e1", entity_type="P", # Dummy values for other fields
        document_type="D1", status="UPLOADED", metadata={"file_ref": "xyz.pdf"}, notes=["User uploaded file."]
    )

    await event_projectors.project_document_status_updated(event)

    mock_update_doc_status_meta.assert_called_once_with(
        doc_requirement_id=doc_req_id,
        new_status="UPLOADED",
        metadata_update={"file_ref": "xyz.pdf"},
        notes_to_add=["User uploaded file."]
    )

@pytest.mark.asyncio
@patch('case_management_service.app.service.events.projectors.document_requirements_store.update_required_document_status_and_meta', new_callable=AsyncMock)
@patch('case_management_service.app.service.events.projectors.logger') # Mock the logger in the projectors module
async def test_project_document_status_updated_not_found(mock_logger, mock_update_doc_status_meta):
    doc_req_id = str(uuid.uuid4())
    event_timestamp = datetime.datetime.now(datetime.UTC)

    payload = domain_events.DocumentStatusUpdatedEventPayload(
        document_requirement_id=doc_req_id,
        new_status="UPLOADED",
        old_status="AWAITING_UPLOAD",
        updated_by="user_y",
        metadata_update=None,
        notes_added=None
    )
    event = domain_events.DocumentStatusUpdatedEvent(
        aggregate_id=doc_req_id,
        payload=payload,
        timestamp=event_timestamp,
        event_type="DocumentStatusUpdated"
    )

    # Simulate that the store function returns None (document not found/updated)
    mock_update_doc_status_meta.return_value = None

    # Act: Call the projector
    await event_projectors.project_document_status_updated(event)

    # Assert: Check that the store function was called
    mock_update_doc_status_meta.assert_called_once_with(
        doc_requirement_id=doc_req_id,
        new_status="UPLOADED",
        metadata_update=None,
        notes_to_add=None
    )
    # Assert: Check that a warning was logged
    mock_logger.warning.assert_called_once_with(
        f"Document requirement with ID {doc_req_id} not found or not updated during DocumentStatusUpdatedEvent projection."
    )


# --- Updated test_dispatch_event_to_projectors_all_event_types ---
@pytest.mark.asyncio
@patch('case_management_service.app.service.events.projectors.project_event_with_tracing_and_metrics', new_callable=AsyncMock)
async def test_dispatch_event_to_projectors_all_event_types(mock_project_wrapper):
    case_id = str(uuid.uuid4())
    company_id = str(uuid.uuid4())
    doc_req_id = str(uuid.uuid4())
    addr_data = domain_events.AddressData(street="s", city="c", country="US", postal_code="pc")

    events_to_test = [
        domain_events.CaseCreatedEvent(aggregate_id=case_id, payload=domain_events.CaseCreatedEventPayload(client_id="c1", case_type="t1", case_version="v1", traitement_type="KYC"), event_type="CaseCreated"),
        domain_events.CompanyProfileCreatedEvent(aggregate_id=company_id, payload=domain_events.CompanyProfileCreatedEventPayload(registered_name="Comp", registration_number="R1", country_of_incorporation="US", registered_address=addr_data), event_type="CompanyProfileCreated"),
        domain_events.BeneficialOwnerAddedEvent(aggregate_id=company_id, payload=domain_events.BeneficialOwnerAddedEventPayload(beneficial_owner_id=str(uuid.uuid4()), person_details=domain_events.PersonData(firstname="bo", lastname="p")), event_type="BeneficialOwnerAdded"),
        domain_events.PersonLinkedToCompanyEvent(aggregate_id=company_id, payload=domain_events.PersonLinkedToCompanyEventPayload(person_id=str(uuid.uuid4()), firstname="pf", lastname="pl", birthdate="1990-01-01", role_in_company="Dir"), event_type="PersonLinkedToCompany"),
        domain_events.PersonAddedToCaseEvent(aggregate_id=case_id, payload=domain_events.PersonAddedToCaseEventPayload(person_id=str(uuid.uuid4()), firstname="pac_f", lastname="pac_l", birthdate="1990-01-01"), event_type="PersonAddedToCase"),
        domain_events.DocumentRequirementDeterminedEvent(aggregate_id=case_id, payload=domain_events.DocumentRequirementDeterminedEventPayload(case_id=case_id, entity_id="e1", entity_type="PERSON", document_type="PASSPORT", is_required=True), event_type="DocumentRequirementDetermined"),
        domain_events.DocumentStatusUpdatedEvent(aggregate_id=doc_req_id, payload=domain_events.DocumentStatusUpdatedEventPayload(document_requirement_id=doc_req_id, new_status="VERIFIED", old_status="UPLOADED"), event_type="DocumentStatusUpdated")
    ]

    for event_item in events_to_test: # Renamed event to event_item to avoid conflict with event module
        await event_projectors.dispatch_event_to_projectors(event_item)

    expected_projector_map = {
        "CaseCreated": event_projectors.project_case_created,
        "CompanyProfileCreated": event_projectors.project_company_profile_created,
        "BeneficialOwnerAdded": event_projectors.project_beneficial_owner_added,
        "PersonLinkedToCompany": event_projectors.project_person_linked_to_company,
        "PersonAddedToCase": event_projectors.project_person_added_to_case,
        "DocumentRequirementDetermined": event_projectors.project_document_requirement_determined,
        "DocumentStatusUpdated": event_projectors.project_document_status_updated,
    }
    expected_calls = [call(expected_projector_map[evt.event_type], evt) for evt in events_to_test]

    mock_project_wrapper.assert_has_calls(expected_calls, any_order=False)
    assert mock_project_wrapper.call_count == len(events_to_test)

@pytest.mark.asyncio
@patch('case_management_service.app.service.events.projectors.domain_events_processed_counter')
@patch('case_management_service.app.service.events.projectors.domain_events_by_type_counter')
@patch('case_management_service.app.service.events.projectors.tracer')
async def test_project_event_with_tracing_and_metrics_wrapper_success(
    mock_tracer, mock_by_type_counter, mock_processed_counter
):
    mock_projector_func = AsyncMock()
    mock_projector_func.__name__ = "mock_actual_projector"
    event_payload = domain_events.CaseCreatedEventPayload(client_id="c1", case_type="t1", case_version="v1", traitement_type="KYC")
    event_to_project = domain_events.CaseCreatedEvent(aggregate_id=str(uuid.uuid4()), payload=event_payload, event_type="CaseCreated")
    mock_span = MagicMock()
    mock_tracer.start_as_current_span.return_value.__enter__.return_value = mock_span

    await event_projectors.project_event_with_tracing_and_metrics(mock_projector_func, event_to_project)

    mock_projector_func.assert_called_once_with(event_to_project)
    mock_span.set_status.assert_called_once()
    called_status_ok = mock_span.set_status.call_args[0][0]
    assert called_status_ok.status_code == StatusCode.OK
    mock_processed_counter.add.assert_called_once_with(1, {"projector.name": "mock_actual_projector"})
    mock_by_type_counter.add.assert_called_once_with(1, {"event.type": "CaseCreated", "projector.name": "mock_actual_projector"})

@pytest.mark.asyncio
@patch('case_management_service.app.service.events.projectors.tracer')
async def test_project_event_with_tracing_and_metrics_wrapper_failure(mock_tracer):
    mock_projector_func = AsyncMock(side_effect=ValueError("Projection failed"))
    mock_projector_func.__name__ = "mock_failing_projector"
    event_payload = domain_events.CaseCreatedEventPayload(client_id="c1", case_type="t1", case_version="v1", traitement_type="KYC")
    event_to_project = domain_events.CaseCreatedEvent(aggregate_id=str(uuid.uuid4()), payload=event_payload, event_type="CaseCreated")
    mock_span = MagicMock()
    mock_tracer.start_as_current_span.return_value.__enter__.return_value = mock_span

    with pytest.raises(ValueError, match="Projection failed"):
        await event_projectors.project_event_with_tracing_and_metrics(mock_projector_func, event_to_project)

    mock_projector_func.assert_called_once_with(event_to_project)
    mock_span.record_exception.assert_called_once()
    mock_span.set_status.assert_called_once()
    called_status_err = mock_span.set_status.call_args[0][0]
    assert called_status_err.status_code == StatusCode.ERROR
    assert called_status_err.description == "Projector Error: ValueError"
