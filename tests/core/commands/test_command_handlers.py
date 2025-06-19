import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import List, Dict, Any, Optional
import uuid

from motor.motor_asyncio import AsyncIOMotorDatabase

# Models to test
from case_management_service.app.service.commands.models import (
    CreateCaseCommand, PersonData, CompanyProfileData, BeneficialOwnerData, # Added missing models
    DetermineInitialDocumentRequirementsCommand,
    UpdateDocumentStatusCommand,
)
from case_management_service.app.service.events import models as domain_event_models
from case_management_service.app.service.commands.handlers import (
    handle_create_case_command,
    handle_determine_initial_document_requirements,
    handle_update_document_status,
)

# Infrastructure for mocking
from case_management_service.infrastructure.kafka.producer import KafkaProducerService
from case_management_service.app.service.interfaces.notification_config_client import AbstractNotificationConfigClient, NotificationRule
from case_management_service.app.models import RequiredDocumentDB

# Custom Exceptions
from case_management_service.app.service.exceptions import DocumentNotFoundError, KafkaProducerError, ConcurrencyConflictError

# Strategies
from case_management_service.app.service.strategies.document_strategies import DocumentDeterminationStrategy
from case_management_service.app.service.strategies.notification_strategies import NotificationStrategy


@pytest.fixture
def mock_db():
    return AsyncMock(spec=AsyncIOMotorDatabase)

@pytest.fixture
def mock_kafka_producer():
    return AsyncMock(spec=KafkaProducerService)

@pytest.fixture
def mock_config_client():
    return AsyncMock(spec=AbstractNotificationConfigClient)

@pytest.fixture
def mock_doc_strategy():
    return AsyncMock(spec=DocumentDeterminationStrategy)

@pytest.fixture
def mock_notification_strategy():
    return AsyncMock(spec=NotificationStrategy)

# --- Tests for handle_determine_initial_document_requirements ---
@pytest.mark.asyncio
@patch('case_management_service.app.service.commands.handlers.get_document_strategy')
@patch('case_management_service.app.service.commands.handlers.save_event', new_callable=AsyncMock)
@patch('case_management_service.app.service.commands.handlers.dispatch_event_to_projectors', new_callable=AsyncMock)
async def test_handle_determine_doc_reqs_success(
    mock_dispatch, mock_save_event, mock_get_strategy, mock_db, mock_doc_strategy
):
    mock_get_strategy.return_value = mock_doc_strategy
    mock_doc_strategy.determine_requirements.return_value = [
        {"type": "PASSPORT", "is_required": True},
        {"type": "VISA", "is_required": False},
    ]

    command = DetermineInitialDocumentRequirementsCommand(
        case_id="case1", entity_id="entity1", entity_type="PERSON", traitement_type="KYC", case_type="STANDARD"
    )

    result_event_ids = await handle_determine_initial_document_requirements(mock_db, command)

    assert len(result_event_ids) == 2
    mock_doc_strategy.determine_requirements.assert_called_once_with(command)
    assert mock_save_event.call_count == 2
    assert mock_dispatch.call_count == 2

    # Check event details for one event
    saved_event_1 = mock_save_event.call_args_list[0][0][1] # event_data is the second arg of save_event(db, event_data)
    assert isinstance(saved_event_1, domain_event_models.DocumentRequirementDeterminedEvent)
    assert saved_event_1.payload.document_type == "PASSPORT"
    assert saved_event_1.payload.is_required is True


@pytest.mark.asyncio
@patch('case_management_service.app.service.commands.handlers.get_document_strategy')
async def test_handle_determine_doc_reqs_no_reqs_from_strategy(
    mock_get_strategy, mock_db, mock_doc_strategy
):
    mock_get_strategy.return_value = mock_doc_strategy
    mock_doc_strategy.determine_requirements.return_value = [] # Strategy returns no documents

    command = DetermineInitialDocumentRequirementsCommand(
        case_id="case2", entity_id="entity2", entity_type="PERSON", traitement_type="KYC", case_type="STANDARD"
    )

    with patch('case_management_service.app.service.commands.handlers.save_event', new_callable=AsyncMock) as mock_save_event, \
         patch('case_management_service.app.service.commands.handlers.dispatch_event_to_projectors', new_callable=AsyncMock) as mock_dispatch:

        result_event_ids = await handle_determine_initial_document_requirements(mock_db, command)

        assert len(result_event_ids) == 0
        mock_doc_strategy.determine_requirements.assert_called_once_with(command)
        mock_save_event.assert_not_called()
        mock_dispatch.assert_not_called()


# --- Tests for handle_create_case_command ---
@pytest.mark.asyncio
@patch('case_management_service.app.service.commands.handlers.get_notification_strategy')
@patch('case_management_service.app.service.commands.handlers.save_event', new_callable=AsyncMock)
@patch('case_management_service.app.service.commands.handlers.dispatch_event_to_projectors', new_callable=AsyncMock)
async def test_handle_create_case_success_with_notification(
    mock_dispatch, mock_save_event, mock_get_notification_strategy,
    mock_db, mock_kafka_producer, mock_config_client, mock_notification_strategy
):
    mock_get_notification_strategy.return_value = mock_notification_strategy
    mock_notification_payload = domain_event_models.NotificationRequiredEventPayload(
        notification_type="EMAIL_WELCOME", recipient_details={}, template_id="welcome_tpl", language_code="en"
    )
    mock_notification_strategy.prepare_notification.return_value = mock_notification_payload

    command = CreateCaseCommand(client_id="client1", case_type="TypeA", traitement_type="KYC", persons=[PersonData(firstname="Test", lastname="User", birthdate="1990-01-01")])

    case_id = await handle_create_case_command(mock_db, command, mock_kafka_producer, mock_config_client)

    assert case_id is not None
    # Expect CaseCreatedEvent, PersonAddedToCaseEvent (if persons provided), and NotificationRequiredEvent
    assert mock_save_event.call_count >= 2 # At least CaseCreated, possibly PersonAdded, and Notification

    # Check if NotificationRequiredEvent was saved
    notification_event_saved = any(
        isinstance(call_args[0][1], domain_event_models.NotificationRequiredEvent) for call_args in mock_save_event.call_args_list
    )
    assert notification_event_saved

    mock_kafka_producer.produce_message.assert_called_once()
    # Check that core domain events (not notification) were dispatched
    assert mock_dispatch.call_count == (mock_save_event.call_count -1) # -1 for the notification event

@pytest.mark.asyncio
@patch('case_management_service.app.service.commands.handlers.get_notification_strategy')
@patch('case_management_service.app.service.commands.handlers.save_event', new_callable=AsyncMock)
async def test_handle_create_case_success_no_notification(
    mock_save_event, mock_get_notification_strategy,
    mock_db, mock_kafka_producer, mock_config_client, mock_notification_strategy
):
    mock_get_notification_strategy.return_value = mock_notification_strategy
    mock_notification_strategy.prepare_notification.return_value = None # No payload

    command = CreateCaseCommand(client_id="client2", case_type="TypeB", traitement_type="KYB", company_profile=CompanyProfileData(registered_name="Comp Inc", registration_number="123"))

    await handle_create_case_command(mock_db, command, mock_kafka_producer, mock_config_client)

    # Ensure NotificationRequiredEvent was NOT saved
    notification_event_saved = any(
        isinstance(call_args[0][1], domain_event_models.NotificationRequiredEvent) for call_args in mock_save_event.call_args_list
    )
    assert not notification_event_saved
    mock_kafka_producer.produce_message.assert_not_called()

@pytest.mark.asyncio
@patch('case_management_service.app.service.commands.handlers.get_notification_strategy')
@patch('case_management_service.app.service.commands.handlers.save_event', new_callable=AsyncMock) # Mock save_event to control its behavior
async def test_handle_create_case_kafka_error(
    mock_save_event, mock_get_notification_strategy, # mock_save_event is used by the handler
    mock_db, mock_kafka_producer, mock_config_client, mock_notification_strategy
):
    mock_get_notification_strategy.return_value = mock_notification_strategy
    mock_notification_payload = domain_event_models.NotificationRequiredEventPayload(
        notification_type="TEST", recipient_details={}, template_id="test", language_code="en"
    )
    mock_notification_strategy.prepare_notification.return_value = mock_notification_payload

    # Configure kafka_producer mock to raise an error
    mock_kafka_producer.produce_message.side_effect = Exception("Kafka broke")

    command = CreateCaseCommand(client_id="client3", case_type="TypeC", traitement_type="KYC", persons=[PersonData(firstname="Test", lastname="User", birthdate="1990-01-01")])

    with pytest.raises(KafkaProducerError):
        await handle_create_case_command(mock_db, command, mock_kafka_producer, mock_config_client)

    # Assert that save_event for NotificationRequiredEvent was still called before Kafka error
    notification_event_saved = any(
        isinstance(call_args[0][1], domain_event_models.NotificationRequiredEvent) for call_args in mock_save_event.call_args_list
    )
    assert notification_event_saved


# --- Tests for handle_update_document_status ---
@pytest.mark.asyncio
@patch('case_management_service.app.service.commands.handlers.get_required_document_by_id', new_callable=AsyncMock)
@patch('case_management_service.app.service.commands.handlers.save_event', new_callable=AsyncMock)
@patch('case_management_service.app.service.commands.handlers.dispatch_event_to_projectors', new_callable=AsyncMock)
async def test_handle_update_doc_status_success(
    mock_dispatch, mock_save_event, mock_get_doc, mock_db
):
    doc_id = str(uuid.uuid4())
    current_version = 2
    mock_current_doc = RequiredDocumentDB(
        id=doc_id, case_id="case1", entity_id="entity1", entity_type="PERSON",
        document_type="PASSPORT", status="AWAITING_UPLOAD", version=current_version,
        created_at=MagicMock(), updated_at=MagicMock() # Pydantic requires these if not Optional with default
    )
    mock_get_doc.return_value = mock_current_doc

    command = UpdateDocumentStatusCommand(document_requirement_id=doc_id, new_status="UPLOADED")

    result_id = await handle_update_document_status(mock_db, command)

    assert result_id == doc_id
    mock_get_doc.assert_called_once_with(mock_db, doc_id)
    mock_save_event.assert_called_once()

    saved_event = mock_save_event.call_args[0][1]
    assert isinstance(saved_event, domain_event_models.DocumentStatusUpdatedEvent)
    assert saved_event.version == current_version + 1 # Verify version increment
    assert saved_event.payload.new_status == "UPLOADED"
    assert saved_event.payload.old_status == "AWAITING_UPLOAD"

    mock_dispatch.assert_called_once_with(mock_db, saved_event)

@pytest.mark.asyncio
@patch('case_management_service.app.service.commands.handlers.get_required_document_by_id', new_callable=AsyncMock)
async def test_handle_update_doc_status_not_found(mock_get_doc, mock_db):
    doc_id = str(uuid.uuid4())
    mock_get_doc.return_value = None # Document not found

    command = UpdateDocumentStatusCommand(document_requirement_id=doc_id, new_status="UPLOADED")

    with pytest.raises(DocumentNotFoundError) as exc_info:
        await handle_update_document_status(mock_db, command)
    assert exc_info.value.document_id == doc_id


@pytest.mark.asyncio
@patch('case_management_service.app.service.commands.handlers.get_required_document_by_id', new_callable=AsyncMock)
@patch('case_management_service.app.service.commands.handlers.save_event', new_callable=AsyncMock)
async def test_handle_update_doc_status_concurrency_error(mock_save_event, mock_get_doc, mock_db):
    doc_id = str(uuid.uuid4())
    current_version = 3
    mock_current_doc = RequiredDocumentDB(
        id=doc_id, case_id="case1", entity_id="entity1", entity_type="PERSON",
        document_type="PASSPORT", status="AWAITING_UPLOAD", version=current_version,
        created_at=MagicMock(), updated_at=MagicMock()
    )
    mock_get_doc.return_value = mock_current_doc

    # Simulate ConcurrencyConflictError from save_event
    mock_save_event.side_effect = ConcurrencyConflictError(
        aggregate_id=doc_id, expected_version=current_version, actual_version=current_version + 1
    )

    command = UpdateDocumentStatusCommand(document_requirement_id=doc_id, new_status="VERIFIED_SYSTEM")

    with pytest.raises(ConcurrencyConflictError):
        await handle_update_document_status(mock_db, command)

    mock_save_event.assert_called_once() # save_event was called
    # dispatch_event_to_projectors should not be called if save_event fails
    # Add this assertion if dispatch is not in a finally block in the handler:
    # mock_dispatch.assert_not_called() # Assuming mock_dispatch is also patched for this test
