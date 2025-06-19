# Unit Tests for Command Handlers (Refactored Structure)
import asyncio # Not strictly needed for pytest-asyncio but good for clarity
import pytest
from unittest.mock import patch, AsyncMock, call, MagicMock
import uuid
import datetime
import logging # Added for logger mocking

# Modules to test and their new locations
from case_management_service.app.service.commands import models as commands
from case_management_service.app.service.commands import handlers as command_handlers
from case_management_service.app.service.events import models as domain_events
from case_management_service.infrastructure.kafka.schemas import PersonData, CompanyProfileData, BeneficialOwnerData, AddressData
from case_management_service.infrastructure.database import schemas as db_schemas
# New imports for notification logic testing
from case_management_service.infrastructure.config_service_client import NotificationRule
from case_management_service.infrastructure.kafka.producer import KafkaProducerService # For spec-ing mock
from case_management_service.app.config import settings

# Custom Exceptions from the original tests
from case_management_service.app.service.exceptions import DocumentNotFoundError, KafkaProducerError, ConcurrencyConflictError
from case_management_service.app.models import RequiredDocumentDB # For mock_current_doc in update status test


# Note: No class definition needed for pytest tests. Functions are discovered.

@pytest.mark.asyncio
@patch('case_management_service.app.service.commands.handlers.dispatch_event_to_projectors', new_callable=AsyncMock)
@patch('case_management_service.app.service.commands.handlers.save_event', new_callable=AsyncMock)
@patch('case_management_service.app.service.commands.handlers.get_notification_config', new_callable=AsyncMock, return_value=None)
@patch('case_management_service.app.service.commands.handlers.get_kafka_producer')
async def test_handle_create_case_command_success(
    mock_get_kafka_producer, mock_get_notification_config, mock_save_event, mock_dispatch_projectors
):
    # Arrange
    client_id = "test_client_123"
    case_type = "KYC_STANDARD"
    case_version = "1.1"

    person1_data = PersonData(firstname="John", lastname="Doe", birthdate="1990-01-01")
    person2_data = PersonData(firstname="Jane", lastname="Doe", birthdate="1992-02-02")

    cmd = commands.CreateCaseCommand(
        client_id=client_id,
        case_type=case_type,
        case_version=case_version,
        traitement_type="KYC",
        persons=[person1_data, person2_data],
        company_profile=None,
        beneficial_owners=[]
    )
    mock_kafka_producer_instance = MagicMock(spec=KafkaProducerService)
    mock_get_kafka_producer.return_value = mock_kafka_producer_instance

    # Act
    returned_case_id_str = await command_handlers.handle_create_case_command(cmd)

    # Assert
    assert returned_case_id_str is not None
    try:
        uuid.UUID(returned_case_id_str)
    except ValueError:
        pytest.fail("Returned case_id is not a valid UUID string")

    assert mock_save_event.call_count == 3
    saved_events = [call_obj.args[0] for call_obj in mock_save_event.call_args_list]
    case_created_event = next(e for e in saved_events if isinstance(e, domain_events.CaseCreatedEvent))
    assert case_created_event.payload.traitement_type == "KYC"
    assert mock_dispatch_projectors.call_count == 3

@pytest.mark.asyncio
@patch('case_management_service.app.service.commands.handlers.get_kafka_producer')
@patch('case_management_service.app.service.commands.handlers.get_notification_config', new_callable=AsyncMock)
@patch('case_management_service.app.service.commands.handlers.dispatch_event_to_projectors', new_callable=AsyncMock)
@patch('case_management_service.app.service.commands.handlers.save_event', new_callable=AsyncMock)
async def test_handle_create_case_command_kyb_sends_notification_if_configured(
    mock_save_event, mock_dispatch_projectors, mock_get_notification_config, mock_get_kafka_producer
):
    client_id = "kyb_notify_client"
    case_type = "KYB_STANDARD"
    traitement_type = "KYB"
    case_id_generated_by_handler = None # Local variable for capturing ID

    company_address = AddressData(street="Notify St", city="Notifia", country="NF", postal_code="NF1")
    company_profile = CompanyProfileData(
        registered_name="Notify Corp", registration_number="N789",
        country_of_incorporation="NF", registered_address=company_address
    )
    person_data = PersonData(firstname="NotifyFirst", lastname="NotifyLast", birthdate="1985-01-01")
    cmd = commands.CreateCaseCommand(
        client_id=client_id, case_type=case_type, case_version="1.0",
        traitement_type=traitement_type, company_profile=company_profile,
        persons=[person_data], beneficial_owners=[]
    )

    active_rule = NotificationRule(
        rule_id="rule_kyb_case_created", is_active=True,
        notification_type="EMAIL_KYB_CASE_OPENED", template_id="kyb_opened_tpl"
    )
    mock_get_notification_config.return_value = active_rule

    mock_kafka_producer_instance = MagicMock(spec=KafkaProducerService)
    mock_kafka_producer_instance.produce_message = MagicMock()
    mock_get_kafka_producer.return_value = mock_kafka_producer_instance

    all_saved_events_capture = []
    original_save_event = mock_save_event.side_effect # In case it's already a mock

    async def capture_and_save(event_data, db_session=None): # Adjusted for potential db_session if used by actual save_event
        nonlocal case_id_generated_by_handler
        # If the actual save_event is complex and involves db_session, this mock might need adjustment
        # For now, assuming event_data is the first arg, and db_session is optional or handled by get_database
        if isinstance(event_data, domain_events.CaseCreatedEvent):
            case_id_generated_by_handler = event_data.aggregate_id
        all_saved_events_capture.append(event_data)
        if asyncio.iscoroutinefunction(original_save_event):
             return await original_save_event(event_data, db_session) if db_session else await original_save_event(event_data)
        elif callable(original_save_event):
             return original_save_event(event_data, db_session) if db_session else original_save_event(event_data)
        return event_data # Default mock return
    mock_save_event.side_effect = capture_and_save


    await command_handlers.handle_create_case_command(cmd)

    mock_get_notification_config.assert_called_once()
    config_call_args = mock_get_notification_config.call_args.args
    assert config_call_args[0] == f"CASE_CREATED_{traitement_type}_{case_type}".upper()
    assert mock_save_event.call_count == 3

    notification_event_saved = next((e for e in all_saved_events_capture if isinstance(e, domain_events.NotificationRequiredEvent)), None)
    assert notification_event_saved is not None, "NotificationRequiredEvent was not saved"
    assert notification_event_saved.payload.notification_type == active_rule.notification_type
    assert notification_event_saved.payload.template_id == active_rule.template_id
    assert notification_event_saved.aggregate_id == case_id_generated_by_handler

    case_created_event = next(e for e in all_saved_events_capture if isinstance(e, domain_events.CaseCreatedEvent))
    assert notification_event_saved.version == case_created_event.version + 1

    mock_get_kafka_producer.assert_called_once()
    mock_kafka_producer_instance.produce_message.assert_called_once_with(
        topic=settings.NOTIFICATION_KAFKA_TOPIC,
        message=notification_event_saved,
        key=case_id_generated_by_handler
    )
    assert mock_dispatch_projectors.call_count == 2

@pytest.mark.asyncio
@patch('case_management_service.app.service.commands.handlers.get_kafka_producer')
@patch('case_management_service.app.service.commands.handlers.get_notification_config', new_callable=AsyncMock)
@patch('case_management_service.app.service.commands.handlers.save_event', new_callable=AsyncMock)
async def test_handle_create_case_command_no_notification_if_rule_inactive(
    mock_save_event, mock_get_notification_config, mock_get_kafka_producer
):
    cmd = commands.CreateCaseCommand(
        client_id="c1", case_type="CT1", case_version="1.0",
        traitement_type="KYC", persons=[PersonData(firstname="f", lastname="l")]
    )
    inactive_rule = NotificationRule(rule_id="r_inactive", is_active=False, notification_type="T", template_id="TPL")
    mock_get_notification_config.return_value = inactive_rule
    mock_kafka_producer_instance = MagicMock(spec=KafkaProducerService)
    mock_get_kafka_producer.return_value = mock_kafka_producer_instance

    await command_handlers.handle_create_case_command(cmd)

    mock_get_notification_config.assert_called_once()
    notification_event_saved = any(
        isinstance(call_arg.args[0], domain_events.NotificationRequiredEvent)
        for call_arg in mock_save_event.call_args_list
    )
    assert not notification_event_saved, "NotificationRequiredEvent should not have been saved"
    mock_kafka_producer_instance.produce_message.assert_not_called()

@pytest.mark.asyncio
@patch('case_management_service.app.service.commands.handlers.get_notification_strategy')
@patch('case_management_service.app.service.commands.handlers.save_event', new_callable=AsyncMock)
@patch('case_management_service.app.service.commands.handlers.get_kafka_producer')
@patch('case_management_service.app.service.commands.handlers.get_notification_config')
async def test_handle_create_case_kafka_error(
    mock_get_notification_config, mock_get_kafka_producer, mock_save_event, mock_get_notification_strategy, mocker
):
    # mock_db = AsyncMock() # Not directly passed to handler
    mock_config_client_instance = AsyncMock()
    mock_get_notification_config.return_value = mock_config_client_instance

    mock_notification_strategy_instance = AsyncMock()
    mock_get_notification_strategy.return_value = mock_notification_strategy_instance
    mock_notification_payload = domain_events.NotificationRequiredEventPayload(
        notification_type="TEST_KAFKA_ERROR", recipient_details={}, template_id="test_kafka_tpl", language_code="en"
    )
    mock_notification_strategy_instance.prepare_notification.return_value = mock_notification_payload

    mock_kafka_producer_instance = AsyncMock(spec=KafkaProducerService)
    mock_kafka_producer_instance.produce_message.side_effect = Exception("Kafka broke")
    mock_get_kafka_producer.return_value = mock_kafka_producer_instance

    command = commands.CreateCaseCommand(
        client_id="client_kafka_error", case_type="TypeKafka", traitement_type="KYC",
        persons=[PersonData(firstname="Kafka", lastname="Test", birthdate="1990-01-01")]
    )

    with pytest.raises(KafkaProducerError):
        await command_handlers.handle_create_case_command(command)

    notification_event_saved = any(
        isinstance(call_args.args[0], domain_events.NotificationRequiredEvent)
        for call_args in mock_save_event.call_args_list
    )
    assert notification_event_saved, "NotificationRequiredEvent should have been saved before Kafka error"

@pytest.mark.asyncio
@patch('case_management_service.app.service.commands.handlers.get_kafka_producer')
@patch('case_management_service.app.service.commands.handlers.get_notification_strategy')
@patch('case_management_service.app.service.commands.handlers.save_event', new_callable=AsyncMock)
@patch('case_management_service.app.service.commands.handlers.dispatch_event_to_projectors', new_callable=AsyncMock)
# Note: get_notification_config is implicitly part of get_notification_strategy's behavior or not called if strategy returns None first
async def test_handle_create_case_no_notification_if_strategy_returns_none(
    mock_dispatch_projectors, mock_save_event, mock_get_notification_strategy, mock_get_kafka_producer
):
    cmd = commands.CreateCaseCommand(
        client_id="client_no_notify", case_type="KYC_MINIMAL", case_version="1.0",
        traitement_type="KYC", persons=[PersonData(firstname="No", lastname="Notify", birthdate="2000-01-01")]
    )

    mock_notification_strategy_instance = AsyncMock()
    mock_notification_strategy_instance.prepare_notification.return_value = None # Strategy decides no notification
    mock_get_notification_strategy.return_value = mock_notification_strategy_instance

    mock_kafka_producer_instance = MagicMock(spec=KafkaProducerService)
    mock_get_kafka_producer.return_value = mock_kafka_producer_instance

    await command_handlers.handle_create_case_command(cmd)

    notification_event_saved = any(
        isinstance(call_arg.args[0], domain_events.NotificationRequiredEvent)
        for call_arg in mock_save_event.call_args_list
    )
    assert not notification_event_saved, "NotificationRequiredEvent should not have been saved"
    mock_kafka_producer_instance.produce_message.assert_not_called()
    # Check that other core events were still processed (e.g., CaseCreated, PersonAddedToCase)
    assert mock_save_event.call_count > 0 # Should be 2 for CaseCreated and PersonAddedToCase
    assert mock_dispatch_projectors.call_count == mock_save_event.call_count


@pytest.mark.asyncio
@patch('case_management_service.app.service.commands.handlers.logger') # Mock the logger in the handlers module
@patch('case_management_service.app.service.commands.handlers.save_event', new_callable=AsyncMock)
@patch('case_management_service.app.service.commands.handlers.dispatch_event_to_projectors', new_callable=AsyncMock)
# Mock notification related dependencies as they might be called
@patch('case_management_service.app.service.commands.handlers.get_notification_strategy', new_callable=AsyncMock)
@patch('case_management_service.app.service.commands.handlers.get_kafka_producer', new_callable=AsyncMock)
async def test_handle_create_case_kyb_no_company_profile(
    mock_get_kafka_producer, mock_get_notification_strategy,
    mock_dispatch_projectors, mock_save_event, mock_logger
):
    cmd = commands.CreateCaseCommand(
        client_id="kyb_no_comp", case_type="KYB_LIGHT", case_version="1.0",
        traitement_type="KYB", persons=[PersonData(firstname="Test", lastname="Person", birthdate="1990-01-01", role_in_company="Director")], # Person with role
        company_profile=None, # Explicitly None for KYB
        beneficial_owners=[]
    )
    # Setup minimal notification mocking to avoid errors if called
    mock_notification_strategy_instance = AsyncMock()
    mock_notification_strategy_instance.prepare_notification.return_value = None
    mock_get_notification_strategy.return_value = mock_notification_strategy_instance


    await command_handlers.handle_create_case_command(cmd)

    mock_logger.warning.assert_called_once_with(
        "Company profile is missing for KYB case. Company related events will be skipped. Case ID will be generated."
    )

    saved_events = [call_arg.args[0] for call_arg in mock_save_event.call_args_list]

    # Check that CaseCreatedEvent was saved
    case_created_event = next((e for e in saved_events if isinstance(e, domain_events.CaseCreatedEvent)), None)
    assert case_created_event is not None
    assert case_created_event.payload.company_id is None # Important check

    # Check that NO CompanyProfileCreatedEvent was saved
    company_profile_created_event = next((e for e in saved_events if isinstance(e, domain_events.CompanyProfileCreatedEvent)), None)
    assert company_profile_created_event is None

    # Check that PersonAddedToCaseEvent was saved (as persons list is not empty)
    person_added_event = next((e for e in saved_events if isinstance(e, domain_events.PersonAddedToCaseEvent)), None)
    assert person_added_event is not None

    # Check that NO PersonLinkedToCompanyEvent was saved (since no company profile/ID)
    person_linked_event = next((e for e in saved_events if isinstance(e, domain_events.PersonLinkedToCompanyEvent)), None)
    assert person_linked_event is None

    # Total events: CaseCreated, PersonAddedToCase. (No notification by default mock)
    assert mock_save_event.call_count == 2
    assert mock_dispatch_projectors.call_count == 2


@pytest.mark.asyncio
@patch('case_management_service.app.service.commands.handlers.logger') # Mock the logger
@patch('case_management_service.app.service.commands.handlers.save_event', new_callable=AsyncMock)
@patch('case_management_service.app.service.commands.handlers.dispatch_event_to_projectors', new_callable=AsyncMock)
@patch('case_management_service.app.service.commands.handlers.get_notification_strategy', new_callable=AsyncMock)
@patch('case_management_service.app.service.commands.handlers.get_kafka_producer', new_callable=AsyncMock)
async def test_handle_create_case_kyb_person_no_role(
    mock_get_kafka_producer, mock_get_notification_strategy,
    mock_dispatch_projectors, mock_save_event, mock_logger
):
    company_address = AddressData(street="123 Corp St", city="Corptown", country="US", postal_code="12345")
    company_profile_data = CompanyProfileData(
        registered_name="RoleTest Corp", registration_number="RT001",
        country_of_incorporation="US", registered_address=company_address
    )
    # Person with no role_in_company
    person_no_role = PersonData(firstname="NoRole", lastname="Person", birthdate="1985-01-01")
    # Person with a role for control
    person_with_role = PersonData(firstname="WithRole", lastname="Director", birthdate="1980-01-01", role_in_company="Director")

    cmd = commands.CreateCaseCommand(
        client_id="kyb_person_no_role", case_type="KYB_FULL", case_version="1.0",
        traitement_type="KYB",
        persons=[person_no_role, person_with_role],
        company_profile=company_profile_data,
        beneficial_owners=[]
    )
    mock_notification_strategy_instance = AsyncMock()
    mock_notification_strategy_instance.prepare_notification.return_value = None
    mock_get_notification_strategy.return_value = mock_notification_strategy_instance

    await command_handlers.handle_create_case_command(cmd)

    mock_logger.warning.assert_called_with(
        f"Person {person_no_role.firstname} {person_no_role.lastname} is missing role_in_company for KYB case. Skipping PersonLinkedToCompanyEvent for this person."
    )

    saved_events = [call_arg.args[0] for call_obj in mock_save_event.call_args_list]

    # PersonLinkedToCompanyEvent should only be created for person_with_role
    person_linked_events = [e for e in saved_events if isinstance(e, domain_events.PersonLinkedToCompanyEvent)]
    assert len(person_linked_events) == 1
    assert person_linked_events[0].payload.firstname == person_with_role.firstname

    # Expected events: CaseCreated, CompanyProfileCreated, 2x PersonAddedToCase, 1x PersonLinkedToCompany
    # (No notification by default mock)
    assert mock_save_event.call_count == 5
    assert mock_dispatch_projectors.call_count == 5


@pytest.mark.asyncio
@patch('case_management_service.app.service.commands.handlers.save_event', new_callable=AsyncMock)
@patch('case_management_service.app.service.commands.handlers.dispatch_event_to_projectors', new_callable=AsyncMock)
@patch('case_management_service.app.service.commands.handlers.get_notification_strategy', new_callable=AsyncMock) # Assume no notification for simplicity
@patch('case_management_service.app.service.commands.handlers.get_kafka_producer', new_callable=AsyncMock)
async def test_handle_create_case_kyb_with_beneficial_owners(
    mock_get_kafka_producer, mock_get_notification_strategy,
    mock_dispatch_projectors, mock_save_event
):
    company_address = AddressData(street="BO St", city="BO Town", country="BO", postal_code="BO123")
    company_profile_data = CompanyProfileData(
        registered_name="BOTest Corp", registration_number="BOT001",
        country_of_incorporation="BO", registered_address=company_address
    )
    bo1_person_details = PersonData(firstname="Beneficial1", lastname="Owner1", birthdate="1970-01-01")
    bo1_data = BeneficialOwnerData(person_details=bo1_person_details, is_ubo=True, ownership_percentage=50.0)

    bo2_person_details = PersonData(firstname="Beneficial2", lastname="Owner2", birthdate="1975-01-01")
    bo2_data = BeneficialOwnerData(person_details=bo2_person_details, is_ubo=False, ownership_percentage=25.0, types_of_control=["SIGNIFICANT_INFLUENCE"])

    cmd = commands.CreateCaseCommand(
        client_id="kyb_with_bos", case_type="KYB_INVESTIGATION", case_version="1.0",
        traitement_type="KYB",
        persons=[], # No main persons for simplicity here
        company_profile=company_profile_data,
        beneficial_owners=[bo1_data, bo2_data]
    )
    mock_notification_strategy_instance = AsyncMock()
    mock_notification_strategy_instance.prepare_notification.return_value = None
    mock_get_notification_strategy.return_value = mock_notification_strategy_instance

    await command_handlers.handle_create_case_command(cmd)

    saved_events = [call_obj.args[0] for call_obj in mock_save_event.call_args_list]

    bo_added_events = [e for e in saved_events if isinstance(e, domain_events.BeneficialOwnerAddedEvent)]
    assert len(bo_added_events) == 2

    # Check details of first BO event
    bo1_event_payload = next(e.payload for e in bo_added_events if e.payload.person_details.firstname == "Beneficial1")
    assert bo1_event_payload.is_ubo is True
    assert bo1_event_payload.ownership_percentage == 50.0
    assert bo1_event_payload.person_details.lastname == "Owner1"

    # Check details of second BO event
    bo2_event_payload = next(e.payload for e in bo_added_events if e.payload.person_details.firstname == "Beneficial2")
    assert bo2_event_payload.is_ubo is False
    assert bo2_event_payload.ownership_percentage == 25.0
    assert "SIGNIFICANT_INFLUENCE" in bo2_event_payload.types_of_control

    # Expected: CaseCreated, CompanyProfileCreated, 2x BeneficialOwnerAddedEvent
    assert mock_save_event.call_count == 4
    assert mock_dispatch_projectors.call_count == 4


# --- Tests for handle_determine_initial_document_requirements ---
@pytest.mark.asyncio
@patch('case_management_service.app.service.commands.handlers.get_document_strategy')
@patch('case_management_service.app.service.commands.handlers.save_event', new_callable=AsyncMock)
@patch('case_management_service.app.service.commands.handlers.dispatch_event_to_projectors', new_callable=AsyncMock)
async def test_handle_determine_doc_reqs_success( # Existing test, ensure it's not broken
    mock_dispatch_projectors, mock_save_event, mock_get_strategy
):
    mock_doc_strategy_instance = AsyncMock()
    mock_get_strategy.return_value = mock_doc_strategy_instance
    mock_doc_strategy_instance.determine_requirements.return_value = [
        {"type": "PASSPORT", "is_required": True, "entity_type": "PERSON", "entity_id": "entity1"},
        {"type": "VISA", "is_required": False, "entity_type": "PERSON", "entity_id": "entity1"},
    ]

    command = commands.DetermineInitialDocumentRequirementsCommand(
        case_id="case1", entity_id="entity1", entity_type="PERSON", traitement_type="KYC", case_type="STANDARD"
    )
    result_event_ids = await command_handlers.handle_determine_initial_document_requirements(command)

    assert len(result_event_ids) == 2
    mock_doc_strategy_instance.determine_requirements.assert_called_once_with(command)
    assert mock_save_event.call_count == 2
    saved_event_1 = mock_save_event.call_args_list[0].args[0]
    assert isinstance(saved_event_1, domain_events.DocumentRequirementDeterminedEvent)
    assert saved_event_1.payload.document_type == "PASSPORT"
    assert saved_event_1.payload.is_required
    assert mock_dispatch_projectors.call_count == 2

@pytest.mark.asyncio
@patch('case_management_service.app.service.commands.handlers.get_document_strategy')
@patch('case_management_service.app.service.commands.handlers.save_event', new_callable=AsyncMock)
@patch('case_management_service.app.service.commands.handlers.dispatch_event_to_projectors', new_callable=AsyncMock)
async def test_handle_determine_doc_reqs_no_reqs_from_strategy( # Existing test
    mock_dispatch_projectors, mock_save_event, mock_get_strategy
):
    mock_doc_strategy_instance = AsyncMock()
    mock_get_strategy.return_value = mock_doc_strategy_instance
    mock_doc_strategy_instance.determine_requirements.return_value = []

    command = commands.DetermineInitialDocumentRequirementsCommand(
        case_id="case2", entity_id="entity2", entity_type="PERSON", traitement_type="KYC", case_type="STANDARD"
    )
    result_event_ids = await command_handlers.handle_determine_initial_document_requirements(command)

    assert len(result_event_ids) == 0
    mock_doc_strategy_instance.determine_requirements.assert_called_once_with(command)
    mock_save_event.assert_not_called()
    mock_dispatch_projectors.assert_not_called()

# --- Tests for handle_update_document_status ---
@pytest.mark.asyncio
@patch('case_management_service.app.service.commands.handlers.get_required_document_by_id_from_read_model', new_callable=AsyncMock)
@patch('case_management_service.app.service.commands.handlers.save_event', new_callable=AsyncMock)
@patch('case_management_service.app.service.commands.handlers.dispatch_event_to_projectors', new_callable=AsyncMock)
async def test_handle_update_doc_status_success_with_all_details( # Modified existing test
    mock_dispatch_projectors, mock_save_event, mock_get_doc_from_read_model
):
    doc_id = str(uuid.uuid4())
    current_version = 2
    actor_id = "user123"
    actor_type = "SYSTEM_USER"
    metadata_update = {"review_comment": "Looks good"}
    notes_add = ["Document verified by automated system.", "Cross-checked with external DB."]

    mock_current_doc = RequiredDocumentDB(
        id=doc_id, case_id="case1", entity_id="entity1", entity_type="PERSON",
        document_type="PASSPORT", status="AWAITING_UPLOAD", version=current_version,
        created_at=datetime.datetime.now(datetime.timezone.utc),
        updated_at=datetime.datetime.now(datetime.timezone.utc)
    )
    mock_get_doc_from_read_model.return_value = mock_current_doc

    command = commands.UpdateDocumentStatusCommand(
        document_requirement_id=doc_id,
        new_status="VERIFIED_AUTO",
        updated_by_actor_id=actor_id,
        updated_by_actor_type=actor_type,
        metadata_changes=metadata_update,
        notes_to_add=notes_add
    )
    result_id = await command_handlers.handle_update_document_status(command)

    assert result_id == doc_id
    mock_get_doc_from_read_model.assert_called_once_with(doc_id)
    mock_save_event.assert_called_once()

    saved_event: domain_events.DocumentStatusUpdatedEvent = mock_save_event.call_args[0][0]
    assert isinstance(saved_event, domain_events.DocumentStatusUpdatedEvent)
    assert saved_event.version == current_version + 1

    payload = saved_event.payload
    assert payload.new_status == "VERIFIED_AUTO"
    assert payload.old_status == "AWAITING_UPLOAD"
    assert payload.document_requirement_id == doc_id
    assert payload.updated_by_actor_id == actor_id
    assert payload.updated_by_actor_type == actor_type
    assert payload.metadata_update == metadata_update
    assert payload.notes_added == notes_add

    mock_dispatch_projectors.assert_called_once_with(saved_event)

@pytest.mark.asyncio
@patch('case_management_service.app.service.commands.handlers.get_required_document_by_id_from_read_model', new_callable=AsyncMock)
async def test_handle_update_doc_status_not_found(mock_get_doc_from_read_model): # Existing test
    doc_id = str(uuid.uuid4())
    mock_get_doc_from_read_model.return_value = None

    command = commands.UpdateDocumentStatusCommand(document_requirement_id=doc_id, new_status="UPLOADED")
    with pytest.raises(DocumentNotFoundError) as exc_info:
        await command_handlers.handle_update_document_status(command)
    assert exc_info.value.document_id == doc_id

@pytest.mark.asyncio
@patch('case_management_service.app.service.commands.handlers.get_required_document_by_id_from_read_model', new_callable=AsyncMock)
@patch('case_management_service.app.service.commands.handlers.save_event', new_callable=AsyncMock)
@patch('case_management_service.app.service.commands.handlers.dispatch_event_to_projectors', new_callable=AsyncMock)
async def test_handle_update_doc_status_concurrency_error(
    mock_dispatch_projectors, mock_save_event, mock_get_doc_from_read_model
):
    # mock_db = AsyncMock() # Not directly passed
    doc_id = str(uuid.uuid4())
    current_version = 3
    mock_current_doc = RequiredDocumentDB(
        id=doc_id, case_id="case1", entity_id="entity1", entity_type="PERSON",
        document_type="PASSPORT", status="AWAITING_UPLOAD", version=current_version,
        created_at=datetime.datetime.now(datetime.timezone.utc),
        updated_at=datetime.datetime.now(datetime.timezone.utc)
    )
    mock_get_doc_from_read_model.return_value = mock_current_doc
    mock_save_event.side_effect = ConcurrencyConflictError(
        aggregate_id=doc_id, expected_version=current_version + 1, actual_version=current_version + 1
    )

    command = commands.UpdateDocumentStatusCommand(document_requirement_id=doc_id, new_status="VERIFIED_SYSTEM")
    with pytest.raises(ConcurrencyConflictError):
        await command_handlers.handle_update_document_status(command)

    mock_save_event.assert_called_once()
    mock_dispatch_projectors.assert_not_called()
