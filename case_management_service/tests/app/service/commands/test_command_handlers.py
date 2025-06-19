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


# --- Refactoring Fixtures ---

@pytest.fixture
def kyc_create_case_command_payload_factory():
    def _factory(created_by: str = "test_user", num_persons: int = 1) -> CreateCaseCommand:
        persons_data = []
        for i in range(num_persons):
            person_id = uuid.uuid4()
            profile = PersonProfile(name=f"Person {i+1}", email=f"person{i+1}@example.com")
            role = Role.PRIMARY_CONTACT if i == 0 else Role.ADDITIONAL_CONTACT
            persons_data.append({"person_id": person_id, "profile": profile, "role": role})

        return CreateCaseCommand(
            case_type=CaseType.KYC,
            created_by=created_by,
            persons=persons_data,
            company_profile=None,
            beneficial_owners=None,
        )
    return _factory

@pytest.fixture
def kyb_create_case_command_payload_factory():
    def _factory(
        created_by: str = "test_user_kyb",
        include_company: bool = True,
        num_persons: int = 0, # Persons linked to company
        num_bos: int = 0
    ) -> CreateCaseCommand:
        company_profile_data = None
        company_id = None
        if include_company:
            company_id = uuid.uuid4()
            company_profile = CompanyProfile(name="Test Corp Inc.", registration_number="KYB123")
            company_profile_data = {"company_id": company_id, "profile": company_profile}

        persons_data = []
        for i in range(num_persons):
            person_id = uuid.uuid4()
            profile = PersonProfile(name=f"Director {i+1}", email=f"director{i+1}@corp.com")
            # Role for KYB persons is role_in_company, not just 'role'
            persons_data.append({"person_id": person_id, "profile": profile, "role_in_company": Role.DIRECTOR})
                                # Note: The CreateCaseCommand might use 'role' for this field, adjust if needed based on model

        bos_data = []
        for i in range(num_bos):
            bo_id = uuid.uuid4()
            profile = PersonProfile(name=f"Owner {i+1}", email=f"owner{i+1}@corp.com")
            bos_data.append({"bo_id": bo_id, "profile": profile, "ownership_percentage": 50.0 / (num_bos or 1)})

        return CreateCaseCommand(
            case_type=CaseType.KYB,
            created_by=created_by,
            company_profile=company_profile_data,
            persons=persons_data, # These are persons linked to company
            beneficial_owners=bos_data,
        )
    return _factory

@pytest.fixture
def mock_command_handler_dependencies(mocker): # Using pytest-mock 'mocker' fixture
    """Mocks common dependencies for command handlers."""
    mocks = {
        "save_event": mocker.patch("app.service.commands.handlers.save_event", new_callable=AsyncMock),
        "dispatch_event_to_projectors": mocker.patch("app.service.commands.handlers.dispatch_event_to_projectors", new_callable=AsyncMock),
        "get_kafka_producer": mocker.patch("app.service.commands.handlers.get_kafka_producer", new_callable=AsyncMock),
        "get_notification_config_client": mocker.patch("app.service.commands.handlers.get_notification_config_client", new_callable=AsyncMock),
        "get_document_strategy": mocker.patch("app.service.commands.handlers.get_document_strategy", new_callable=AsyncMock),
        "uuid4": mocker.patch("app.service.commands.handlers.uuid.uuid4"), # Standard mock for uuid4
        "get_required_document_by_id": mocker.patch("app.service.commands.handlers.get_required_document_by_id", new_callable=AsyncMock),
        "logger": mocker.patch("app.service.commands.handlers.logger"), # Standard mock for logger
    }

    # Configure default return values for producer and clients
    mock_kafka_prod_instance = AsyncMock(spec=KafkaProducer)
    mock_kafka_prod_instance.produce_message = AsyncMock()
    mocks["get_kafka_producer"].return_value = mock_kafka_prod_instance
    mocks["kafka_producer_instance"] = mock_kafka_prod_instance # For direct assertion on produce_message

    mock_notif_client_instance = AsyncMock(spec=NotificationConfigClient)
    # Default strategy, can be overridden in tests
    mock_notif_client_instance.get_notification_strategy = AsyncMock(return_value=NotificationStrategy.SEND_ALL)
    mocks["get_notification_config_client"].return_value = mock_notif_client_instance
    mocks["notification_config_client_instance"] = mock_notif_client_instance # For direct assertion

    mock_doc_strategy_instance = AsyncMock(spec=DocumentStrategy)
    mock_doc_strategy_instance.get_document_requirements = AsyncMock(return_value=[]) # Default empty list
    mocks["get_document_strategy"].return_value = mock_doc_strategy_instance
    mocks["document_strategy_instance"] = mock_doc_strategy_instance

    # Allow specific configuration of uuid4 if needed, e.g., side_effect for multiple UUIDs
    mocks["uuid4"].return_value = uuid.uuid4() # Default single UUID

    yield mocks


# Refactored tests for handle_create_case_command

@pytest.mark.asyncio
async def test_handle_create_case_command_kyc_valid_refactored(
    mock_command_handler_dependencies, # Centralized mocks
    kyc_create_case_command_payload_factory, # Payload factory
    mock_event_store: EventStore, # Still needed for passing to handler
    mock_db: AsyncMock,
):
    mocks = mock_command_handler_dependencies
    case_id = uuid.uuid4()
    mocks["uuid4"].return_value = case_id # Control the generated case_id

    # Use the factory to create command payload
    # Assuming the factory generates person_ids and profiles internally
    command = kyc_create_case_command_payload_factory(user_id="test_user_kyc_valid", num_persons=2)

    # Specific mock configurations for this test if needed (e.g., notification strategy)
    # mocks["notification_config_client_instance"].get_notification_strategy.return_value = NotificationStrategy.SEND_ALL (already default)

    await handle_create_case_command(command, mock_event_store, mock_db)

    # Assertions
    # CaseCreatedEvent
    case_created_event_call = next(
        call for call in mocks["save_event"].call_args_list if isinstance(call.args[1], CaseCreatedEvent)
    )
    case_created_event: CaseCreatedEvent = case_created_event_call.args[1]
    assert case_created_event.aggregate_id == case_id
    assert case_created_event.version == 1
    assert case_created_event.payload["case_type"] == command.case_type.value
    assert case_created_event.payload["created_by"] == command.created_by

    # PersonAddedToCaseEvents (example for the first person)
    # Need to access person_id from the command generated by factory
    person1_id = command.persons[0]["person_id"]
    person1_profile = command.persons[0]["profile"]
    person1_added_event_call = next(
        call for call in mocks["save_event"].call_args_list
        if isinstance(call.args[1], PersonAddedToCaseEvent) and call.args[1].payload["person_id"] == person1_id
    )
    person1_added_event: PersonAddedToCaseEvent = person1_added_event_call.args[1]
    assert person1_added_event.aggregate_id == case_id
    assert person1_added_event.version == 2
    assert person1_added_event.payload["profile"] == person1_profile.model_dump()
    assert person1_added_event.payload["role"] == command.persons[0]["role"].value

    # NotificationRequiredEvent
    notification_event_call = next(
        (call for call in mocks["save_event"].call_args_list if isinstance(call.args[1], NotificationRequiredEvent)), None
    )
    assert notification_event_call is not None
    # Further checks on notification content...
    mocks["kafka_producer_instance"].produce_message.assert_called_once()
    # Further checks on kafka call args...

    # Dispatch calls
    assert mocks["dispatch_event_to_projectors"].call_count == mocks["save_event"].call_count
    # Further checks on dispatch calls...

    expected_save_calls = 1 + len(command.persons) + (1 if notification_event_call else 0)
    assert mocks["save_event"].call_count == expected_save_calls


@pytest.mark.asyncio
async def test_handle_create_case_command_kyb_full_valid_refactored(
    mock_command_handler_dependencies,
    kyb_create_case_command_payload_factory,
    mock_event_store: EventStore,
    mock_db: AsyncMock,
):
    mocks = mock_command_handler_dependencies
    case_id = uuid.uuid4()
    company_id_in_command = uuid.uuid4() # This will be part of the command from factory

    # Configure uuid4 to return case_id first, then other generated IDs if the handler makes more uuid4 calls
    # The factory also calls uuid4, so careful management is needed if asserting all generated IDs.
    # For simplicity, let's assume the factory generates its own internal IDs for persons/BOs
    # and we control the main case_id and potentially company_id if handler generates it.
    # If company_id in command is used by handler, no need to mock it here for that.
    # If handler generates company_id if not provided, then mock side_effect:
    # mocks["uuid4"].side_effect = [case_id, generated_company_id_if_any, ...]
    mocks["uuid4"].return_value = case_id # For the CaseCreatedEvent aggregate_id

    command = kyb_create_case_command_payload_factory(
        created_by="test_user_kyb_full",
        include_company=True,
        num_persons=1, # e.g., a director
        num_bos=1      # e.g., one BO
    )
    # Override the company_id in the command to use the one we want to assert against for company events
    # The factory already creates a company_id if include_company is True.
    company_id_from_factory = command.company_profile["company_id"]


    await handle_create_case_command(command, mock_event_store, mock_db)

    # CompanyProfileCreatedEvent
    company_created_call = next(c for c in mocks["save_event"].call_args_list if isinstance(c.args[1], CompanyProfileCreatedEvent))
    company_event: CompanyProfileCreatedEvent = company_created_call.args[1]
    assert company_event.aggregate_id == company_id_from_factory
    assert company_event.version == 1
    assert company_event.payload["profile"] == command.company_profile["profile"].model_dump()

    # PersonLinkedToCompanyEvent
    person_linked_call = next(c for c in mocks["save_event"].call_args_list if isinstance(c.args[1], PersonLinkedToCompanyEvent))
    person_linked_event: PersonLinkedToCompanyEvent = person_linked_call.args[1]
    assert person_linked_event.aggregate_id == company_id_from_factory
    assert person_linked_event.version == 2 # Assuming this order
    assert person_linked_event.payload["person_id"] == command.persons[0]["person_id"]

    # BeneficialOwnerAddedEvent
    bo_added_call = next(c for c in mocks["save_event"].call_args_list if isinstance(c.args[1], BeneficialOwnerAddedEvent))
    bo_event: BeneficialOwnerAddedEvent = bo_added_call.args[1]
    assert bo_event.aggregate_id == company_id_from_factory
    assert bo_event.version == 3 # Assuming this order
    assert bo_event.payload["bo_id"] == command.beneficial_owners[0]["bo_id"]

    # CaseCreatedEvent
    case_created_call = next(c for c in mocks["save_event"].call_args_list if isinstance(c.args[1], CaseCreatedEvent))
    case_event: CaseCreatedEvent = case_created_call.args[1]
    assert case_event.aggregate_id == case_id # This should be the case_id from mock_uuid4
    assert case_event.version == 1
    assert case_event.payload["company_id"] == company_id_from_factory

    # Notification and Dispatch checks (similar to KYC)
    # ...
    expected_event_count = 1 + 1 + 1 + 1 + 1 # Company, PersonLink, BO, Case, Notification
    assert mocks["save_event"].call_count == expected_event_count
    assert mocks["dispatch_event_to_projectors"].call_count == expected_event_count
    mocks["kafka_producer_instance"].produce_message.assert_called_once()


@pytest.mark.asyncio
async def test_handle_create_case_command_kyb_minimal_company_only_refactored(
    mock_command_handler_dependencies,
    kyb_create_case_command_payload_factory,
    mock_event_store, mock_db
):
    mocks = mock_command_handler_dependencies
    case_id = uuid.uuid4()
    mocks["uuid4"].return_value = case_id

    command = kyb_create_case_command_payload_factory(include_company=True, num_persons=0, num_bos=0)
    company_id_from_factory = command.company_profile["company_id"]

    await handle_create_case_command(command, mock_event_store, mock_db)

    # CompanyProfileCreatedEvent
    company_created_call = next(c for c in mocks["save_event"].call_args_list if isinstance(c.args[1], CompanyProfileCreatedEvent))
    assert company_created_call.args[1].aggregate_id == company_id_from_factory

    # CaseCreatedEvent
    case_created_call = next(c for c in mocks["save_event"].call_args_list if isinstance(c.args[1], CaseCreatedEvent))
    assert case_created_call.args[1].aggregate_id == case_id
    assert case_created_call.args[1].payload["company_id"] == company_id_from_factory

    assert not any(isinstance(call.args[1], PersonLinkedToCompanyEvent) for call in mocks["save_event"].call_args_list)
    assert not any(isinstance(call.args[1], BeneficialOwnerAddedEvent) for call in mocks["save_event"].call_args_list)

    assert mocks["save_event"].call_count == 3 # CompanyProfile, CaseCreated, NotificationRequired
    mocks["kafka_producer_instance"].produce_message.assert_called_once()


@pytest.mark.asyncio
async def test_handle_create_case_command_kyb_no_company_profile_refactored(
    mock_command_handler_dependencies,
    kyb_create_case_command_payload_factory, # Factory will be used
    mock_event_store, mock_db
):
    mocks = mock_command_handler_dependencies
    case_id = uuid.uuid4()
    mocks["uuid4"].return_value = case_id

    # Use factory, but specify no company
    command = kyb_create_case_command_payload_factory(include_company=False)

    await handle_create_case_command(command, mock_event_store, mock_db)

    case_created_call = next(c for c in mocks["save_event"].call_args_list if isinstance(c.args[1], CaseCreatedEvent))
    case_event: CaseCreatedEvent = case_created_call.args[1]
    assert case_event.aggregate_id == case_id
    assert "company_id" not in case_event.payload

    mocks["logger"].warning.assert_called_once_with(
        f"KYB case {case_id} created without company profile information."
    )
    assert not any(isinstance(call.args[1], CompanyProfileCreatedEvent) for call in mocks["save_event"].call_args_list)
    assert mocks["save_event"].call_count == 2 # CaseCreated, NotificationRequired


@pytest.mark.asyncio
async def test_handle_create_case_command_kyc_no_persons_refactored(
    mock_command_handler_dependencies,
    kyc_create_case_command_payload_factory,
    mock_event_store, mock_db
):
    mocks = mock_command_handler_dependencies
    case_id = uuid.uuid4()
    mocks["uuid4"].return_value = case_id

    command = kyc_create_case_command_payload_factory(num_persons=0)

    await handle_create_case_command(command, mock_event_store, mock_db)

    case_created_call = next(c for c in mocks["save_event"].call_args_list if isinstance(c.args[1], CaseCreatedEvent))
    assert case_created_call.args[1].aggregate_id == case_id

    mocks["logger"].warning.assert_any_call(
        f"Case {case_id} of type KYC created without any persons."
    )
    assert not any(isinstance(call.args[1], PersonAddedToCaseEvent) for call in mocks["save_event"].call_args_list)
    assert mocks["save_event"].call_count == 2 # CaseCreated, NotificationRequired


@pytest.mark.asyncio
async def test_handle_create_case_command_kyb_no_persons_no_bos_refactored(
    mock_command_handler_dependencies,
    kyb_create_case_command_payload_factory,
    mock_event_store, mock_db
):
    mocks = mock_command_handler_dependencies
    case_id = uuid.uuid4()
    mocks["uuid4"].return_value = case_id # For Case ID

    # Factory creates company by default, but no persons/BOs
    command = kyb_create_case_command_payload_factory(num_persons=0, num_bos=0)
    company_id_from_factory = command.company_profile["company_id"]


    await handle_create_case_command(command, mock_event_store, mock_db)

    # CompanyProfileCreatedEvent should exist
    company_created_call = next(c for c in mocks["save_event"].call_args_list if isinstance(c.args[1], CompanyProfileCreatedEvent))
    assert company_created_call.args[1].aggregate_id == company_id_from_factory

    # CaseCreatedEvent should exist and link to company
    case_created_call = next(c for c in mocks["save_event"].call_args_list if isinstance(c.args[1], CaseCreatedEvent))
    case_event: CaseCreatedEvent = case_created_call.args[1]
    assert case_event.aggregate_id == case_id
    assert case_event.payload["company_id"] == company_id_from_factory

    mocks["logger"].warning.assert_any_call(
        f"KYB case {case_id} for company {company_id_from_factory} created without any linked persons."
    )
    mocks["logger"].warning.assert_any_call(
        f"KYB case {case_id} for company {company_id_from_factory} created without any beneficial owners."
    )

    assert not any(isinstance(call.args[1], PersonLinkedToCompanyEvent) for call in mocks["save_event"].call_args_list)
    assert not any(isinstance(call.args[1], BeneficialOwnerAddedEvent) for call in mocks["save_event"].call_args_list)
    assert mocks["save_event"].call_count == 3 # Company, Case, Notification


@pytest.mark.asyncio
async def test_handle_create_case_command_kafka_producer_error_refactored(
    mock_command_handler_dependencies,
    kyc_create_case_command_payload_factory,
    mock_event_store, mock_db
):
    mocks = mock_command_handler_dependencies
    case_id = uuid.uuid4()
    mocks["uuid4"].return_value = case_id

    command = kyc_create_case_command_payload_factory(num_persons=1)

    # Configure Kafka producer to raise an error
    mocks["kafka_producer_instance"].produce_message.side_effect = KafkaProducerError("Kafka test error refactored")

    with pytest.raises(KafkaProducerError, match="Kafka test error refactored"):
        await handle_create_case_command(command, mock_event_store, mock_db)

    # Events up to notification attempt should be saved
    assert any(isinstance(call.args[1], CaseCreatedEvent) for call in mocks["save_event"].call_args_list)
    assert any(isinstance(call.args[1], PersonAddedToCaseEvent) for call in mocks["save_event"].call_args_list)
    # NotificationRequiredEvent is saved before sending
    assert any(isinstance(call.args[1], NotificationRequiredEvent) for call in mocks["save_event"].call_args_list)

    assert mocks["save_event"].call_count == 3 # Case, Person, NotificationRequired
    assert mocks["dispatch_event_to_projectors"].call_count == 3
    mocks["kafka_producer_instance"].produce_message.assert_called_once()



@pytest.mark.asyncio
async def test_handle_determine_initial_document_requirements_strategy_returns_reqs_refactored(
    mock_command_handler_dependencies,
    mock_event_store: EventStore,
    mock_db: AsyncMock,
):
    mocks = mock_command_handler_dependencies
    case_id = uuid.uuid4()
    user_id = "doc_test_user"
    case_type = CaseType.KYC
    country_code = "US"

    command = DetermineInitialDocumentRequirementsCommand(
        case_id=case_id, case_type=case_type, country_code=country_code, created_by=user_id
    )

    doc_spec1_id = uuid.uuid4()
    doc_spec1 = DocumentSpecification(document_id=doc_spec1_id, document_type="PASSPORT", description="Valid Passport", country_code="US", required=True)
    doc_spec2_id = uuid.uuid4()
    doc_spec2 = DocumentSpecification(document_id=doc_spec2_id, document_type="UTILITY_BILL", description="Utility Bill", country_code="US", required=True)

    # Configure the document_strategy_instance from the central fixture
    mocks["document_strategy_instance"].get_document_requirements.return_value = [doc_spec1, doc_spec2]

    await handle_determine_initial_document_requirements(command, mock_event_store, mock_db)

    # Assert strategy was called correctly (via the mock provided by the fixture)
    mocks["document_strategy_instance"].get_document_requirements.assert_called_once_with(
        mock_db, case_type, country_code, command.company_name
    )

    # Assertions for DocumentRequirementDeterminedEvent (doc_spec1)
    doc_req1_event_call = next(
        call for call in mocks["save_event"].call_args_list
        if isinstance(call.args[1], DocumentRequirementDeterminedEvent) and call.args[1].payload["document_id"] == doc_spec1_id
    )
    doc_req1_event: DocumentRequirementDeterminedEvent = doc_req1_event_call.args[1]
    assert doc_req1_event.aggregate_id == case_id
    assert doc_req1_event.version == 1
    assert doc_req1_event.payload["document_id"] == doc_spec1_id
    # ... other assertions for doc_req1_event ...

    # Assertions for DocumentRequirementDeterminedEvent (doc_spec2)
    doc_req2_event_call = next(
        call for call in mocks["save_event"].call_args_list
        if isinstance(call.args[1], DocumentRequirementDeterminedEvent) and call.args[1].payload["document_id"] == doc_spec2_id
    )
    # ... assertions for doc_req2_event ...

    assert mocks["save_event"].call_count == 2
    assert mocks["dispatch_event_to_projectors"].call_count == 2
    # ... further dispatch checks ...


@pytest.mark.asyncio
async def test_handle_determine_initial_document_requirements_no_reqs_refactored(
    mock_command_handler_dependencies,
    mock_event_store: EventStore,
    mock_db: AsyncMock,
):
    mocks = mock_command_handler_dependencies
    case_id = uuid.uuid4()
    user_id = "doc_test_user_no_reqs"
    case_type = CaseType.KYB
    country_code = "DE"
    company_name = "German Corp"

    command = DetermineInitialDocumentRequirementsCommand(
        case_id=case_id, case_type=case_type, country_code=country_code,
        company_name=company_name, created_by=user_id
    )

    # Configure the document_strategy_instance to return empty list
    mocks["document_strategy_instance"].get_document_requirements.return_value = []

    await handle_determine_initial_document_requirements(command, mock_event_store, mock_db)

    mocks["document_strategy_instance"].get_document_requirements.assert_called_once_with(
        mock_db, case_type, country_code, company_name
    )
    mocks["save_event"].assert_not_called()
    mocks["dispatch_event_to_projectors"].assert_not_called()
    mocks["logger"].info.assert_called_once_with(
        f"No initial document requirements determined for case {case_id} (type: {case_type.value}, country: {country_code}, company: {company_name})."
    )


@pytest.mark.asyncio
async def test_handle_update_document_status_success_refactored(
    mock_command_handler_dependencies,
    mock_event_store: EventStore,
    mock_db: AsyncMock,
):
    mocks = mock_command_handler_dependencies
    case_id = uuid.uuid4()
    document_id = uuid.uuid4()
    user_id = "doc_update_user"
    old_status = DocumentStatus.PENDING_UPLOAD
    new_status = DocumentStatus.APPROVED
    expected_event_version = 2

    command = UpdateDocumentStatusCommand(
        case_id=case_id, document_id=document_id, status=new_status, updated_by=user_id
    )

    mock_document_db_obj = MagicMock(spec=RequiredDocumentDB)
    mock_document_db_obj.document_id = document_id
    mock_document_db_obj.case_id = case_id
    mock_document_db_obj.status = old_status.value
    mock_document_db_obj.version = expected_event_version - 1
    # ... set other attributes on mock_document_db_obj if needed for payload ...

    mocks["get_required_document_by_id"].return_value = mock_document_db_obj

    await handle_update_document_status(command, mock_event_store, mock_db)

    mocks["get_required_document_by_id"].assert_called_once_with(mock_db, str(document_id))

    assert mocks["save_event"].call_count == 1
    saved_event_call = mocks["save_event"].call_args_list[0]
    assert isinstance(saved_event_call.args[1], DocumentStatusUpdatedEvent)

    event: DocumentStatusUpdatedEvent = saved_event_call.args[1]
    assert event.aggregate_id == case_id
    assert event.version == expected_event_version
    assert event.payload["document_id"] == document_id
    assert event.payload["old_status"] == old_status.value
    assert event.payload["new_status"] == new_status.value
    # ... other payload assertions ...

    assert mocks["dispatch_event_to_projectors"].call_count == 1
    # ... dispatch assertions ...


@pytest.mark.asyncio
async def test_handle_update_document_status_not_found_refactored(
    mock_command_handler_dependencies,
    mock_event_store: EventStore,
    mock_db: AsyncMock,
):
    mocks = mock_command_handler_dependencies
    case_id = uuid.uuid4()
    document_id = uuid.uuid4()
    user_id = "doc_update_user_not_found"

    command = UpdateDocumentStatusCommand(
        case_id=case_id, document_id=document_id, status=DocumentStatus.APPROVED, updated_by=user_id
    )

    mocks["get_required_document_by_id"].return_value = None # Simulate document not found

    with pytest.raises(DocumentNotFoundError, match=f"Required document with ID {document_id} not found for case {case_id}"):
        await handle_update_document_status(command, mock_event_store, mock_db)

    mocks["get_required_document_by_id"].assert_called_once_with(mock_db, str(document_id))
    mocks["save_event"].assert_not_called()
    mocks["dispatch_event_to_projectors"].assert_not_called()
