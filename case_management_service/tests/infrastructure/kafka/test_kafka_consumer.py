# Unit Tests for Kafka Consumer (Refactored Structure)
import asyncio # Keep for clarity
import json
import pytest
from unittest.mock import patch, AsyncMock, MagicMock, call # Keep call if used
from confluent_kafka import Message, KafkaError # Using original confluent_kafka for Message and KafkaError

# Modules to test or support testing - new locations
from case_management_service.infrastructure.kafka import consumer as kafka_consumer_module # The module to test
from case_management_service.infrastructure.kafka.schemas import KafkaMessage # For verifying dispatched command data
from case_management_service.app.service.commands.models import CreateCaseCommand # Updated import path
from opentelemetry.trace.status import Status, StatusCode # For checking span status


@pytest.mark.asyncio
@patch('case_management_service.infrastructure.kafka.consumer.Consumer')
@patch('case_management_service.infrastructure.kafka.consumer.connect_to_mongo', MagicMock())
@patch('case_management_service.infrastructure.kafka.consumer.close_mongo_connection', MagicMock())
@patch('case_management_service.infrastructure.kafka.consumer.add_raw_event_to_store', new_callable=AsyncMock)
@patch('case_management_service.infrastructure.kafka.consumer.dispatch_command', new_callable=AsyncMock)
@patch('case_management_service.infrastructure.kafka.consumer.extract_trace_context_from_kafka_headers')
@patch('case_management_service.infrastructure.kafka.consumer.tracer')
@patch('case_management_service.infrastructure.kafka.consumer.kafka_messages_consumed_counter')
async def test_consume_kafka_events_success_path(
    mock_metrics_counter, mock_tracer, mock_extract_trace_context,
    mock_dispatch_command, mock_add_raw_event_to_store, mock_consumer_cls
):
    # Arrange
    mock_consumer_instance = MagicMock()
    mock_consumer_cls.return_value = mock_consumer_instance

    mock_span = MagicMock()
    mock_tracer.start_as_current_span.return_value.__enter__.return_value = mock_span
    mock_extract_trace_context.return_value = None

    kafka_msg_data = {
        "client_id": "client1", "version": "1.0", "type": "KYC_FULL", "traitement_type": "KYC",
        "persons": [{"firstname": "Kaf", "lastname": "Ka", "birthdate": "1980-01-01"}]
    }
    kafka_msg_json = json.dumps(kafka_msg_data)

    mock_kafka_message = MagicMock(spec=Message)
    mock_kafka_message.value.return_value = kafka_msg_json.encode('utf-8')
    mock_kafka_message.error.return_value = None
    mock_kafka_message.topic.return_value = "kyc_events"
    mock_kafka_message.partition.return_value = 0
    mock_kafka_message.offset.return_value = 100
    mock_kafka_message.headers.return_value = [("some_header", b"some_value")]
    mock_kafka_message.key.return_value = b"test_key"

    mock_consumer_instance.poll.side_effect = [mock_kafka_message, KeyboardInterrupt("Stop test loop")]
    mock_consumer_instance.commit = MagicMock()
    mock_add_raw_event_to_store.return_value = MagicMock(id="raw_event_id_123")

    # Act
    # The KeyboardInterrupt is used to break the infinite loop in consume_kafka_events for testing.
    # Pytest doesn't automatically handle this like unittest.IsolatedAsyncioTestCase might for task cancellation.
    # Running it directly and expecting the KeyboardInterrupt to propagate is one way.
    with pytest.raises(KeyboardInterrupt, match="Stop test loop"):
        await kafka_consumer_module.consume_kafka_events()

    # Assert
    mock_consumer_cls.assert_called_once()
    kafka_consumer_module.connect_to_mongo.assert_called_once()

    # mock_consumer_instance.poll will be called twice (once for message, once for interrupt)
    assert mock_consumer_instance.poll.call_count >= 1 # At least one successful poll
    mock_extract_trace_context.assert_called_with(mock_kafka_message.headers())
    mock_tracer.start_as_current_span.assert_called()

    mock_add_raw_event_to_store.assert_called_once_with(kafka_msg_data, event_type="KAFKA_MESSAGE_RAW_STORED")

    assert mock_dispatch_command.call_count == 1
    call_arg = mock_dispatch_command.call_args.args[0]
    assert isinstance(call_arg, KafkaMessage)
    assert call_arg.client_id == "client1"
    assert call_arg.persons[0].firstname == "Kaf"

    mock_metrics_counter.add.assert_called_once_with(1, {"topic": "kyc_events", "kafka_partition": "0"})
    mock_consumer_instance.commit.assert_called_once_with(message=mock_kafka_message, asynchronous=False)

    # These assertions are after the loop, so they should be checked regardless of KeyboardInterrupt
    mock_consumer_instance.close.assert_called_once()
    kafka_consumer_module.close_mongo_connection.assert_called_once()

@pytest.mark.asyncio
@patch('case_management_service.infrastructure.kafka.consumer.Consumer')
@patch('case_management_service.infrastructure.kafka.consumer.connect_to_mongo', MagicMock())
@patch('case_management_service.infrastructure.kafka.consumer.close_mongo_connection', MagicMock())
@patch('case_management_service.infrastructure.kafka.consumer.add_raw_event_to_store', new_callable=AsyncMock)
@patch('case_management_service.infrastructure.kafka.consumer.dispatch_command', new_callable=AsyncMock)
@patch('case_management_service.infrastructure.kafka.consumer.tracer')
async def test_consume_kafka_events_json_decode_error(
    mock_tracer, mock_dispatch_command, mock_add_raw_event_to_store, mock_consumer_cls
):
    # Arrange
    mock_consumer_instance = MagicMock()
    mock_consumer_cls.return_value = mock_consumer_instance
    mock_span = MagicMock()
    mock_tracer.start_as_current_span.return_value.__enter__.return_value = mock_span

    invalid_json_kafka_msg = MagicMock(spec=Message)
    invalid_json_kafka_msg.value.return_value = b"this is not json"
    invalid_json_kafka_msg.error.return_value = None
    invalid_json_kafka_msg.topic.return_value = "kyc_events"
    invalid_json_kafka_msg.partition.return_value = 0
    invalid_json_kafka_msg.offset.return_value = 101
    invalid_json_kafka_msg.headers.return_value = []
    invalid_json_kafka_msg.key.return_value = None

    mock_consumer_instance.poll.side_effect = [invalid_json_kafka_msg, KeyboardInterrupt("Stop test")]
    mock_consumer_instance.commit = MagicMock()

    # Act
    with pytest.raises(KeyboardInterrupt, match="Stop test"):
        await kafka_consumer_module.consume_kafka_events()

    # Assert
    mock_dispatch_command.assert_not_called()
    mock_consumer_instance.commit.assert_called_once_with(message=invalid_json_kafka_msg, asynchronous=False)
    mock_consumer_instance.close.assert_called_once()
    kafka_consumer_module.close_mongo_connection.assert_called_once()
    mock_span.record_exception.assert_called_once()

    mock_span.set_status.assert_called_once()
    args, _ = mock_span.set_status.call_args
    status_arg = args[0]
    assert isinstance(status_arg, Status)
    assert status_arg.status_code == StatusCode.ERROR
    assert status_arg.description == "JSON Decode Error: JSONDecodeError"

@pytest.mark.asyncio
@patch('case_management_service.infrastructure.kafka.consumer.Consumer')
@patch('case_management_service.infrastructure.kafka.consumer.connect_to_mongo', MagicMock())
@patch('case_management_service.infrastructure.kafka.consumer.close_mongo_connection', MagicMock())
@patch('case_management_service.infrastructure.kafka.consumer.dispatch_command', new_callable=AsyncMock)
async def test_consume_kafka_events_kafka_error(
    mock_dispatch_command, mock_consumer_cls
):
    # Arrange
    mock_consumer_instance = MagicMock()
    mock_consumer_cls.return_value = mock_consumer_instance

    error_kafka_msg = MagicMock(spec=Message)
    mock_kafka_error = MagicMock(spec=KafkaError)
    # Ensure code() is a callable attribute if that's how it's used by confluent_kafka.KafkaError
    # For MagicMock, direct attribute assignment is fine if it's just a value.
    # If it's a method, it should be: mock_kafka_error.code.return_value = KafkaError._AUTHENTICATION
    # Assuming error.code() is the access pattern in the code under test based on confluent_kafka documentation
    # If it's just error.code, then the direct assignment is fine. Let's assume it's a method call.
    type(mock_kafka_error).code = MagicMock(return_value=KafkaError._AUTHENTICATION) # Make .code() callable
    mock_kafka_error.__str__.return_value = "Mock Kafka Authentication Error"
    error_kafka_msg.error.return_value = mock_kafka_error
    # topic, partition, offset might not be strictly necessary if error() is not None, but good for completeness
    error_kafka_msg.topic.return_value = "kyc_events"
    error_kafka_msg.partition.return_value = 0
    error_kafka_msg.offset.return_value = 102


    mock_consumer_instance.poll.side_effect = [error_kafka_msg, KeyboardInterrupt("Stop test")]
    mock_consumer_instance.commit = MagicMock()

    # Act
    with pytest.raises(KeyboardInterrupt, match="Stop test"):
        await kafka_consumer_module.consume_kafka_events()

    # Assert
    mock_dispatch_command.assert_not_called()
    # If an error occurs, the message might not be committed in the same way,
    # or commit might not be called at all depending on error handling logic.
    # The original test asserts it's called. Let's keep it.
    mock_consumer_instance.commit.assert_called_once_with(message=error_kafka_msg, asynchronous=False)
    mock_consumer_instance.close.assert_called_once()
    kafka_consumer_module.close_mongo_connection.assert_called_once()
