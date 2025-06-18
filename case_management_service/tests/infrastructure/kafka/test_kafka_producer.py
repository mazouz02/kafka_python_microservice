# Unit Tests for Kafka Producer Utility
import asyncio
import unittest
from unittest.mock import patch, AsyncMock, MagicMock, call
from pydantic import BaseModel # For creating dummy Pydantic models for testing
import json

# Module to test
from case_management_service.infrastructure.kafka import producer as kafka_producer_module
from case_management_service.infrastructure.kafka.producer import KafkaProducerService
# Import settings to control it for tests
from case_management_service.app import config as app_config
# Import confluent_kafka to mock its Producer and for error types
from confluent_kafka import KafkaError, Message

# Dummy Pydantic model for testing message production
class DummyMessage(BaseModel):
    id: int
    content: str

class TestKafkaProducerService(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        # Store original settings that might be modified
        self.original_kafka_bootstrap_servers = app_config.settings.KAFKA_BOOTSTRAP_SERVERS
        # Reset global producer instance in the module to ensure fresh one per test if needed
        kafka_producer_module._kafka_producer_instance = None

    def tearDown(self):
        # Restore original settings
        app_config.settings.KAFKA_BOOTSTRAP_SERVERS = self.original_kafka_bootstrap_servers
        kafka_producer_module._kafka_producer_instance = None # Clean up global instance

    @patch('case_management_service.infrastructure.kafka.producer.Producer') # Mock confluent_kafka.Producer
    async def test_producer_initialization_and_get_producer(self, MockConfluentProducer):
        # Arrange
        mock_producer_instance = MagicMock()
        MockConfluentProducer.return_value = mock_producer_instance
        app_config.settings.KAFKA_BOOTSTRAP_SERVERS = "fake_server:9092"

        # Act
        producer_service = kafka_producer_module.get_kafka_producer()

        # Assert
        self.assertIsNotNone(producer_service)
        self.assertIsInstance(producer_service, KafkaProducerService)
        MockConfluentProducer.assert_called_once_with({
            'bootstrap.servers': "fake_server:9092"
        })
        producer_service_2 = kafka_producer_module.get_kafka_producer()
        self.assertIs(producer_service, producer_service_2)
        self.assertEqual(MockConfluentProducer.call_count, 1)


    async def test_get_producer_raises_error_if_no_servers_config(self):
        app_config.settings.KAFKA_BOOTSTRAP_SERVERS = None # Or ""
        with self.assertRaisesRegex(ValueError, "KAFKA_BOOTSTRAP_SERVERS not configured"):
            kafka_producer_module.get_kafka_producer()


    @patch('case_management_service.infrastructure.kafka.producer.Producer')
    async def test_produce_message_success(self, MockConfluentProducer):
        # Arrange
        mock_confluent_producer_instance = MagicMock()
        MockConfluentProducer.return_value = mock_confluent_producer_instance
        app_config.settings.KAFKA_BOOTSTRAP_SERVERS = "fake_server:9092"

        producer_service = kafka_producer_module.get_kafka_producer()

        test_topic = "test_topic"
        test_key = "test_key"
        test_message_model = DummyMessage(id=1, content="Hello Kafka")
        expected_value_json = test_message_model.model_dump_json()

        # Act
        producer_service.produce_message(test_topic, test_message_model, key=test_key)

        # Assert
        mock_confluent_producer_instance.produce.assert_called_once_with(
            test_topic,
            value=expected_value_json.encode('utf-8'),
            key=test_key.encode('utf-8'),
            callback=producer_service._delivery_report
        )

    @patch('case_management_service.infrastructure.kafka.producer.Producer')
    async def test_produce_message_buffer_error(self, MockConfluentProducer):
        # Arrange
        mock_confluent_producer_instance = MagicMock()
        mock_confluent_producer_instance.produce.side_effect = BufferError("Kafka queue full")
        MockConfluentProducer.return_value = mock_confluent_producer_instance
        app_config.settings.KAFKA_BOOTSTRAP_SERVERS = "fake_server:9092"

        producer_service = kafka_producer_module.get_kafka_producer()
        test_message_model = DummyMessage(id=2, content="Buffer Test")

        # Act & Assert
        with self.assertRaises(BufferError):
            producer_service.produce_message("buf_topic", test_message_model)

    def test_delivery_report_error(self):
        mock_confluent_producer = MagicMock()
        # Instantiate service directly for this sync test, overriding its producer
        service = KafkaProducerService(bootstrap_servers="mock_server_ignored")
        service.producer = mock_confluent_producer

        mock_msg = MagicMock(spec=Message)
        mock_msg.topic.return_value = "error_topic"
        mock_msg.key.return_value = b"error_key"
        mock_err = KafkaError(KafkaError._MSG_TIMED_OUT)

        with patch.object(kafka_producer_module.logger, 'error') as mock_logger_error:
            service._delivery_report(mock_err, mock_msg)

        mock_logger_error.assert_called_once()
        log_message_error = mock_logger_error.call_args[0][0]
        self.assertIn(f'Message delivery failed: Topic {mock_msg.topic()}', log_message_error)
        self.assertIn(f'Key {mock_msg.key()!r}', log_message_error) # Using !r for robust repr
        self.assertIn(str(mock_err), log_message_error)


    def test_delivery_report_success(self):
        mock_confluent_producer = MagicMock()
        service = KafkaProducerService(bootstrap_servers="mock_server_ignored")
        service.producer = mock_confluent_producer

        mock_msg = MagicMock(spec=Message)
        mock_msg.topic.return_value = "success_topic"
        mock_msg.key.return_value = b"success_key"
        mock_msg.partition.return_value = 0
        mock_msg.offset.return_value = 123

        with patch.object(kafka_producer_module.logger, 'info') as mock_logger_info:
            service._delivery_report(None, mock_msg)

        mock_logger_info.assert_called_once()
        log_message_success = mock_logger_info.call_args[0][0]
        self.assertIn(f'Message delivered: Topic {mock_msg.topic()}', log_message_success)
        self.assertIn(f'Key {mock_msg.key()!r}', log_message_success) # Using !r
        self.assertIn(f'Partition [{mock_msg.partition()}]', log_message_success)
        self.assertIn(f'@ Offset {mock_msg.offset()}', log_message_success)


    @patch('case_management_service.infrastructure.kafka.producer.Producer')
    async def test_flush_producer(self, MockConfluentProducer):
        # Arrange
        mock_confluent_producer_instance = MagicMock()
        mock_confluent_producer_instance.flush.return_value = 0
        MockConfluentProducer.return_value = mock_confluent_producer_instance
        app_config.settings.KAFKA_BOOTSTRAP_SERVERS = "fake_server:9092"

        producer_service = kafka_producer_module.get_kafka_producer()

        # Act
        remaining = producer_service.flush(timeout=5.0)

        # Assert
        self.assertEqual(remaining, 0)
        mock_confluent_producer_instance.flush.assert_called_once_with(5.0)

    @patch('case_management_service.infrastructure.kafka.producer.KafkaProducerService.start_polling', new_callable=AsyncMock)
    @patch('case_management_service.infrastructure.kafka.producer.get_kafka_producer') # Mock get_kafka_producer to control instance
    async def test_startup_kafka_producer(self, mock_get_producer, mock_start_polling):
        # Arrange
        mock_producer_service_instance = MagicMock(spec=KafkaProducerService)
        mock_producer_service_instance.start_polling = mock_start_polling # Assign the AsyncMock to the instance
        mock_get_producer.return_value = mock_producer_service_instance

        # Act
        await kafka_producer_module.startup_kafka_producer()

        # Assert
        mock_get_producer.assert_called_once() # Ensures get_kafka_producer was called
        mock_start_polling.assert_called_once()


    @patch('case_management_service.infrastructure.kafka.producer.KafkaProducerService.stop_polling', new_callable=AsyncMock)
    @patch('case_management_service.infrastructure.kafka.producer.KafkaProducerService.flush')
    @patch('case_management_service.infrastructure.kafka.producer.get_kafka_producer')
    async def test_shutdown_kafka_producer(self, mock_get_producer, mock_flush, mock_stop_polling):
        # Arrange
        mock_producer_service_instance = MagicMock(spec=KafkaProducerService)
        mock_producer_service_instance.flush = mock_flush
        mock_producer_service_instance.stop_polling = mock_stop_polling
        mock_get_producer.return_value = mock_producer_service_instance

        # Ensure _kafka_producer_instance is set for the shutdown logic to proceed
        kafka_producer_module._kafka_producer_instance = mock_producer_service_instance

        # Act
        await kafka_producer_module.shutdown_kafka_producer()

        # Assert
        mock_flush.assert_called_once()
        mock_stop_polling.assert_called_once()


    @patch('case_management_service.infrastructure.kafka.producer.Producer')
    async def test_poll_loop_start_stop(self, MockConfluentProducer):
        # Arrange
        mock_confluent_producer_instance = MagicMock()
        mock_confluent_producer_instance.poll = MagicMock() # Ensure poll is a mock
        MockConfluentProducer.return_value = mock_confluent_producer_instance

        # Instantiate service directly for this test to control its internal producer
        producer_service = kafka_producer_module.KafkaProducerService(bootstrap_servers="test_server:9092")
        producer_service.producer = mock_confluent_producer_instance # Override with mocked confluent producer

        self.assertIsNone(producer_service._poll_loop_task)

        # Act: Start polling
        await producer_service.start_polling()

        # Assert: Polling task created and not cancelled
        self.assertIsNotNone(producer_service._poll_loop_task)
        self.assertFalse(producer_service._cancelled)

        # Allow loop to run a few times
        await asyncio.sleep(0.3)
        mock_confluent_producer_instance.poll.assert_called_with(0.1)

        # Act: Stop polling
        await producer_service.stop_polling()

        # Assert: Cancelled flag set and task should be done (or None)
        self.assertTrue(producer_service._cancelled)
        if producer_service._poll_loop_task:
            self.assertTrue(producer_service._poll_loop_task.done())
