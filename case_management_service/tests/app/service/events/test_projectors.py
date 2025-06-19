import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch, ANY as matchers
import logging # For testing logging calls

from app.service.events.projectors import (
    project_case_created,
    project_company_profile_created,
    project_beneficial_owner_added,
    project_person_linked_to_company,
    project_person_added_to_case,
    project_document_requirement_determined,
    project_document_status_updated,
    project_notification_required, # Assuming this might also have a projection, if not remove
    dispatch_event_to_projectors,
    project_event_with_tracing_and_metrics,
    EVENT_PROJECTORS, # To potentially mock or inspect
)
from app.service.events.events import (
    CaseCreatedEvent,
    CompanyProfileCreatedEvent,
    BeneficialOwnerAddedEvent,
    PersonLinkedToCompanyEvent,
    PersonAddedToCaseEvent,
    DocumentRequirementDeterminedEvent,
    DocumentStatusUpdatedEvent,
    NotificationRequiredEvent, # If it has a projector
    BaseEvent, # For generic event testing
)
from app.db import db_schemas # For verifying data transformation
from app.service.models import CaseType, Role, DocumentStatus, PersonProfile, CompanyProfile
from app.service.read_model import read_model_ops
from app.service.document_requirements import document_requirements_store

# Mock database for tests
@pytest.fixture
def mock_db():
    return AsyncMock()

# Mock tracer and counters for project_event_with_tracing_and_metrics
@pytest.fixture
def mock_tracer():
    with patch("app.service.events.projectors.trace.get_tracer") as mock_get_tracer:
        tracer = MagicMock()
        tracer.start_as_current_span = MagicMock()
        mock_get_tracer.return_value = tracer
        yield tracer

@pytest.fixture
def mock_span():
    span = MagicMock()
    span.set_attribute = MagicMock()
    span.set_status = MagicMock()
    span.record_exception = MagicMock()
    return span

@pytest.fixture
def mock_metrics_counters():
    with patch("app.service.events.projectors.domain_events_processed_counter") as mock_processed_counter, \
         patch("app.service.events.projectors.domain_events_by_type_counter") as mock_type_counter:
        yield {
            "processed": mock_processed_counter,
            "by_type": mock_type_counter,
        }

@pytest.mark.asyncio
async def test_placeholder():
    # This is a placeholder test to ensure the file is created and pytest runs.
    assert True

# --- Individual Projector Tests ---

@pytest.mark.asyncio
@patch("app.service.events.projectors.read_model_ops.upsert_case_read_model", new_callable=AsyncMock)
async def test_project_case_created(mock_upsert_op: AsyncMock, mock_db: AsyncMock):
    event_id = uuid.uuid4()
    aggregate_id = uuid.uuid4() # This is the case_id
    created_at = "2023-01-01T12:00:00Z"
    user_id = "test_user"
    company_id_val = uuid.uuid4()

    event = CaseCreatedEvent(
        id=event_id,
        aggregate_id=aggregate_id,
        version=1,
        created_at=created_at,
        payload={
            "case_type": CaseType.KYB.value,
            "created_by": user_id,
            "company_id": company_id_val, # For KYB
            # other optional fields can be None or not present if projector handles defaults
        }
    )

    await project_case_created(mock_db, event)

    mock_upsert_op.assert_called_once()
    call_args = mock_upsert_op.call_args[0]
    assert call_args[0] == mock_db

    # Verify the CaseManagementDB object
    case_db_obj: db_schemas.CaseManagementDB = call_args[1]
    assert isinstance(case_db_obj, db_schemas.CaseManagementDB)
    assert case_db_obj.case_id == str(aggregate_id)
    assert case_db_obj.version == event.version
    assert case_db_obj.case_type == CaseType.KYB.value
    assert case_db_obj.created_by == user_id
    assert case_db_obj.company_id == str(company_id_val)
    assert case_db_obj.created_at is not None # Projector should set this
    assert case_db_obj.updated_at is not None # Projector should set this
    assert case_db_obj.status == "PENDING" # Default status on creation


@pytest.mark.asyncio
@patch("app.service.events.projectors.read_model_ops.upsert_company_profile_read_model", new_callable=AsyncMock)
async def test_project_company_profile_created(mock_upsert_op: AsyncMock, mock_db: AsyncMock):
    event_id = uuid.uuid4()
    aggregate_id = uuid.uuid4() # This is the company_id
    created_at = "2023-01-02T10:00:00Z"
    user_id = "company_creator"
    profile_data = CompanyProfile(name="Test Company Inc.", registration_number="REG123")

    event = CompanyProfileCreatedEvent(
        id=event_id,
        aggregate_id=aggregate_id,
        version=1,
        created_at=created_at,
        payload={
            "profile": profile_data.model_dump(),
            "created_by": user_id,
        }
    )

    await project_company_profile_created(mock_db, event)

    mock_upsert_op.assert_called_once()
    call_args = mock_upsert_op.call_args[0]
    assert call_args[0] == mock_db

    company_db_obj: db_schemas.CompanyProfileDB = call_args[1]
    assert isinstance(company_db_obj, db_schemas.CompanyProfileDB)
    assert company_db_obj.company_id == str(aggregate_id)
    assert company_db_obj.version == event.version
    assert company_db_obj.name == profile_data.name
    assert company_db_obj.registration_number == profile_data.registration_number
    assert company_db_obj.created_by == user_id
    # Timestamps are set by the projector
    assert company_db_obj.created_at is not None
    assert company_db_obj.updated_at is not None


@pytest.mark.asyncio
@patch("app.service.events.projectors.read_model_ops.add_beneficial_owner_to_company_read_model", new_callable=AsyncMock)
async def test_project_beneficial_owner_added(mock_add_bo_op: AsyncMock, mock_db: AsyncMock):
    event_id = uuid.uuid4()
    company_id = uuid.uuid4() # aggregate_id for this event is company_id
    created_at = "2023-01-03T11:00:00Z"
    bo_id_val = uuid.uuid4()
    profile_data = PersonProfile(name="BO One", email="bo.one@example.com")
    ownership_percentage = 50.5

    event = BeneficialOwnerAddedEvent(
        id=event_id,
        aggregate_id=company_id, # CompanyID is the aggregate
        version=2, # Assuming company profile was version 1
        created_at=created_at,
        payload={
            "bo_id": bo_id_val,
            "profile": profile_data.model_dump(),
            "ownership_percentage": ownership_percentage,
            "added_by": "user_who_added_bo"
        }
    )

    await project_beneficial_owner_added(mock_db, event)

    mock_add_bo_op.assert_called_once()
    call_args = mock_add_bo_op.call_args[0]
    assert call_args[0] == mock_db
    assert call_args[1] == str(company_id) # company_id argument

    bo_db_obj: db_schemas.BeneficialOwnerDB = call_args[2] # The BO data
    assert isinstance(bo_db_obj, db_schemas.BeneficialOwnerDB)
    assert bo_db_obj.bo_id == str(bo_id_val)
    assert bo_db_obj.company_id == str(company_id)
    assert bo_db_obj.name == profile_data.name
    assert bo_db_obj.email == profile_data.email
    assert bo_db_obj.ownership_percentage == ownership_percentage
    assert bo_db_obj.version == event.version # Projector should pass this through
    # Timestamps are set by the projector/db op
    assert bo_db_obj.created_at is not None
    assert bo_db_obj.updated_at is not None


@pytest.mark.asyncio
@patch("app.service.events.projectors.read_model_ops.link_person_to_company_read_model", new_callable=AsyncMock)
async def test_project_person_linked_to_company(mock_link_person_op: AsyncMock, mock_db: AsyncMock):
    event_id = uuid.uuid4()
    company_id = uuid.uuid4() # aggregate_id
    created_at = "2023-01-04T12:00:00Z"
    person_id_val = uuid.uuid4()
    profile_data = PersonProfile(name="Linked Person", email="linked.person@example.com")
    role_val = Role.DIRECTOR

    event = PersonLinkedToCompanyEvent(
        id=event_id,
        aggregate_id=company_id,
        version=3,
        created_at=created_at,
        payload={
            "person_id": person_id_val,
            "profile": profile_data.model_dump(),
            "role": role_val.value,
            "linked_by": "user_linking_person"
        }
    )

    await project_person_linked_to_company(mock_db, event)

    mock_link_person_op.assert_called_once()
    call_args = mock_link_person_op.call_args[0]
    assert call_args[0] == mock_db
    assert call_args[1] == str(company_id)

    person_link_obj: db_schemas.PersonCompanyLinkDB = call_args[2]
    assert isinstance(person_link_obj, db_schemas.PersonCompanyLinkDB)
    assert person_link_obj.person_id == str(person_id_val)
    assert person_link_obj.company_id == str(company_id)
    assert person_link_obj.name == profile_data.name
    assert person_link_obj.email == profile_data.email
    assert person_link_obj.role == role_val.value
    assert person_link_obj.version == event.version
    assert person_link_obj.created_at is not None
    assert person_link_obj.updated_at is not None


@pytest.mark.asyncio
@patch("app.service.events.projectors.read_model_ops.add_person_to_case_read_model", new_callable=AsyncMock)
async def test_project_person_added_to_case(mock_add_person_op: AsyncMock, mock_db: AsyncMock):
    event_id = uuid.uuid4()
    case_id = uuid.uuid4() # aggregate_id
    created_at = "2023-01-05T13:00:00Z"
    person_id_val = uuid.uuid4()
    profile_data = PersonProfile(name="Case Person", email="case.person@example.com")
    role_val = Role.PRIMARY_CONTACT

    event = PersonAddedToCaseEvent(
        id=event_id,
        aggregate_id=case_id,
        version=2, # Assuming case created was v1
        created_at=created_at,
        payload={
            "person_id": person_id_val,
            "profile": profile_data.model_dump(),
            "role": role_val.value,
            "added_by": "user_adding_to_case"
        }
    )

    await project_person_added_to_case(mock_db, event)

    mock_add_person_op.assert_called_once()
    call_args = mock_add_person_op.call_args[0]
    assert call_args[0] == mock_db
    assert call_args[1] == str(case_id)

    person_case_obj: db_schemas.PersonCaseLinkDB = call_args[2]
    assert isinstance(person_case_obj, db_schemas.PersonCaseLinkDB)
    assert person_case_obj.person_id == str(person_id_val)
    assert person_case_obj.case_id == str(case_id)
    assert person_case_obj.name == profile_data.name
    assert person_case_obj.email == profile_data.email
    assert person_case_obj.role == role_val.value
    assert person_case_obj.version == event.version
    assert person_case_obj.created_at is not None
    assert person_case_obj.updated_at is not None


@pytest.mark.asyncio
@patch("app.service.events.projectors.document_requirements_store.add_required_document", new_callable=AsyncMock)
async def test_project_document_requirement_determined(mock_add_doc_req_op: AsyncMock, mock_db: AsyncMock):
    event_id = uuid.uuid4()
    case_id = uuid.uuid4() # aggregate_id
    created_at = "2023-01-06T14:00:00Z"
    document_id_val = uuid.uuid4()
    user_id = "doc_determiner"

    event = DocumentRequirementDeterminedEvent(
        id=event_id,
        aggregate_id=case_id,
        version=1, # First document event for this case
        created_at=created_at,
        payload={
            "document_id": document_id_val,
            "document_type": "PASSPORT",
            "description": "Valid Passport Copy",
            "country_code": "US",
            "status": DocumentStatus.PENDING_UPLOAD.value,
            "required_by_case_type": True,
            "determined_by": user_id,
        }
    )

    await project_document_requirement_determined(mock_db, event)

    mock_add_doc_req_op.assert_called_once()
    call_args = mock_add_doc_req_op.call_args[0]
    assert call_args[0] == mock_db

    doc_req_db_obj: db_schemas.RequiredDocumentDB = call_args[1]
    assert isinstance(doc_req_db_obj, db_schemas.RequiredDocumentDB)
    assert doc_req_db_obj.document_id == str(document_id_val)
    assert doc_req_db_obj.case_id == str(case_id)
    assert doc_req_db_obj.document_type == "PASSPORT"
    assert doc_req_db_obj.description == "Valid Passport Copy"
    assert doc_req_db_obj.country_code == "US"
    assert doc_req_db_obj.status == DocumentStatus.PENDING_UPLOAD.value
    assert doc_req_db_obj.required_by_case_type is True
    assert doc_req_db_obj.version == event.version
    assert doc_req_db_obj.created_by == user_id # determined_by maps to created_by
    assert doc_req_db_obj.created_at is not None
    assert doc_req_db_obj.updated_at is not None


@pytest.mark.asyncio
@patch("app.service.events.projectors.document_requirements_store.update_required_document_status_and_meta", new_callable=AsyncMock)
@patch("app.service.events.projectors.logger") # To check logging on failure
async def test_project_document_status_updated_success(mock_logger: MagicMock, mock_update_doc_op: AsyncMock, mock_db: AsyncMock):
    event_id = uuid.uuid4()
    case_id = uuid.uuid4() # aggregate_id
    created_at = "2023-01-07T15:00:00Z"
    document_id_val = uuid.uuid4()
    user_id = "doc_updater"
    old_status = DocumentStatus.PENDING_UPLOAD.value
    new_status = DocumentStatus.APPROVED.value

    event = DocumentStatusUpdatedEvent(
        id=event_id,
        aggregate_id=case_id,
        version=2,
        created_at=created_at,
        payload={
            "document_id": document_id_val,
            "old_status": old_status,
            "new_status": new_status,
            "updated_by": user_id,
            "rejection_reason": None,
            "s3_path": "/path/to/doc.pdf", # Example meta field
            "file_name": "doc.pdf"
        }
    )

    # Simulate successful update by store returning the updated document mock
    updated_doc_mock = MagicMock(spec=db_schemas.RequiredDocumentDB)
    mock_update_doc_op.return_value = updated_doc_mock

    await project_document_status_updated(mock_db, event)

    mock_update_doc_op.assert_called_once_with(
        db=mock_db,
        document_id=str(document_id_val),
        new_status=new_status,
        updated_by=user_id,
        version=event.version,
        rejection_reason=None,
        s3_path="/path/to/doc.pdf",
        file_name="doc.pdf"
    )
    mock_logger.warning.assert_not_called()


@pytest.mark.asyncio
@patch("app.service.events.projectors.document_requirements_store.update_required_document_status_and_meta", new_callable=AsyncMock)
@patch("app.service.events.projectors.logger")
async def test_project_document_status_updated_not_found(mock_logger: MagicMock, mock_update_doc_op: AsyncMock, mock_db: AsyncMock):
    event_id = uuid.uuid4()
    case_id = uuid.uuid4()
    document_id_val = uuid.uuid4()

    event = DocumentStatusUpdatedEvent(
        id=event_id,
        aggregate_id=case_id,
        version=2,
        created_at="2023-01-08T10:00:00Z",
        payload={
            "document_id": document_id_val,
            "old_status": DocumentStatus.PENDING_UPLOAD.value,
            "new_status": DocumentStatus.APPROVED.value,
            "updated_by": "test_user",
        }
    )

    # Simulate document not found by store operation returning None
    mock_update_doc_op.return_value = None

    await project_document_status_updated(mock_db, event)

    mock_update_doc_op.assert_called_once() # Still called
    mock_logger.warning.assert_called_once_with(
        f"Document with ID {str(document_id_val)} not found in read model during status update projection for event {event.id}."
    )

@pytest.mark.asyncio
@patch("app.service.events.projectors.read_model_ops.create_notification_read_model", new_callable=AsyncMock)
async def test_project_notification_required(mock_create_notification_op: AsyncMock, mock_db: AsyncMock):
    event_id = uuid.uuid4()
    case_id = uuid.uuid4() # aggregate_id for this event is case_id
    created_at = "2023-01-09T10:00:00Z"

    event_payload = {
        "case_id": case_id,
        "notification_type": "CASE_CREATED",
        "recipient_user_id": "user123",
        "message": "Your case has been created.",
        "details": {"reason": "initial creation"}
    }
    event = NotificationRequiredEvent(
        id=event_id,
        aggregate_id=case_id,
        version=1,
        created_at=created_at,
        payload=event_payload
    )

    await project_notification_required(mock_db, event)

    mock_create_notification_op.assert_called_once()
    call_args = mock_create_notification_op.call_args[0]
    assert call_args[0] == mock_db

    notification_db_obj: db_schemas.NotificationDB = call_args[1]
    assert isinstance(notification_db_obj, db_schemas.NotificationDB)
    assert notification_db_obj.notification_id is not None # Should be generated by projector
    assert notification_db_obj.event_id == str(event_id)
    assert notification_db_obj.case_id == str(case_id)
    assert notification_db_obj.notification_type == "CASE_CREATED"
    assert notification_db_obj.recipient_user_id == "user123"
    assert notification_db_obj.message == "Your case has been created."
    assert notification_db_obj.status == "PENDING" # Default status
    assert notification_db_obj.created_at is not None
    assert notification_db_obj.updated_at is not None
    assert notification_db_obj.details == {"reason": "initial creation"}


# --- Dispatcher Tests ---

@pytest.mark.asyncio
@patch("app.service.events.projectors.project_event_with_tracing_and_metrics", new_callable=AsyncMock)
async def test_dispatch_event_to_projectors_event_with_projectors(
    mock_project_wrapper: AsyncMock, mock_db: AsyncMock
):
    """
    Test dispatch_event_to_projectors for an event type that has registered projectors.
    """
    # Use a real event type that is expected to be in EVENT_PROJECTORS
    # For this example, let's assume CaseCreatedEvent maps to project_case_created
    event = CaseCreatedEvent(
        id=uuid.uuid4(),
        aggregate_id=uuid.uuid4(),
        version=1,
        created_at="2023-01-01T00:00:00Z",
        payload={"case_type": "KYC", "created_by": "user"}
    )

    # Mock EVENT_PROJECTORS to control the projectors for this test
    # This ensures the test is not dependent on the actual global EVENT_PROJECTORS map
    mock_case_created_projector_func = AsyncMock(name="mock_project_case_created_for_dispatch")

    test_event_projectors_map = {
        CaseCreatedEvent: [mock_case_created_projector_func]
    }

    with patch.dict(EVENT_PROJECTORS, test_event_projectors_map, clear=True):
        await dispatch_event_to_projectors(mock_db, event)

        # Assert that our mock wrapper was called with the correct projector and event
        mock_project_wrapper.assert_called_once_with(
            mock_db, event, mock_case_created_projector_func
        )

@pytest.mark.asyncio
@patch("app.service.events.projectors.project_event_with_tracing_and_metrics", new_callable=AsyncMock)
@patch("app.service.events.projectors.logger") # Patch logger
async def test_dispatch_event_to_projectors_event_with_no_projectors(
    mock_logger: MagicMock, mock_project_wrapper: AsyncMock, mock_db: AsyncMock
):
    """
    Test dispatch_event_to_projectors for an event type that has no registered projectors.
    """
    # Create a dummy event type that is not in EVENT_PROJECTORS
    class UnknownEvent(BaseEvent):
        pass

    event = UnknownEvent(
        id=uuid.uuid4(),
        aggregate_id=uuid.uuid4(),
        version=1,
        created_at="2023-01-01T00:00:00Z",
        payload={}
    )

    # Ensure EVENT_PROJECTORS is empty or does not contain UnknownEvent for this test
    with patch.dict(EVENT_PROJECTORS, {}, clear=True):
        await dispatch_event_to_projectors(mock_db, event)

        # Assert that no projector was called
        mock_project_wrapper.assert_not_called()
        # Assert that a debug message was logged
        mock_logger.debug.assert_called_once_with(
            f"No projectors registered for event type {type(event).__name__}"
        )


@pytest.mark.asyncio
@patch("app.service.events.projectors.project_event_with_tracing_and_metrics", new_callable=AsyncMock)
async def test_dispatch_event_to_projectors_multiple_projectors_for_event(
    mock_project_wrapper: AsyncMock, mock_db: AsyncMock
):
    """
    Test dispatch_event_to_projectors for an event type that has multiple registered projectors.
    """
    event = CaseCreatedEvent( # Using a known event type
        id=uuid.uuid4(),
        aggregate_id=uuid.uuid4(),
        version=1,
        created_at="2023-01-01T00:00:00Z",
        payload={"case_type": "KYC", "created_by": "user"}
    )

    mock_projector1 = AsyncMock(name="mock_projector1")
    mock_projector2 = AsyncMock(name="mock_projector2")

    test_event_projectors_map = {
        CaseCreatedEvent: [mock_projector1, mock_projector2]
    }

    with patch.dict(EVENT_PROJECTORS, test_event_projectors_map, clear=True):
        await dispatch_event_to_projectors(mock_db, event)

        # Assert that the wrapper was called for each projector
        assert mock_project_wrapper.call_count == 2
        mock_project_wrapper.assert_any_call(mock_db, event, mock_projector1)
        mock_project_wrapper.assert_any_call(mock_db, event, mock_projector2)


# --- Wrapper Tests ---

@pytest.mark.asyncio
async def test_project_event_with_tracing_and_metrics_success(
    mock_db: AsyncMock, mock_tracer: MagicMock, mock_span: MagicMock, mock_metrics_counters: dict
):
    """
    Test project_event_with_tracing_and_metrics for successful projector execution.
    """
    mock_actual_projector = AsyncMock(name="actual_projector_func")
    event = CaseCreatedEvent( # Example event
        id=uuid.uuid4(),
        aggregate_id=uuid.uuid4(),
        version=1,
        created_at="2023-01-01T00:00:00Z",
        payload={"case_type": "KYC", "created_by": "user"}
    )
    event_type_name = type(event).__name__
    projector_name = mock_actual_projector.__name__

    # Link mock_span to the tracer's start_as_current_span context manager
    mock_tracer.start_as_current_span.return_value.__enter__.return_value = mock_span

    await project_event_with_tracing_and_metrics(mock_db, event, mock_actual_projector)

    # Verify tracer and span interactions
    mock_tracer.start_as_current_span.assert_called_once_with(f"ProjectEvent.{event_type_name}.{projector_name}")
    mock_span.set_attribute.assert_any_call("event_id", str(event.id))
    mock_span.set_attribute.assert_any_call("aggregate_id", str(event.aggregate_id))
    mock_span.set_attribute.assert_any_call("event_type", event_type_name)
    mock_span.set_attribute.assert_any_call("projector_name", projector_name)
    mock_span.set_status.assert_called_once_with(matchers.Anything) # trace.Status Matcher if possible, otherwise check args
    # Check the status was OK - trace.Status(trace.StatusCode.OK)
    assert mock_span.set_status.call_args[0][0].status_code == pytest.importorskip("opentelemetry.trace").StatusCode.OK


    # Verify the actual projector was called
    mock_actual_projector.assert_called_once_with(mock_db, event)

    # Verify metrics counters
    mock_metrics_counters["processed"].add.assert_called_once_with(1, {"projector_name": projector_name, "event_type": event_type_name, "status": "success"})
    mock_metrics_counters["by_type"].add.assert_called_once_with(1, {"event_type": event_type_name, "projector_name": projector_name, "status": "success"})


@pytest.mark.asyncio
async def test_project_event_with_tracing_and_metrics_projector_exception(
    mock_db: AsyncMock, mock_tracer: MagicMock, mock_span: MagicMock, mock_metrics_counters: dict
):
    """
    Test project_event_with_tracing_and_metrics when the projector raises an exception.
    """
    mock_actual_projector = AsyncMock(name="failing_projector_func")
    test_exception = ValueError("Projector failed!")
    mock_actual_projector.side_effect = test_exception

    event = DocumentStatusUpdatedEvent( # Example event
        id=uuid.uuid4(),
        aggregate_id=uuid.uuid4(),
        version=1,
        created_at="2023-01-01T00:00:00Z",
        payload={"document_id": uuid.uuid4(), "new_status": "APPROVED"}
    )
    event_type_name = type(event).__name__
    projector_name = mock_actual_projector.__name__

    mock_tracer.start_as_current_span.return_value.__enter__.return_value = mock_span

    with pytest.raises(ValueError, match="Projector failed!"):
        await project_event_with_tracing_and_metrics(mock_db, event, mock_actual_projector)

    # Verify tracer and span interactions for error
    mock_tracer.start_as_current_span.assert_called_once_with(f"ProjectEvent.{event_type_name}.{projector_name}")
    mock_span.record_exception.assert_called_once_with(test_exception)
    mock_span.set_status.assert_called_once_with(matchers.Anything) # trace.Status Matcher if possible
    # Check the status was ERROR - trace.Status(trace.StatusCode.ERROR, "Projector failed!")
    status_arg = mock_span.set_status.call_args[0][0]
    assert status_arg.status_code == pytest.importorskip("opentelemetry.trace").StatusCode.ERROR
    assert status_arg.description == str(test_exception)


    # Verify the actual projector was called
    mock_actual_projector.assert_called_once_with(mock_db, event)

    # Verify metrics counters (failure status)
    mock_metrics_counters["processed"].add.assert_called_once_with(1, {"projector_name": projector_name, "event_type": event_type_name, "status": "failure"})
    mock_metrics_counters["by_type"].add.assert_called_once_with(1, {"event_type": event_type_name, "projector_name": projector_name, "status": "failure"})
