# Unit Tests for Kafka Consumer (Refactored Structure)
import asyncio
import json
import unittest
from unittest.mock import patch, AsyncMock, MagicMock, call
from confluent_kafka import Message, KafkaError # Using original confluent_kafka for Message and KafkaError

# Modules to test or support testing - new locations
from case_management_service.infrastructure.kafka import consumer as kafka_consumer_module # The module to test
from case_management_service.infrastructure.kafka.schemas import KafkaMessage # For verifying dispatched command data
from case_management_service.core.commands.models import CreateCaseCommand # For verifying dispatched command data
from opentelemetry.trace.status import Status, StatusCode # For checking span status


class TestKafkaConsumer(unittest.IsolatedAsyncioTestCase):

    @patch('case_management_service.infrastructure.kafka.consumer.Consumer')
    @patch('case_management_service.infrastructure.kafka.consumer.connect_to_mongo', MagicMock())
    @patch('case_management_service.infrastructure.kafka.consumer.close_mongo_connection', MagicMock())
    @patch('case_management_service.infrastructure.kafka.consumer.add_raw_event_to_store', new_callable=AsyncMock)
    @patch('case_management_service.infrastructure.kafka.consumer.dispatch_command', new_callable=AsyncMock)
    @patch('case_management_service.infrastructure.kafka.consumer.extract_trace_context_from_kafka_headers')
    @patch('case_management_service.infrastructure.kafka.consumer.tracer')
    @patch('case_management_service.infrastructure.kafka.consumer.kafka_messages_consumed_counter')
    async def test_consume_kafka_events_success_path(
        self, mock_metrics_counter, mock_tracer, mock_extract_trace_context,
        mock_dispatch_command, mock_add_raw_event_to_store, mock_consumer_cls # Renamed mock_add_raw_event
    ):
        # Arrange
        mock_consumer_instance = MagicMock()
        mock_consumer_cls.return_value = mock_consumer_instance

        mock_span = MagicMock()
        mock_tracer.start_as_current_span.return_value.__enter__.return_value = mock_span
        mock_extract_trace_context.return_value = None

        kafka_msg_data = {
            "client_id": "client1", "version": "1.0", "type": "KYC_FULL",
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
        mock_add_raw_event_to_store.return_value = MagicMock(id="raw_event_id_123") # mock return for add_raw_event_to_store

        # Act
        # consumer_task = asyncio.create_task(kafka_consumer_module.consume_kafka_events())
        # with self.assertRaises(KeyboardInterrupt):
        #      await asyncio.wait_for(consumer_task, timeout=2.0)
        # Running directly for simplicity in this test environment if event loop is managed by IsolatedAsyncioTestCase
        with self.assertRaises(KeyboardInterrupt):
            kafka_consumer_module.consume_kafka_events()


        # Assert
        mock_consumer_cls.assert_called_once()
        kafka_consumer_module.connect_to_mongo.assert_called_once()

        mock_consumer_instance.poll.assert_called()
        mock_extract_trace_context.assert_called_with(mock_kafka_message.headers())
        mock_tracer.start_as_current_span.assert_called()

        # Check that add_raw_event_to_store was called
        mock_add_raw_event_to_store.assert_called_once_with(kafka_msg_data, event_type="KAFKA_MESSAGE_RAW_STORED")

        self.assertEqual(mock_dispatch_command.call_count, 1)
        call_arg = mock_dispatch_command.call_args.args[0]
        self.assertIsInstance(call_arg, KafkaMessage)
        self.assertEqual(call_arg.client_id, "client1")
        self.assertEqual(call_arg.persons[0].firstname, "Kaf")

        mock_metrics_counter.add.assert_called_once_with(1, {"topic": "kyc_events", "kafka_partition": "0"})
        mock_consumer_instance.commit.assert_called_once_with(message=mock_kafka_message, asynchronous=False)
        kafka_consumer_module.close_mongo_connection.assert_called_once()


    @patch('case_management_service.infrastructure.kafka.consumer.Consumer')
    @patch('case_management_service.infrastructure.kafka.consumer.connect_to_mongo', MagicMock())
    @patch('case_management_service.infrastructure.kafka.consumer.close_mongo_connection', MagicMock())
    @patch('case_management_service.infrastructure.kafka.consumer.add_raw_event_to_store', new_callable=AsyncMock) # Mock this even if not directly asserted for errors
    @patch('case_management_service.infrastructure.kafka.consumer.dispatch_command', new_callable=AsyncMock)
    @patch('case_management_service.infrastructure.kafka.consumer.tracer')
    async def test_consume_kafka_events_json_decode_error(
        self, mock_tracer, mock_dispatch_command, mock_add_raw_event_to_store, mock_consumer_cls # Added mock_add_raw_event_to_store
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
        with self.assertRaises(KeyboardInterrupt):
            kafka_consumer_module.consume_kafka_events()

        # Assert
        mock_dispatch_command.assert_not_called()
        mock_consumer_instance.commit.assert_called_once_with(message=invalid_json_kafka_msg, asynchronous=False)
        mock_span.record_exception.assert_called_once()
        mock_span.set_status.assert_called_with(Status(StatusCode.ERROR, description="JSON Decode Error: Expecting value: line 1 column 1 (char 0)"))


    @patch('case_management_service.infrastructure.kafka.consumer.Consumer')
    @patch('case_management_service.infrastructure.kafka.consumer.connect_to_mongo', MagicMock())
    @patch('case_management_service.infrastructure.kafka.consumer.close_mongo_connection', MagicMock())
    @patch('case_management_service.infrastructure.kafka.consumer.dispatch_command', new_callable=AsyncMock)
    # No tracer mock needed here if error is before span creation for message processing
    async def test_consume_kafka_events_kafka_error(
        self, mock_dispatch_command, mock_consumer_cls
    ):
        # Arrange
        mock_consumer_instance = MagicMock()
        mock_consumer_cls.return_value = mock_consumer_instance

        error_kafka_msg = MagicMock(spec=Message)
        mock_kafka_error = MagicMock(spec=KafkaError)
        mock_kafka_error.code.return_value = KafkaError._AUTHENTICATION
        mock_kafka_error.__str__.return_value = "Mock Kafka Authentication Error"
        error_kafka_msg.error.return_value = mock_kafka_error
        error_kafka_msg.topic.return_value = "kyc_events"
        error_kafka_msg.partition.return_value = 0
        error_kafka_msg.offset.return_value = 102


        mock_consumer_instance.poll.side_effect = [error_kafka_msg, KeyboardInterrupt("Stop test")]
        mock_consumer_instance.commit = MagicMock()


        # Act
        with self.assertRaises(KeyboardInterrupt):
            kafka_consumer_module.consume_kafka_events()

        # Assert
        mock_dispatch_command.assert_not_called()
        mock_consumer_instance.commit.assert_called_once_with(message=error_kafka_msg, asynchronous=False)
