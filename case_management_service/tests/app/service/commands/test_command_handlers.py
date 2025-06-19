import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app.service.commands.handlers import (
    handle_create_case_command,
    handle_determine_initial_document_requirements,
    handle_update_document_status,
)
from app.service.commands.commands import (
    CreateCaseCommand,
    DetermineInitialDocumentRequirementsCommand,
    UpdateDocumentStatusCommand,
)
from app.service.events.events import (
    CaseCreatedEvent,
    PersonAddedToCaseEvent,
    CompanyProfileCreatedEvent,
    PersonLinkedToCompanyEvent,
    BeneficialOwnerAddedEvent,
    NotificationRequiredEvent,
    DocumentRequirementDeterminedEvent,
    DocumentStatusUpdatedEvent,
)
from app.service.models import (
    CaseType,
    PersonProfile,
    CompanyProfile,
    Role,
    BeneficialOwner,
    DocumentStatus,
    DocumentSpecification,
    RequiredDocumentDB,
)
from app.service.event_store.event_store import EventStore
from app.service.projectors.projector import dispatch_event_to_projectors
from app.infrastructure.kafka.kafka_producer import KafkaProducer
from app.infrastructure.notification.notification_config import NotificationConfigClient, NotificationStrategy
from app.infrastructure.document_management.document_management import DocumentStrategy
from app.shared.errors import KafkaProducerError, DocumentNotFoundError

# Mock database for tests
@pytest.fixture
def mock_db():
    return AsyncMock()

# Mock EventStore for tests
@pytest.fixture
def mock_event_store(mock_db):
    return EventStore(database=mock_db)

# Mock KafkaProducer for tests
@pytest.fixture
def mock_kafka_producer():
    producer = AsyncMock(spec=KafkaProducer)
    producer.produce_message = AsyncMock()
    return producer

# Mock NotificationConfigClient for tests
@pytest.fixture
def mock_notification_config_client():
    client = AsyncMock(spec=NotificationConfigClient)
    client.get_notification_strategy = AsyncMock(return_value=NotificationStrategy.SEND_ALL) # Default strategy
    return client

# Mock DocumentStrategy for tests
@pytest.fixture
def mock_document_strategy():
    strategy = AsyncMock(spec=DocumentStrategy)
    strategy.get_document_requirements = AsyncMock(return_value=[]) # Default empty list
    return strategy

@pytest.mark.asyncio
async def test_placeholder():
    # This is a placeholder test to ensure the file is created and pytest runs.
    # It will be replaced with actual tests.
    assert True

@pytest.mark.asyncio
@patch("app.service.commands.handlers.uuid.uuid4")
@patch("app.service.commands.handlers.dispatch_event_to_projectors")
@patch("app.service.commands.handlers.save_event")
async def test_handle_create_case_command_kyc_valid(
    mock_save_event: AsyncMock,
    mock_dispatch_event_to_projectors: AsyncMock,
    mock_uuid4: MagicMock,
    mock_event_store: EventStore,
    mock_kafka_producer: KafkaProducer,
    mock_notification_config_client: NotificationConfigClient,
    mock_db: AsyncMock, # Added mock_db here
):
    """
    Test handle_create_case_command for a valid KYC case.
    Verifies CaseCreatedEvent and PersonAddedToCaseEvent(s) are generated and saved.
    Verifies NotificationRequiredEvent is (or isn't) generated and sent via Kafka.
    Verifies events are dispatched to projectors.
    """
    case_id = uuid.uuid4()
    user_id = "test_user"
    mock_uuid4.return_value = case_id

    person1_id = uuid.uuid4()
    person1_profile = PersonProfile(name="John Doe", email="john.doe@example.com")
    person2_id = uuid.uuid4()
    person2_profile = PersonProfile(name="Jane Doe", email="jane.doe@example.com")

    command = CreateCaseCommand(
        case_type=CaseType.KYC,
        created_by=user_id,
        persons=[
            {"person_id": person1_id, "profile": person1_profile, "role": Role.PRIMARY_CONTACT},
            {"person_id": person2_id, "profile": person2_profile, "role": Role.ADDITIONAL_CONTACT},
        ],
        company_profile=None,
        beneficial_owners=None,
    )

    # Mock get_kafka_producer and get_notification_strategy from handlers
    with patch("app.service.commands.handlers.get_kafka_producer", return_value=mock_kafka_producer), \
         patch("app.service.commands.handlers.get_notification_config_client", return_value=mock_notification_config_client), \
         patch("app.service.commands.handlers.get_notification_strategy", return_value=NotificationStrategy.SEND_ALL) as mock_get_notification_strategy:

        await handle_create_case_command(command, mock_event_store, mock_db)

        # Assertions for CaseCreatedEvent
        case_created_event_call = next(
            call for call in mock_save_event.call_args_list if isinstance(call.args[1], CaseCreatedEvent)
        )
        case_created_event: CaseCreatedEvent = case_created_event_call.args[1]
        assert case_created_event.aggregate_id == case_id
        assert case_created_event.version == 1
        assert case_created_event.payload["case_type"] == CaseType.KYC.value
        assert case_created_event.payload["created_by"] == user_id

        # Assertions for PersonAddedToCaseEvent (John Doe)
        person1_added_event_call = next(
            call for call in mock_save_event.call_args_list if isinstance(call.args[1], PersonAddedToCaseEvent) and call.args[1].payload["person_id"] == person1_id
        )
        person1_added_event: PersonAddedToCaseEvent = person1_added_event_call.args[1]
        assert person1_added_event.aggregate_id == case_id
        assert person1_added_event.version == 2 # Assuming CaseCreated was version 1
        assert person1_added_event.payload["person_id"] == person1_id
        assert person1_added_event.payload["profile"] == person1_profile.model_dump()
        assert person1_added_event.payload["role"] == Role.PRIMARY_CONTACT.value

        # Assertions for PersonAddedToCaseEvent (Jane Doe)
        person2_added_event_call = next(
            call for call in mock_save_event.call_args_list if isinstance(call.args[1], PersonAddedToCaseEvent) and call.args[1].payload["person_id"] == person2_id
        )
        person2_added_event: PersonAddedToCaseEvent = person2_added_event_call.args[1]
        assert person2_added_event.aggregate_id == case_id
        # Version depends on the order of person processing, could be 3 or 4 if no company events
        assert person2_added_event.version > 1
        assert person2_added_event.payload["person_id"] == person2_id
        assert person2_added_event.payload["profile"] == person2_profile.model_dump()
        assert person2_added_event.payload["role"] == Role.ADDITIONAL_CONTACT.value

        # Assertions for NotificationRequiredEvent
        mock_get_notification_strategy.assert_called_once_with(mock_db, CaseType.KYC, None) # No action for KYC

        # Check if NotificationRequiredEvent was created and sent
        notification_event_call = next(
            (call for call in mock_save_event.call_args_list if isinstance(call.args[1], NotificationRequiredEvent)),
            None
        )
        if NotificationStrategy.SEND_ALL: # or whatever condition makes it send
            assert notification_event_call is not None
            notification_event: NotificationRequiredEvent = notification_event_call.args[1]
            assert notification_event.aggregate_id == case_id
            assert notification_event.payload["case_id"] == case_id
            assert notification_event.payload["notification_type"] == "CASE_CREATED"

            mock_kafka_producer.produce_message.assert_called_once()
            kafka_call_args = mock_kafka_producer.produce_message.call_args
            assert kafka_call_args[0][0] == "notification_requests" # topic
            assert kafka_call_args[0][1]["case_id"] == str(case_id) # message key
            assert kafka_call_args[0][2]["notification_type"] == "CASE_CREATED" # message value
        else:
            assert notification_event_call is None
            mock_kafka_producer.produce_message.assert_not_called()


        # Assertions for dispatch_event_to_projectors
        # It should be called for each saved event
        assert mock_dispatch_event_to_projectors.call_count == mock_save_event.call_count
        dispatch_calls = mock_dispatch_event_to_projectors.call_args_list
        saved_events = [call.args[1] for call in mock_save_event.call_args_list]

        for i, call in enumerate(dispatch_calls):
            assert call.args[0] == mock_db
            assert call.args[1] == saved_events[i] # Ensure the correct event was dispatched

        # Ensure save_event was called for all generated events
        # 1 CaseCreatedEvent + 2 PersonAddedToCaseEvent + 1 NotificationRequiredEvent (if applicable)
        expected_save_event_calls = 1 + 2 + (1 if NotificationStrategy.SEND_ALL else 0)
        assert mock_save_event.call_count == expected_save_event_calls


@pytest.mark.asyncio
@patch("app.service.commands.handlers.uuid.uuid4")
@patch("app.service.commands.handlers.dispatch_event_to_projectors")
@patch("app.service.commands.handlers.save_event")
async def test_handle_create_case_command_kyb_full_valid(
    mock_save_event: AsyncMock,
    mock_dispatch_event_to_projectors: AsyncMock,
    mock_uuid4: MagicMock,
    mock_event_store: EventStore,
    mock_kafka_producer: KafkaProducer,
    mock_notification_config_client: NotificationConfigClient,
    mock_db: AsyncMock,
):
    """
    Test handle_create_case_command for a valid KYB case with company, persons, and BOs.
    Verifies CompanyProfileCreatedEvent, PersonLinkedToCompanyEvent(s),
    BeneficialOwnerAddedEvent(s), and CaseCreatedEvent are generated and saved.
    Verifies notification logic and event dispatch.
    """
    case_id = uuid.uuid4()
    user_id = "test_user_kyb"
    company_id = uuid.uuid4()
    mock_uuid4.side_effect = [case_id, company_id] # First for case, second for company if generated by handler

    company_profile_data = CompanyProfile(name="Test Corp", registration_number="12345")
    person1_id = uuid.uuid4()
    person1_profile = PersonProfile(name="CEO Person", email="ceo@testcorp.com")
    bo1_id = uuid.uuid4()
    bo1_profile = PersonProfile(name="BO One", email="bo1@testcorp.com")

    command = CreateCaseCommand(
        case_type=CaseType.KYB,
        created_by=user_id,
        company_profile={"company_id": company_id, "profile": company_profile_data},
        persons=[
            {"person_id": person1_id, "profile": person1_profile, "role": Role.DIRECTOR},
        ],
        beneficial_owners=[
            {"bo_id": bo1_id, "profile": bo1_profile, "ownership_percentage": 75.0},
        ],
    )

    with patch("app.service.commands.handlers.get_kafka_producer", return_value=mock_kafka_producer), \
         patch("app.service.commands.handlers.get_notification_config_client", return_value=mock_notification_config_client), \
         patch("app.service.commands.handlers.get_notification_strategy", return_value=NotificationStrategy.SEND_ALL) as mock_get_notification_strategy:

        await handle_create_case_command(command, mock_event_store, mock_db)

        # Expected order of events and their versions (approximate)
        # 1. CompanyProfileCreatedEvent (version 1 for company aggregate)
        # 2. PersonLinkedToCompanyEvent (version 2 for company aggregate)
        # 3. BeneficialOwnerAddedEvent (version 3 for company aggregate)
        # 4. CaseCreatedEvent (version 1 for case aggregate)
        # 5. NotificationRequiredEvent (version 2 for case aggregate)

        # Assertions for CompanyProfileCreatedEvent
        company_created_event_call = next(
            call for call in mock_save_event.call_args_list if isinstance(call.args[1], CompanyProfileCreatedEvent)
        )
        company_created_event: CompanyProfileCreatedEvent = company_created_event_call.args[1]
        assert company_created_event.aggregate_id == company_id
        assert company_created_event.version == 1
        assert company_created_event.payload["profile"] == company_profile_data.model_dump()
        assert company_created_event.payload["created_by"] == user_id

        # Assertions for PersonLinkedToCompanyEvent
        person_linked_event_call = next(
            call for call in mock_save_event.call_args_list if isinstance(call.args[1], PersonLinkedToCompanyEvent)
        )
        person_linked_event: PersonLinkedToCompanyEvent = person_linked_event_call.args[1]
        assert person_linked_event.aggregate_id == company_id
        assert person_linked_event.version == 2
        assert person_linked_event.payload["person_id"] == person1_id
        assert person_linked_event.payload["profile"] == person1_profile.model_dump()
        assert person_linked_event.payload["role"] == Role.DIRECTOR.value

        # Assertions for BeneficialOwnerAddedEvent
        bo_added_event_call = next(
            call for call in mock_save_event.call_args_list if isinstance(call.args[1], BeneficialOwnerAddedEvent)
        )
        bo_added_event: BeneficialOwnerAddedEvent = bo_added_event_call.args[1]
        assert bo_added_event.aggregate_id == company_id
        assert bo_added_event.version == 3
        assert bo_added_event.payload["bo_id"] == bo1_id
        assert bo_added_event.payload["profile"] == bo1_profile.model_dump()
        assert bo_added_event.payload["ownership_percentage"] == 75.0

        # Assertions for CaseCreatedEvent
        case_created_event_call = next(
            call for call in mock_save_event.call_args_list if isinstance(call.args[1], CaseCreatedEvent)
        )
        case_created_event: CaseCreatedEvent = case_created_event_call.args[1]
        assert case_created_event.aggregate_id == case_id
        assert case_created_event.version == 1 # New aggregate
        assert case_created_event.payload["case_type"] == CaseType.KYB.value
        assert case_created_event.payload["created_by"] == user_id
        assert case_created_event.payload["company_id"] == company_id

        # Assertions for NotificationRequiredEvent
        mock_get_notification_strategy.assert_called_once_with(mock_db, CaseType.KYB, command.company_profile["profile"].name) # Name for KYB
        notification_event_call = next(
            (call for call in mock_save_event.call_args_list if isinstance(call.args[1], NotificationRequiredEvent)),
            None
        )
        assert notification_event_call is not None # Assuming SEND_ALL
        notification_event: NotificationRequiredEvent = notification_event_call.args[1]
        assert notification_event.aggregate_id == case_id
        assert notification_event.version == 2 # After CaseCreatedEvent for this aggregate
        assert notification_event.payload["case_id"] == case_id
        assert notification_event.payload["notification_type"] == "CASE_CREATED"

        mock_kafka_producer.produce_message.assert_called_once()
        kafka_call_args = mock_kafka_producer.produce_message.call_args
        assert kafka_call_args[0][0] == "notification_requests"
        assert kafka_call_args[0][1]["case_id"] == str(case_id)
        assert kafka_call_args[0][2]["notification_type"] == "CASE_CREATED"

        # Assertions for dispatch_event_to_projectors
        assert mock_dispatch_event_to_projectors.call_count == mock_save_event.call_count
        dispatch_calls = mock_dispatch_event_to_projectors.call_args_list
        saved_events = [call.args[1] for call in mock_save_event.call_args_list]
        for i, call in enumerate(dispatch_calls):
            assert call.args[0] == mock_db
            assert call.args[1] == saved_events[i]

        # 1 CompanyProfileCreatedEvent + 1 PersonLinkedToCompanyEvent + 1 BeneficialOwnerAddedEvent + 1 CaseCreatedEvent + 1 NotificationRequiredEvent
        assert mock_save_event.call_count == 5


@pytest.mark.asyncio
@patch("app.service.commands.handlers.uuid.uuid4")
@patch("app.service.commands.handlers.dispatch_event_to_projectors")
@patch("app.service.commands.handlers.save_event")
async def test_handle_create_case_command_kyb_minimal_company_only(
    mock_save_event: AsyncMock,
    mock_dispatch_event_to_projectors: AsyncMock,
    mock_uuid4: MagicMock,
    mock_event_store: EventStore,
    mock_kafka_producer: KafkaProducer,
    mock_notification_config_client: NotificationConfigClient,
    mock_db: AsyncMock,
):
    """
    Test handle_create_case_command for a KYB case with only company profile data.
    Verifies CompanyProfileCreatedEvent and CaseCreatedEvent are generated.
    """
    case_id = uuid.uuid4()
    user_id = "test_user_kyb_minimal"
    company_id = uuid.uuid4()
    mock_uuid4.side_effect = [case_id, company_id]

    company_profile_data = CompanyProfile(name="Minimal Corp", registration_number="00000")

    command = CreateCaseCommand(
        case_type=CaseType.KYB,
        created_by=user_id,
        company_profile={"company_id": company_id, "profile": company_profile_data},
        persons=[], # No persons
        beneficial_owners=[], # No BOs
    )

    with patch("app.service.commands.handlers.get_kafka_producer", return_value=mock_kafka_producer), \
         patch("app.service.commands.handlers.get_notification_config_client", return_value=mock_notification_config_client), \
         patch("app.service.commands.handlers.get_notification_strategy", return_value=NotificationStrategy.SEND_ALL) as mock_get_notification_strategy:

        await handle_create_case_command(command, mock_event_store, mock_db)

        # Expected events: CompanyProfileCreatedEvent, CaseCreatedEvent, NotificationRequiredEvent

        # Assertions for CompanyProfileCreatedEvent
        company_created_event_call = next(
            call for call in mock_save_event.call_args_list if isinstance(call.args[1], CompanyProfileCreatedEvent)
        )
        company_created_event: CompanyProfileCreatedEvent = company_created_event_call.args[1]
        assert company_created_event.aggregate_id == company_id
        assert company_created_event.version == 1
        assert company_created_event.payload["profile"] == company_profile_data.model_dump()

        # Assertions for CaseCreatedEvent
        case_created_event_call = next(
            call for call in mock_save_event.call_args_list if isinstance(call.args[1], CaseCreatedEvent)
        )
        case_created_event: CaseCreatedEvent = case_created_event_call.args[1]
        assert case_created_event.aggregate_id == case_id
        assert case_created_event.version == 1
        assert case_created_event.payload["company_id"] == company_id

        # Assertions for NotificationRequiredEvent
        notification_event_call = next(
            (call for call in mock_save_event.call_args_list if isinstance(call.args[1], NotificationRequiredEvent)), None
        )
        assert notification_event_call is not None
        notification_event: NotificationRequiredEvent = notification_event_call.args[1]
        assert notification_event.aggregate_id == case_id
        assert notification_event.version == 2 # After CaseCreatedEvent

        # Check that no PersonLinkedToCompanyEvent or BeneficialOwnerAddedEvent were created
        assert not any(isinstance(call.args[1], PersonLinkedToCompanyEvent) for call in mock_save_event.call_args_list)
        assert not any(isinstance(call.args[1], BeneficialOwnerAddedEvent) for call in mock_save_event.call_args_list)
        assert not any(isinstance(call.args[1], PersonAddedToCaseEvent) for call in mock_save_event.call_args_list)


        # 1 CompanyProfileCreatedEvent + 1 CaseCreatedEvent + 1 NotificationRequiredEvent
        assert mock_save_event.call_count == 3
        assert mock_dispatch_event_to_projectors.call_count == 3
        mock_kafka_producer.produce_message.assert_called_once()


@pytest.mark.asyncio
@patch("app.service.commands.handlers.uuid.uuid4")
@patch("app.service.commands.handlers.dispatch_event_to_projectors")
@patch("app.service.commands.handlers.save_event")
@patch("app.service.commands.handlers.logger") # Patch logger
async def test_handle_create_case_command_kyb_no_company_profile(
    mock_logger: MagicMock, # Injected mock_logger
    mock_save_event: AsyncMock,
    mock_dispatch_event_to_projectors: AsyncMock,
    mock_uuid4: MagicMock,
    mock_event_store: EventStore,
    mock_kafka_producer: KafkaProducer,
    mock_notification_config_client: NotificationConfigClient,
    mock_db: AsyncMock,
):
    """
    Test handle_create_case_command for KYB case with no company profile data.
    Verifies a warning is logged and only CaseCreatedEvent is generated.
    """
    case_id = uuid.uuid4()
    user_id = "test_user_kyb_no_company"
    mock_uuid4.return_value = case_id

    command = CreateCaseCommand(
        case_type=CaseType.KYB,
        created_by=user_id,
        company_profile=None, # No company profile
        persons=[],
        beneficial_owners=[],
    )

    with patch("app.service.commands.handlers.get_kafka_producer", return_value=mock_kafka_producer), \
         patch("app.service.commands.handlers.get_notification_config_client", return_value=mock_notification_config_client), \
         patch("app.service.commands.handlers.get_notification_strategy", return_value=NotificationStrategy.SEND_ALL) as mock_get_notification_strategy:

        await handle_create_case_command(command, mock_event_store, mock_db)

        # Assertions for CaseCreatedEvent
        case_created_event_call = next(
            (call for call in mock_save_event.call_args_list if isinstance(call.args[1], CaseCreatedEvent)), None
        )
        assert case_created_event_call is not None
        case_created_event: CaseCreatedEvent = case_created_event_call.args[1]
        assert case_created_event.aggregate_id == case_id
        assert case_created_event.version == 1
        assert case_created_event.payload["case_type"] == CaseType.KYB.value
        assert case_created_event.payload["created_by"] == user_id
        assert "company_id" not in case_created_event.payload # No company_id

        # Verify warning log
        mock_logger.warning.assert_called_once_with(
            f"KYB case {case_id} created without company profile information."
        )

        # Assertions for NotificationRequiredEvent (should still be created for the case itself)
        notification_event_call = next(
            (call for call in mock_save_event.call_args_list if isinstance(call.args[1], NotificationRequiredEvent)), None
        )
        assert notification_event_call is not None
        notification_event: NotificationRequiredEvent = notification_event_call.args[1]
        assert notification_event.aggregate_id == case_id
        assert notification_event.version == 2 # After CaseCreatedEvent

        # Check that no company-specific events were created
        assert not any(isinstance(call.args[1], CompanyProfileCreatedEvent) for call in mock_save_event.call_args_list)
        assert not any(isinstance(call.args[1], PersonLinkedToCompanyEvent) for call in mock_save_event.call_args_list)
        assert not any(isinstance(call.args[1], BeneficialOwnerAddedEvent) for call in mock_save_event.call_args_list)
        assert not any(isinstance(call.args[1], PersonAddedToCaseEvent) for call in mock_save_event.call_args_list)

        # 1 CaseCreatedEvent + 1 NotificationRequiredEvent
        assert mock_save_event.call_count == 2
        assert mock_dispatch_event_to_projectors.call_count == 2
        mock_kafka_producer.produce_message.assert_called_once() # Notification for case creation
        mock_get_notification_strategy.assert_called_once_with(mock_db, CaseType.KYB, None)


@pytest.mark.asyncio
@patch("app.service.commands.handlers.uuid.uuid4")
@patch("app.service.commands.handlers.dispatch_event_to_projectors")
@patch("app.service.commands.handlers.save_event")
@patch("app.service.commands.handlers.logger")
async def test_handle_create_case_command_kyc_no_persons(
    mock_logger: MagicMock,
    mock_save_event: AsyncMock,
    mock_dispatch_event_to_projectors: AsyncMock,
    mock_uuid4: MagicMock,
    mock_event_store: EventStore,
    mock_kafka_producer: KafkaProducer,
    mock_notification_config_client: NotificationConfigClient,
    mock_db: AsyncMock,
):
    """
    Test handle_create_case_command for a KYC case with no persons.
    Verifies CaseCreatedEvent is generated, and a warning is logged.
    """
    case_id = uuid.uuid4()
    user_id = "test_user_kyc_no_persons"
    mock_uuid4.return_value = case_id

    command = CreateCaseCommand(
        case_type=CaseType.KYC,
        created_by=user_id,
        persons=[], # No persons
        company_profile=None,
        beneficial_owners=None,
    )

    with patch("app.service.commands.handlers.get_kafka_producer", return_value=mock_kafka_producer), \
         patch("app.service.commands.handlers.get_notification_config_client", return_value=mock_notification_config_client), \
         patch("app.service.commands.handlers.get_notification_strategy", return_value=NotificationStrategy.SEND_ALL) as mock_get_notification_strategy:

        await handle_create_case_command(command, mock_event_store, mock_db)

        # Assertions for CaseCreatedEvent
        case_created_event_call = next(
            (call for call in mock_save_event.call_args_list if isinstance(call.args[1], CaseCreatedEvent)), None
        )
        assert case_created_event_call is not None
        case_created_event: CaseCreatedEvent = case_created_event_call.args[1]
        assert case_created_event.aggregate_id == case_id
        assert case_created_event.version == 1
        assert case_created_event.payload["case_type"] == CaseType.KYC.value

        # Verify warning log
        mock_logger.warning.assert_any_call(
            f"Case {case_id} of type KYC created without any persons."
        )

        # Assertions for NotificationRequiredEvent
        notification_event_call = next(
            (call for call in mock_save_event.call_args_list if isinstance(call.args[1], NotificationRequiredEvent)), None
        )
        assert notification_event_call is not None # Notification for case creation itself
        notification_event: NotificationRequiredEvent = notification_event_call.args[1]
        assert notification_event.aggregate_id == case_id
        assert notification_event.version == 2 # After CaseCreatedEvent

        # Check that no PersonAddedToCaseEvent were created
        assert not any(isinstance(call.args[1], PersonAddedToCaseEvent) for call in mock_save_event.call_args_list)

        # 1 CaseCreatedEvent + 1 NotificationRequiredEvent
        assert mock_save_event.call_count == 2
        assert mock_dispatch_event_to_projectors.call_count == 2
        mock_kafka_producer.produce_message.assert_called_once()
        mock_get_notification_strategy.assert_called_once_with(mock_db, CaseType.KYC, None)


@pytest.mark.asyncio
@patch("app.service.commands.handlers.uuid.uuid4")
@patch("app.service.commands.handlers.dispatch_event_to_projectors")
@patch("app.service.commands.handlers.save_event")
@patch("app.service.commands.handlers.logger")
async def test_handle_create_case_command_kyb_no_persons_no_bos(
    mock_logger: MagicMock,
    mock_save_event: AsyncMock,
    mock_dispatch_event_to_projectors: AsyncMock,
    mock_uuid4: MagicMock,
    mock_event_store: EventStore,
    mock_kafka_producer: KafkaProducer,
    mock_notification_config_client: NotificationConfigClient,
    mock_db: AsyncMock,
):
    """
    Test handle_create_case_command for a KYB case with company profile but no persons or BOs.
    Verifies CompanyProfileCreatedEvent, CaseCreatedEvent are generated, and warnings are logged.
    """
    case_id = uuid.uuid4()
    user_id = "test_user_kyb_no_persons_bos"
    company_id = uuid.uuid4()
    mock_uuid4.side_effect = [case_id, company_id]

    company_profile_data = CompanyProfile(name="Corp NoPersonsBOs", registration_number="67890")

    command = CreateCaseCommand(
        case_type=CaseType.KYB,
        created_by=user_id,
        company_profile={"company_id": company_id, "profile": company_profile_data},
        persons=[], # No persons
        beneficial_owners=[], # No BOs
    )

    with patch("app.service.commands.handlers.get_kafka_producer", return_value=mock_kafka_producer), \
         patch("app.service.commands.handlers.get_notification_config_client", return_value=mock_notification_config_client), \
         patch("app.service.commands.handlers.get_notification_strategy", return_value=NotificationStrategy.SEND_ALL) as mock_get_notification_strategy:

        await handle_create_case_command(command, mock_event_store, mock_db)

        # Assertions for CompanyProfileCreatedEvent
        company_created_event_call = next(
            (call for call in mock_save_event.call_args_list if isinstance(call.args[1], CompanyProfileCreatedEvent)), None
        )
        assert company_created_event_call is not None
        company_created_event: CompanyProfileCreatedEvent = company_created_event_call.args[1]
        assert company_created_event.aggregate_id == company_id
        assert company_created_event.version == 1

        # Assertions for CaseCreatedEvent
        case_created_event_call = next(
            (call for call in mock_save_event.call_args_list if isinstance(call.args[1], CaseCreatedEvent)), None
        )
        assert case_created_event_call is not None
        case_created_event: CaseCreatedEvent = case_created_event_call.args[1]
        assert case_created_event.aggregate_id == case_id
        assert case_created_event.version == 1
        assert case_created_event.payload["company_id"] == company_id

        # Verify warning logs
        mock_logger.warning.assert_any_call(
            f"KYB case {case_id} for company {company_id} created without any linked persons."
        )
        mock_logger.warning.assert_any_call(
            f"KYB case {case_id} for company {company_id} created without any beneficial owners."
        )

        # Assertions for NotificationRequiredEvent
        notification_event_call = next(
            (call for call in mock_save_event.call_args_list if isinstance(call.args[1], NotificationRequiredEvent)), None
        )
        assert notification_event_call is not None
        notification_event: NotificationRequiredEvent = notification_event_call.args[1]
        assert notification_event.aggregate_id == case_id
        assert notification_event.version == 2 # After CaseCreatedEvent

        # Check no person/BO events
        assert not any(isinstance(call.args[1], PersonAddedToCaseEvent) for call in mock_save_event.call_args_list)
        assert not any(isinstance(call.args[1], PersonLinkedToCompanyEvent) for call in mock_save_event.call_args_list)
        assert not any(isinstance(call.args[1], BeneficialOwnerAddedEvent) for call in mock_save_event.call_args_list)

        # 1 CompanyProfileCreatedEvent + 1 CaseCreatedEvent + 1 NotificationRequiredEvent
        assert mock_save_event.call_count == 3
        assert mock_dispatch_event_to_projectors.call_count == 3
        mock_kafka_producer.produce_message.assert_called_once()
        mock_get_notification_strategy.assert_called_once_with(mock_db, CaseType.KYB, company_profile_data.name)


@pytest.mark.asyncio
@patch("app.service.commands.handlers.uuid.uuid4")
@patch("app.service.commands.handlers.dispatch_event_to_projectors") # Keep other patches if events before notification are saved
@patch("app.service.commands.handlers.save_event")
async def test_handle_create_case_command_kafka_producer_error(
    mock_save_event: AsyncMock,
    mock_dispatch_event_to_projectors: AsyncMock,
    mock_uuid4: MagicMock,
    mock_event_store: EventStore,
    mock_kafka_producer: KafkaProducer,
    mock_notification_config_client: NotificationConfigClient,
    mock_db: AsyncMock,
):
    """
    Test handle_create_case_command when Kafka producer raises an error.
    Verifies KafkaProducerError is raised by the handler.
    Events prior to notification dispatch should still be saved.
    """
    case_id = uuid.uuid4()
    user_id = "test_user_kafka_error"
    mock_uuid4.return_value = case_id

    command = CreateCaseCommand(
        case_type=CaseType.KYC,
        created_by=user_id,
        persons=[{"person_id": uuid.uuid4(), "profile": PersonProfile(name="Test Person"), "role": Role.PRIMARY_CONTACT}],
        company_profile=None,
        beneficial_owners=None,
    )

    # Configure mock_kafka_producer to raise KafkaProducerError
    mock_kafka_producer.produce_message.side_effect = KafkaProducerError("Kafka test error")

    with patch("app.service.commands.handlers.get_kafka_producer", return_value=mock_kafka_producer), \
         patch("app.service.commands.handlers.get_notification_config_client", return_value=mock_notification_config_client), \
         patch("app.service.commands.handlers.get_notification_strategy", return_value=NotificationStrategy.SEND_ALL):

        with pytest.raises(KafkaProducerError, match="Kafka test error"):
            await handle_create_case_command(command, mock_event_store, mock_db)

        # Verify events up to the point of failure were saved and dispatched
        # CaseCreatedEvent and PersonAddedToCaseEvent should be saved
        # NotificationRequiredEvent should be saved (as it's generated before sending)

        assert any(isinstance(call.args[1], CaseCreatedEvent) for call in mock_save_event.call_args_list)
        assert any(isinstance(call.args[1], PersonAddedToCaseEvent) for call in mock_save_event.call_args_list)

        # The NotificationRequiredEvent IS created and saved before attempting to send.
        # The error happens when kafka_producer.produce_message is called.
        notification_event_call = next(
            (call for call in mock_save_event.call_args_list if isinstance(call.args[1], NotificationRequiredEvent)), None
        )
        assert notification_event_call is not None

        # Dispatch should have been called for these saved events
        # If NotificationRequiredEvent is saved before sending, then 3 calls, otherwise 2.
        # Based on current handler logic, NotificationRequiredEvent *is* saved.
        assert mock_dispatch_event_to_projectors.call_count == 3 # CaseCreated, PersonAdded, NotificationRequired
        assert mock_save_event.call_count == 3

        # Ensure produce_message was called, leading to the error
        mock_kafka_producer.produce_message.assert_called_once()


@pytest.mark.asyncio
@patch("app.service.commands.handlers.dispatch_event_to_projectors")
@patch("app.service.commands.handlers.save_event")
async def test_handle_determine_initial_document_requirements_strategy_returns_reqs(
    mock_save_event: AsyncMock,
    mock_dispatch_event_to_projectors: AsyncMock,
    mock_event_store: EventStore,
    mock_document_strategy: DocumentStrategy, # Use the fixture
    mock_db: AsyncMock,
):
    """
    Test handle_determine_initial_document_requirements when strategy returns requirements.
    Verifies DocumentRequirementDeterminedEvent(s) are generated, saved, and dispatched.
    """
    case_id = uuid.uuid4()
    user_id = "doc_test_user"
    case_type = CaseType.KYC
    # Assuming company_name might be None for KYC, or fetched if needed by strategy
    # For this test, let's assume the strategy doesn't strictly need it or it's handled
    # by get_document_strategy if it were to fetch case details.
    # The command itself doesn't carry it.
    country_code = "US"

    command = DetermineInitialDocumentRequirementsCommand(
        case_id=case_id,
        case_type=case_type,
        country_code=country_code,
        # company_name is not part of this command's direct fields
        created_by=user_id
    )

    doc_spec1_id = uuid.uuid4()
    doc_spec1 = DocumentSpecification(
        document_id=doc_spec1_id,
        document_type="PASSPORT",
        description="Valid Passport",
        country_code="US",
        required=True
    )
    doc_spec2_id = uuid.uuid4()
    doc_spec2 = DocumentSpecification(
        document_id=doc_spec2_id,
        document_type="UTILITY_BILL",
        description="Utility Bill for Address Proof",
        country_code="US",
        required=True
    )

    # Mock the concrete strategy's get_document_requirements method
    # The mock_document_strategy fixture is already an AsyncMock of DocumentStrategy
    mock_document_strategy.get_document_requirements.return_value = [doc_spec1, doc_spec2]

    with patch("app.service.commands.handlers.get_document_strategy", return_value=mock_document_strategy):
        await handle_determine_initial_document_requirements(command, mock_event_store, mock_db)

        assert mock_document_strategy.get_document_requirements.call_count == 1
        # call_args[0] is args, call_args[1] is kwargs.
        # The first arg to get_document_requirements is db, then case_type, country_code, (optional) company_name
        strategy_call_args = mock_document_strategy.get_document_requirements.call_args[0]
        assert strategy_call_args[0] == mock_db
        assert strategy_call_args[1] == case_type
        assert strategy_call_args[2] == country_code
        # Add assertion for company_name if it were passed and relevant

        # Assertions for DocumentRequirementDeterminedEvent (doc_spec1)
        doc_req1_event_call = next(
            call for call in mock_save_event.call_args_list
            if isinstance(call.args[1], DocumentRequirementDeterminedEvent) and call.args[1].payload["document_id"] == doc_spec1_id
        )
        doc_req1_event: DocumentRequirementDeterminedEvent = doc_req1_event_call.args[1]
        assert doc_req1_event.aggregate_id == case_id
        assert doc_req1_event.version == 1 # First event for this aggregate in this handler
        assert doc_req1_event.payload["document_id"] == doc_spec1_id
        assert doc_req1_event.payload["document_type"] == doc_spec1.document_type
        assert doc_req1_event.payload["description"] == doc_spec1.description
        assert doc_req1_event.payload["country_code"] == doc_spec1.country_code
        assert doc_req1_event.payload["status"] == DocumentStatus.PENDING_UPLOAD.value # Initial status
        assert doc_req1_event.payload["required_by_case_type"] == doc_spec1.required
        assert doc_req1_event.payload["determined_by"] == user_id

        # Assertions for DocumentRequirementDeterminedEvent (doc_spec2)
        doc_req2_event_call = next(
            call for call in mock_save_event.call_args_list
            if isinstance(call.args[1], DocumentRequirementDeterminedEvent) and call.args[1].payload["document_id"] == doc_spec2_id
        )
        doc_req2_event: DocumentRequirementDeterminedEvent = doc_req2_event_call.args[1]
        assert doc_req2_event.aggregate_id == case_id
        assert doc_req2_event.version == 2 # Second event
        assert doc_req2_event.payload["document_id"] == doc_spec2_id
        assert doc_req2_event.payload["document_type"] == doc_spec2.document_type
        assert doc_req2_event.payload["status"] == DocumentStatus.PENDING_UPLOAD.value

        assert mock_save_event.call_count == 2
        assert mock_dispatch_event_to_projectors.call_count == 2

        dispatch_calls = mock_dispatch_event_to_projectors.call_args_list
        saved_events = [call.args[1] for call in mock_save_event.call_args_list]
        for i, call in enumerate(dispatch_calls):
            assert call.args[0] == mock_db
            assert call.args[1] == saved_events[i]


@pytest.mark.asyncio
@patch("app.service.commands.handlers.dispatch_event_to_projectors")
@patch("app.service.commands.handlers.save_event")
@patch("app.service.commands.handlers.logger") # Patch logger
async def test_handle_determine_initial_document_requirements_no_reqs(
    mock_logger: MagicMock,
    mock_save_event: AsyncMock,
    mock_dispatch_event_to_projectors: AsyncMock,
    mock_event_store: EventStore,
    mock_document_strategy: DocumentStrategy,
    mock_db: AsyncMock,
):
    """
    Test handle_determine_initial_document_requirements when strategy returns no requirements.
    Verifies no DocumentRequirementDeterminedEvent are generated and logging occurs.
    """
    case_id = uuid.uuid4()
    user_id = "doc_test_user_no_reqs"
    case_type = CaseType.KYB
    country_code = "DE"
    company_name = "German Corp" # For KYB, company_name might be used by strategy

    command = DetermineInitialDocumentRequirementsCommand(
        case_id=case_id,
        case_type=case_type,
        country_code=country_code,
        company_name=company_name, # Pass it in command
        created_by=user_id
    )

    # Mock strategy to return an empty list
    mock_document_strategy.get_document_requirements.return_value = []

    with patch("app.service.commands.handlers.get_document_strategy", return_value=mock_document_strategy):
        await handle_determine_initial_document_requirements(command, mock_event_store, mock_db)

        # Verify strategy was called
        mock_document_strategy.get_document_requirements.assert_called_once_with(
            mock_db, case_type, country_code, company_name # Ensure company_name is passed
        )

        # Verify no events were saved or dispatched
        mock_save_event.assert_not_called()
        mock_dispatch_event_to_projectors.assert_not_called()

        # Verify logging
        mock_logger.info.assert_called_once_with(
            f"No initial document requirements determined for case {case_id} (type: {case_type.value}, country: {country_code}, company: {company_name})."
        )


@pytest.mark.asyncio
@patch("app.service.commands.handlers.dispatch_event_to_projectors")
@patch("app.service.commands.handlers.save_event")
@patch("app.service.commands.handlers.get_required_document_by_id") # Patch the DB query function
async def test_handle_update_document_status_success(
    mock_get_required_document_by_id: AsyncMock,
    mock_save_event: AsyncMock,
    mock_dispatch_event_to_projectors: AsyncMock,
    mock_event_store: EventStore,
    mock_db: AsyncMock,
):
    """
    Test handle_update_document_status when document is found and updated.
    Verifies DocumentStatusUpdatedEvent is generated, saved, and dispatched.
    """
    case_id = uuid.uuid4()
    document_id = uuid.uuid4()
    user_id = "doc_update_user"
    old_status = DocumentStatus.PENDING_UPLOAD
    new_status = DocumentStatus.APPROVED
    version = 2 # Assuming this document had a prior event, e.g., DocumentRequirementDeterminedEvent

    command = UpdateDocumentStatusCommand(
        case_id=case_id,
        document_id=document_id,
        status=new_status,
        updated_by=user_id,
        rejection_reason=None # Not rejected
    )

    # Mock the document returned by get_required_document_by_id
    # This mock needs to behave like a RequiredDocumentDB object
    mock_document_db = MagicMock(spec=RequiredDocumentDB)
    mock_document_db.id = document_id # Ensure it has an 'id' attribute if accessed by that name
    mock_document_db.document_id = document_id # Or 'document_id' if that's the attribute name used
    mock_document_db.case_id = case_id
    mock_document_db.status = old_status.value # The DB stores the enum's value
    mock_document_db.version = version -1 # Version before this update
    mock_document_db.document_type = "PASSPORT" # Example data
    # Add other fields if they are used in the event payload derivation

    mock_get_required_document_by_id.return_value = mock_document_db

    await handle_update_document_status(command, mock_event_store, mock_db)

    # Verify get_required_document_by_id was called correctly
    mock_get_required_document_by_id.assert_called_once_with(mock_db, str(document_id))

    # Assertions for DocumentStatusUpdatedEvent
    assert mock_save_event.call_count == 1
    saved_event_call = mock_save_event.call_args_list[0]
    assert isinstance(saved_event_call.args[1], DocumentStatusUpdatedEvent)

    event: DocumentStatusUpdatedEvent = saved_event_call.args[1]
    assert event.aggregate_id == case_id # Assuming case_id is the aggregate for document events
    assert event.version == version # Incremented version
    assert event.payload["document_id"] == document_id
    assert event.payload["old_status"] == old_status.value
    assert event.payload["new_status"] == new_status.value
    assert event.payload["updated_by"] == user_id
    assert event.payload["rejection_reason"] is None
    # Example of checking other data copied from DB if applicable
    # assert event.payload["document_type"] == mock_document_db.document_type

    # Assertions for dispatch_event_to_projectors
    assert mock_dispatch_event_to_projectors.call_count == 1
    dispatch_call = mock_dispatch_event_to_projectors.call_args_list[0]
    assert dispatch_call.args[0] == mock_db
    assert dispatch_call.args[1] == event


@pytest.mark.asyncio
@patch("app.service.commands.handlers.dispatch_event_to_projectors") # Still need to patch these as they are global
@patch("app.service.commands.handlers.save_event")
@patch("app.service.commands.handlers.get_required_document_by_id")
async def test_handle_update_document_status_not_found(
    mock_get_required_document_by_id: AsyncMock,
    mock_save_event: AsyncMock,
    mock_dispatch_event_to_projectors: AsyncMock,
    mock_event_store: EventStore,
    mock_db: AsyncMock,
):
    """
    Test handle_update_document_status when document is not found.
    Verifies DocumentNotFoundError is raised and no event is generated or saved.
    """
    case_id = uuid.uuid4()
    document_id = uuid.uuid4() # Non-existent document
    user_id = "doc_update_user_not_found"
    new_status = DocumentStatus.APPROVED

    command = UpdateDocumentStatusCommand(
        case_id=case_id,
        document_id=document_id,
        status=new_status,
        updated_by=user_id,
    )

    # Mock get_required_document_by_id to return None (document not found)
    mock_get_required_document_by_id.return_value = None

    with pytest.raises(DocumentNotFoundError, match=f"Required document with ID {document_id} not found for case {case_id}"):
        await handle_update_document_status(command, mock_event_store, mock_db)

    # Verify get_required_document_by_id was called
    mock_get_required_document_by_id.assert_called_once_with(mock_db, str(document_id))

    # Verify no event was saved or dispatched
    mock_save_event.assert_not_called()
    mock_dispatch_event_to_projectors.assert_not_called()
