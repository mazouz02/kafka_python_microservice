import pytest
import uuid
import json
from unittest.mock import patch, MagicMock, ANY, AsyncMock

from fastapi.testclient import TestClient
from mongomock import MongoClient as MongoMockClient

from app.main import app
from app.api.dependencies import get_db
from app.config import settings
from app.service.models import CaseType, Role, PersonProfile
from app.service.events.events import NotificationRequiredEvent # For payload verification

# Path to the Producer class as used by KafkaProducerService
# Adjust if your KafkaProducerService instantiates it differently,
# e.g., if it's from a different module or aliased.
CONFLUENT_KAFKA_PRODUCER_PATH = "app.infrastructure.kafka.kafka_producer.Producer"


@pytest.fixture(scope="function")
def test_db_session_for_kafka_tests():
    """Provides a mongomock database session, clearing critical collections."""
    client = MongoMockClient()
    db = client[settings.MONGODB_DATABASE_NAME]
    db[settings.EVENT_STORE_COLLECTION_NAME].delete_many({})
    db[settings.CASES_READ_MODEL_COLLECTION_NAME].delete_many({})
    # Add other collections if case creation touches them and they need to be clean
    yield db
    client.close()


@pytest.fixture(scope="function")
def mock_confluent_producer():
    """Mocks confluent_kafka.Producer and returns the mock instance."""
    with patch(CONFLUENT_KAFKA_PRODUCER_PATH, autospec=True) as mock_producer_class:
        mock_producer_instance = mock_producer_class.return_value
        mock_producer_instance.produce = MagicMock()
        # If your producer service calls poll or flush, mock them:
        mock_producer_instance.poll = MagicMock(return_value=0)
        mock_producer_instance.flush = MagicMock()
        yield mock_producer_instance


@pytest.fixture(scope="function")
def test_client_with_db_and_kafka_mocks(
    test_db_session_for_kafka_tests: MongoMockClient,
    mock_confluent_producer: MagicMock # This fixture ensures Producer is mocked
):
    """
    Provides a TestClient with get_db overridden for mongomock
    and Kafka Producer mocked.
    """
    app.dependency_overrides[get_db] = lambda: test_db_session_for_kafka_tests

    # Mock other external services if necessary for the command handler to succeed
    # Reusing parts of mock_external_services from other integration tests:
    with patch("app.service.commands.handlers.get_notification_config_client", new_callable=AsyncMock) as mock_get_notif_client:
        mock_notif_client_instance = AsyncMock()
        mock_notif_client_instance.get_notification_strategy = AsyncMock(return_value="SEND_ALL") # Or relevant strategy
        mock_get_notif_client.return_value = mock_notif_client_instance

        # The get_kafka_producer in command_handlers returns an instance of KafkaProducerService.
        # KafkaProducerService internally uses the confluent_kafka.Producer (which is already mocked by mock_confluent_producer).
        # So, we don't need to mock get_kafka_producer itself, but ensure the underlying confluent Producer is the mock.

        yield TestClient(app)

    app.dependency_overrides = {} # Clear overrides


def test_create_case_publishes_notification_event(
    test_client_with_db_and_kafka_mocks: TestClient, # This client uses the mocked DB and Kafka
    mock_confluent_producer: MagicMock, # Get the instance of the mocked Kafka producer
    test_db_session_for_kafka_tests: MongoMockClient # For any direct DB checks if needed
):
    # 1. Prepare Command Payload
    user_id = "kafka_test_user"
    person1_id = str(uuid.uuid4())
    person1_profile = PersonProfile(name="Kafka Test User", email="kafka.user@example.com")

    create_case_payload = {
        "case_type": CaseType.KYC.value,
        "created_by": user_id,
        "persons": [{
            "person_id": person1_id,
            "profile": person1_profile.model_dump(),
            "role": Role.PRIMARY_CONTACT.value
        }]
    }

    # 2. Action: Make POST request to create a case
    response = test_client_with_db_and_kafka_mocks.post("/api/v1/cases", json=create_case_payload)

    # 3. Assertions
    # API Response
    assert response.status_code == 202
    response_data = response.json()
    assert "case_id" in response_data
    case_id = response_data["case_id"]

    # Kafka Producer Mock Verification
    mock_confluent_producer.produce.assert_called_once()

    call_args = mock_confluent_producer.produce.call_args
    assert call_args is not None

    # topic = call_args[0][0] # First positional argument
    # OR if called with kwargs:
    topic = call_args.kwargs.get("topic")
    key = call_args.kwargs.get("key")
    value_str = call_args.kwargs.get("value")

    assert topic == settings.KAFKA_NOTIFICATIONS_TOPIC

    # Key should be JSON string of {"case_id": "actual_case_id"}
    assert key is not None
    key_data = json.loads(key)
    assert key_data == {"case_id": case_id}

    assert value_str is not None
    message_payload = json.loads(value_str) # The producer service likely sends a JSON string

    # Verify structure of the message payload (NotificationRequiredEventPayload)
    # This assumes NotificationRequiredEvent is the structure sent.
    # The actual event payload might be nested if the full event object is serialized.
    # Based on handle_create_case_command, it's likely NotificationRequiredEvent's payload.
    assert message_payload["case_id"] == case_id
    assert message_payload["notification_type"] == "CASE_CREATED" # As per NotificationRequiredEvent
    assert "recipient_user_id" in message_payload # Check for presence of key fields
    assert "message_template_id" in message_payload
    assert "context_data" in message_payload
    assert message_payload["context_data"]["case_id"] == case_id
    assert message_payload["context_data"]["case_type"] == CaseType.KYC.value

    # Optional: verify poll or flush calls if your producer uses them
    # mock_confluent_producer.poll.assert_called_with(0)
    # mock_confluent_producer.flush.assert_called_once()

    # Also verify that NotificationRequiredEvent was stored in EventStore (optional for this specific test's focus)
    event_store_collection = test_db_session_for_kafka_tests[settings.EVENT_STORE_COLLECTION_NAME]
    notification_event_doc = event_store_collection.find_one({
        "aggregate_id": case_id,
        "event_type": NotificationRequiredEvent.__name__
    })
    assert notification_event_doc is not None
    assert notification_event_doc["payload"]["case_id"] == case_id
    assert notification_event_doc["payload"]["notification_type"] == "CASE_CREATED"


# --- Kafka Consumer Tests ---

# Path to the Consumer class and dispatch_command function
# Adjust if your consumer/dispatcher are structured differently
CONFLUENT_KAFKA_CONSUMER_PATH = "app.infrastructure.kafka.consumer.Consumer"
DISPATCH_COMMAND_PATH = "app.infrastructure.kafka.consumer.dispatch_command" # Assuming dispatch_command is in this module
KAFKA_CONSUMER_LOOP_PATH = "app.infrastructure.kafka.consumer.consume_kafka_events" # Path to the main consumer loop function

@pytest.fixture(scope="function")
def mock_confluent_consumer_for_poll():
    """Mocks confluent_kafka.Consumer for testing poll behavior."""
    with patch(CONFLUENT_KAFKA_CONSUMER_PATH, autospec=True) as mock_consumer_class:
        mock_consumer_instance = mock_consumer_class.return_value
        mock_consumer_instance.subscribe = MagicMock()
        mock_consumer_instance.poll = MagicMock() # This will be configured per test
        mock_consumer_instance.commit = MagicMock()
        mock_consumer_instance.close = MagicMock()
        yield mock_consumer_instance


@patch(DISPATCH_COMMAND_PATH, new_callable=AsyncMock) # Mock the command dispatcher
async def test_kafka_consumer_processes_message_and_dispatches_command(
    mock_dispatch_command: AsyncMock,
    mock_confluent_consumer_for_poll: MagicMock, # Use the consumer mock that allows poll configuration
    test_db_session_for_kafka_tests: MongoMockClient, # DB session for consumer context if needed by dispatch
    # test_client_with_db_and_kafka_mocks # Not strictly needed if we directly run consumer logic
):
    # 1. Setup Kafka Message
    # Example: Consumer expects a message that should trigger a CreateCaseCommand
    # This payload should match what your Kafka message *value* would contain.
    case_id_from_kafka = str(uuid.uuid4())
    user_id_from_kafka = "kafka_consumed_user"
    # This is the *content* of the Kafka message. The actual command object will be built by the consumer.
    kafka_message_payload = {
        "command_type": "CreateCaseCommand", # Used by consumer to know what command to build
        "payload": { # This is the CreateCaseCommand's payload
            "case_type": CaseType.KYC.value,
            "created_by": user_id_from_kafka,
            "persons": [{
                "person_id": str(uuid.uuid4()),
                "profile": {"name": "Consumed Person", "email": "consumed@example.com"},
                "role": Role.PRIMARY_CONTACT.value
            }],
            # Assuming the message might directly suggest a case_id for idempotency or specific scenarios
            # If not, the command handler would generate it.
            # For this test, let's assume the consumer can pass it to the command if present.
            # The CreateCaseCommand model itself doesn't have case_id. It's generated.
            # So, this specific kafka_message_payload might be simplified if case_id isn't part of it.
        }
    }

    mock_kafka_message = MagicMock()
    mock_kafka_message.value.return_value = json.dumps(kafka_message_payload).encode('utf-8')
    mock_kafka_message.error.return_value = None # No error
    mock_kafka_message.topic.return_value = "test_commands_topic"
    mock_kafka_message.partition.return_value = 0
    mock_kafka_message.offset.return_value = 100

    # Configure mock_confluent_consumer.poll to return this message once, then an error/None to stop
    # A common way to stop a consumer loop in tests is to raise an exception like KeyboardInterrupt
    # or have poll return None or a message with an error after the first valid message.
    mock_confluent_consumer_for_poll.poll.side_effect = [mock_kafka_message, KeyboardInterrupt("Stopping test consumer")]

    # 2. Action: Run the consumer loop
    # We need to get a reference to the actual consumer loop function.
    # This assumes `consume_kafka_events` takes the db session as an argument.
    # Adjust if it gets the session differently (e.g., via a global or context var).
    # Also, the consumer loop might be designed to run indefinitely.
    # The KeyboardInterrupt trick in poll.side_effect is one way to break it for tests.

    # For this test, we need to ensure that the KafkaConsumerService (or equivalent)
    # within `consume_kafka_events` gets the `mock_confluent_consumer_for_poll`.
    # This is typically handled if `consume_kafka_events` instantiates `Consumer` itself,
    # as `CONFLUENT_KAFKA_CONSUMER_PATH` is patched.

    from app.infrastructure.kafka.consumer import consume_kafka_events # Import the target function

    # Mock other dependencies of consume_kafka_events if any (e.g., producer for error topics)
    # For now, assuming it mainly needs db and the (mocked) consumer.
    # The `get_db` dependency for the consumer needs to be handled if it uses it directly.
    # Often, the db session is passed into the consumer processing logic.

    # The consumer loop needs a DB session. We provide the mongomock one.
    # It also needs a Kafka Producer for error handling (DLQ). Mock this too.
    with patch("app.infrastructure.kafka.consumer.KafkaProducerService", autospec=True) as mock_dlq_producer_service:
        mock_dlq_producer_instance = mock_dlq_producer_service.return_value
        mock_dlq_producer_instance.produce_message = AsyncMock()

        try:
            # If consume_kafka_events is async, it needs to be awaited or run in a task.
            # Assuming it's synchronous for now based on typical consumer patterns.
            # If it's async: await consume_kafka_events(test_db_session_for_kafka_tests)
            # If it's not async but creates an asyncio loop internally, that's more complex.
            # For now, let's assume `consume_kafka_events` can be called like this
            # and that the KeyboardInterrupt will stop it.

            # If consume_kafka_events is async:
            # await consume_kafka_events(test_db_session_for_kafka_tests)
            # For a synchronous loop that might run in a thread, this test structure would need adjustment.
            # Let's assume it's an async function for an asyncio-based service:

            # If consume_kafka_events is an async generator or a simple async function that processes one batch:
            # await consume_kafka_events(test_db_session_for_kafka_tests) # This line might change based on actual consumer structure

            # Simulating a call to a refactored single message processing logic if main loop is hard to test
            # from app.infrastructure.kafka.consumer import process_message # Hypothetical function
            # await process_message(mock_kafka_message, test_db_session_for_kafka_tests, mock_dispatch_command)

            # Given the current structure, it's likely `consume_kafka_events` is a long-running async function.
            # We will test its core logic by directly calling a (hypothetical for now) message processing part.
            # This is often the most practical way if the loop itself is not designed for easy testing.
            # For this exercise, let's assume `consume_kafka_events` can be run and interrupted.
            # Or, better, let's assume a refactoring where the core processing of a message is testable.
            # For now, we will mock the loop and call the processing function directly.

            # If we cannot easily call `consume_kafka_events` due to its loop structure,
            # we would ideally test a `_process_message` function.
            # Let's simulate that the `consume_kafka_events` was run and called `dispatch_command`.
            # This requires `consume_kafka_events` to correctly use the patched consumer and dispatcher.

            # To make this test runnable without actually running an infinite loop,
            # we'll assume `consume_kafka_events` calls a message handler that uses `dispatch_command`.
            # We'll directly test an assumed handler function or the effect of `dispatch_command`.
            # This part is highly dependent on the actual structure of `consumer.py`.

            # Let's assume the consumer has logic like this:
            # async def process_message_from_kafka(msg, db, command_dispatcher):
            #    data = json.loads(msg.value().decode('utf-8'))
            #    command_payload = data['payload']
            #    if data['command_type'] == "CreateCaseCommand":
            #        actual_command = service_commands.CreateCaseCommand(**command_payload)
            #        await command_dispatcher(actual_command, db)
            #
            # await process_message_from_kafka(mock_kafka_message, test_db_session_for_kafka_tests, mock_dispatch_command)
            # This above simulation is what we're essentially testing via the mocks.
            # The actual `consume_kafka_events` loop would call this.
            # For now, we can't directly call `consume_kafka_events` without knowing its exact structure
            # and how it handles shutdown for tests. The KeyboardInterrupt approach is common.

            # To proceed, we will assume `consume_kafka_events` is called elsewhere or started,
            # and it picks up the message from the mocked poll.
            # The following assertions would then hold after that execution.
            # This test will need `consume_kafka_events` to be callable in a test-friendly way.

            # If `consume_kafka_events` is the actual entry point we need to test:
            with pytest.raises(KeyboardInterrupt, match="Stopping test consumer"):
                 await consume_kafka_events(
                     db_session_factory=lambda: test_db_session_for_kafka_tests, # Assuming it takes a factory
                     kafka_consumer=mock_confluent_consumer_for_poll, # Pass the mocked consumer directly
                     dlq_producer=mock_dlq_producer_instance # Pass the mocked DLQ producer
                 )

        except KeyboardInterrupt:
            pass # Expected for stopping the consumer loop in test

    # 3. Assertions
    mock_confluent_consumer_for_poll.subscribe.assert_called_once_with(settings.KAFKA_CONSUMER_TOPICS)
    mock_confluent_consumer_for_poll.poll.assert_called_once_with(timeout=1.0) # Or whatever timeout is used

    # Check that dispatch_command was called
    mock_dispatch_command.assert_called_once()

    # Inspect the arguments to dispatch_command
    dispatched_command_call = mock_dispatch_command.call_args[0]
    dispatched_command_object = dispatched_command_call[0]
    dispatched_db_session = dispatched_command_call[1]

    assert isinstance(dispatched_command_object, service_commands.CreateCaseCommand)
    assert dispatched_command_object.created_by == user_id_from_kafka
    assert dispatched_command_object.case_type == CaseType.KYC
    assert len(dispatched_command_object.persons) == 1
    assert dispatched_command_object.persons[0]["profile"].name == "Consumed Person"

    assert dispatched_db_session == test_db_session_for_kafka_tests # Ensure DB session is passed

    # Verify commit was called with the processed message (or appropriate offset)
    # Confluent Kafka's commit can be called with no args (sync) or with message (async)
    # Depending on consumer's commit strategy (auto-commit vs. manual)
    # Assuming manual commit after processing:
    mock_confluent_consumer_for_poll.commit.assert_called_once_with(message=mock_kafka_message, asynchronous=False)

    # mock_dlq_producer_instance.produce_message.assert_not_called() # Ensure no errors sent to DLQ


# --- Full Flow Kafka Consumer Test (Message to DB Change) ---

# Define paths for command handler dependencies
COMMAND_HANDLER_KAFKA_PRODUCER_GETTER_PATH = "app.service.commands.handlers.get_kafka_producer"
COMMAND_HANDLER_NOTIFICATION_CONFIG_GETTER_PATH = "app.service.commands.handlers.get_notification_config_client"

@patch(COMMAND_HANDLER_KAFKA_PRODUCER_GETTER_PATH, new_callable=AsyncMock)
@patch(COMMAND_HANDLER_NOTIFICATION_CONFIG_GETTER_PATH, new_callable=AsyncMock)
async def test_kafka_message_triggers_case_creation_in_db(
    mock_handler_get_notification_config: AsyncMock, # For handle_create_case_command
    mock_handler_get_kafka_producer: AsyncMock,    # For handle_create_case_command
    mock_confluent_consumer_for_poll: MagicMock,
    test_db_session_for_kafka_tests: MongoMockClient,
):
    # 1. Mock Command Handler's External Dependencies
    # Mock for Kafka producer used by command handler for notifications
    mock_notification_kafka_producer_instance = AsyncMock()
    mock_notification_kafka_producer_instance.produce_message = AsyncMock(return_value=None)
    mock_handler_get_kafka_producer.return_value = mock_notification_kafka_producer_instance

    # Mock for NotificationConfigClient used by command handler
    mock_notification_config_instance = AsyncMock()
    mock_notification_config_instance.get_notification_strategy = AsyncMock(return_value="SEND_ALL")
    mock_handler_get_notification_config.return_value = mock_notification_config_instance

    # 2. Setup Kafka Message for CreateCaseCommand
    user_id_from_kafka = "full_flow_kafka_user"
    person_id_from_kafka = str(uuid.uuid4())
    # The case_id will be generated by the command handler, so not included in kafka message payload for command

    kafka_message_payload_content = { # This is the CreateCaseCommand's payload
        "case_type": CaseType.KYC.value,
        "created_by": user_id_from_kafka,
        "persons": [{
            "person_id": person_id_from_kafka,
            "profile": {"name": "Full Flow Person", "email": "full.flow@example.com"},
            "role": Role.PRIMARY_CONTACT.value
        }]
    }
    kafka_message_to_consume = { # This is the structure of the message value
        "command_type": "CreateCaseCommand",
        "payload": kafka_message_payload_content
    }

    mock_kafka_message = MagicMock()
    mock_kafka_message.value.return_value = json.dumps(kafka_message_to_consume).encode('utf-8')
    mock_kafka_message.error.return_value = None
    mock_kafka_message.topic.return_value = settings.KAFKA_CONSUMER_TOPICS[0] # Use one of the subscribed topics
    mock_kafka_message.partition.return_value = 0
    mock_kafka_message.offset.return_value = 101 # Next offset

    mock_confluent_consumer_for_poll.poll.side_effect = [mock_kafka_message, KeyboardInterrupt("Stopping test consumer")]

    # 3. Action: Run the consumer loop (DO NOT mock dispatch_command)
    from app.infrastructure.kafka.consumer import consume_kafka_events

    with patch("app.infrastructure.kafka.consumer.KafkaProducerService", autospec=True) as mock_dlq_producer_service:
        mock_dlq_producer_instance = mock_dlq_producer_service.return_value
        mock_dlq_producer_instance.produce_message = AsyncMock()

        with pytest.raises(KeyboardInterrupt, match="Stopping test consumer"):
            await consume_kafka_events(
                db_session_factory=lambda: test_db_session_for_kafka_tests,
                kafka_consumer=mock_confluent_consumer_for_poll,
                dlq_producer=mock_dlq_producer_instance
            )

    # 4. Assertions
    # Consumer interactions
    mock_confluent_consumer_for_poll.subscribe.assert_called_once_with(settings.KAFKA_CONSUMER_TOPICS)
    mock_confluent_consumer_for_poll.poll.assert_called_once_with(timeout=1.0)
    mock_confluent_consumer_for_poll.commit.assert_called_once_with(message=mock_kafka_message, asynchronous=False)

    # Event Store Verification (mongomock)
    event_store = test_db_session_for_kafka_tests[settings.EVENT_STORE_COLLECTION_NAME]

    # Find the CaseCreatedEvent - its aggregate_id is the generated case_id
    case_created_event_doc = event_store.find_one({"event_type": "CaseCreatedEvent", "payload.created_by": user_id_from_kafka})
    assert case_created_event_doc is not None
    generated_case_id = case_created_event_doc["aggregate_id"] # This is the dynamically generated case_id
    assert uuid.UUID(generated_case_id)
    assert case_created_event_doc["payload"]["case_type"] == CaseType.KYC.value
    assert case_created_event_doc["version"] == 1

    # PersonAddedToCaseEvent
    person_added_event_doc = event_store.find_one({
        "aggregate_id": generated_case_id,
        "event_type": "PersonAddedToCaseEvent",
        "payload.person_id": person_id_from_kafka
    })
    assert person_added_event_doc is not None
    assert person_added_event_doc["payload"]["profile"]["name"] == "Full Flow Person"
    assert person_added_event_doc["version"] == 2

    # NotificationRequiredEvent (for case creation)
    notification_event_doc = event_store.find_one({
        "aggregate_id": generated_case_id,
        "event_type": "NotificationRequiredEvent"
    })
    assert notification_event_doc is not None
    assert notification_event_doc["payload"]["notification_type"] == "CASE_CREATED"
    assert notification_event_doc["version"] == 3 # Assuming it's the third event for this aggregate

    # Read Models Verification (mongomock)
    cases_collection = test_db_session_for_kafka_tests[settings.CASES_READ_MODEL_COLLECTION_NAME]
    case_read_model = cases_collection.find_one({"case_id": generated_case_id})
    assert case_read_model is not None
    assert case_read_model["created_by"] == user_id_from_kafka
    assert case_read_model["case_type"] == CaseType.KYC.value
    assert case_read_model["status"] == "PENDING" # Default status from projector
    assert case_read_model["version"] == 1 # Reflects version of CaseCreatedEvent

    # Verify persons in case read model (if embedded)
    assert len(case_read_model["persons"]) == 1
    assert case_read_model["persons"][0]["person_id"] == person_id_from_kafka
    assert case_read_model["persons"][0]["name"] == "Full Flow Person"

    # Assert that the mocked Kafka producer (for notifications from command handler) was called
    mock_notification_kafka_producer_instance.produce_message.assert_called_once()
    call_args_notif_producer = mock_notification_kafka_producer_instance.produce_message.call_args.kwargs
    assert call_args_notif_producer["topic"] == settings.KAFKA_NOTIFICATIONS_TOPIC
    assert json.loads(call_args_notif_producer["key"]) == {"case_id": generated_case_id}
    notif_payload = json.loads(call_args_notif_producer["value"])
    assert notif_payload["case_id"] == generated_case_id
    assert notif_payload["notification_type"] == "CASE_CREATED"

    # Ensure no errors sent to DLQ by the consumer itself
    mock_dlq_producer_instance.produce_message.assert_not_called()
