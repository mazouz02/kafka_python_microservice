# Kafka Producer Utility
import asyncio
import json
import logging
from confluent_kafka import Producer
from pydantic import BaseModel
from typing import Optional, Callable, Any # Added Any for callback type hint flexibility

# Import settings for Kafka brokers and notification topic
from case_management_service.app.config import settings

logger = logging.getLogger(__name__)

class KafkaProducerService:
    def __init__(self, bootstrap_servers: str):
        self.producer_config = {
            'bootstrap.servers': bootstrap_servers,
            # 'linger.ms': 10, # Example: Batch messages for 10ms
            # 'acks': 'all', # Example: Wait for all replicas
            # Add other producer configs as needed: compression, retries, etc.
        }
        self.producer = Producer(self.producer_config)
        self._cancelled = False
        self._poll_loop_task: Optional[asyncio.Task] = None
        logger.info(f"KafkaProducer initialized with servers: {bootstrap_servers}")

    def _delivery_report(self, err, msg):
        """ Called once for each message produced to indicate delivery result. """
        if err is not None:
            logger.error(f'Message delivery failed: Topic {msg.topic()} Key {msg.key()}: {err}')
        else:
            logger.info(f'Message delivered: Topic {msg.topic()} Key {msg.key()} Partition [{msg.partition()}] @ Offset {msg.offset()}')

    async def _poll_loop(self):
        """ Polls the producer for delivery reports. """
        while not self._cancelled:
            self.producer.poll(0.1) # Poll for 100ms, then yield to asyncio loop
            await asyncio.sleep(0.1) # Allow other asyncio tasks to run
        logger.info("KafkaProducer poll loop stopped.")


    def produce_message(
        self,
        topic: str,
        message: BaseModel,
        key: Optional[str] = None,
        callback: Optional[Callable[[Any, Any], None]] = None # err, msg
    ):
        """ Produces a Pydantic model message to a Kafka topic. """
        if self._cancelled:
            logger.warning(f"Producer is cancelled, not producing message to {topic}.")
            return

        try:
            value_json = message.model_dump_json()

            self.producer.produce(
                topic,
                value=value_json.encode('utf-8'),
                key=key.encode('utf-8') if key else None,
                callback=callback if callback else self._delivery_report
            )
            # For higher throughput, rely on background poll_loop or periodic flush calls
            # rather than polling after every produce.
            # self.producer.poll(0) # Non-blocking poll
            logger.debug(f"Message enqueued to topic {topic} (key: {key}): {value_json}")
        except BufferError as e:
            logger.error(f"Kafka producer queue full. Message to {topic} not produced. Error: {e}")
            # Consider how to handle this: retry, raise, DLQ. For now, re-raise.
            raise
        except Exception as e:
            logger.error(f"Error producing message to Kafka topic {topic}: {e}", exc_info=True)
            raise

    async def start_polling(self):
        if self._poll_loop_task is None or self._poll_loop_task.done():
            self._cancelled = False
            self._poll_loop_task = asyncio.create_task(self._poll_loop())
            logger.info("KafkaProducer polling started.")

    async def stop_polling(self):
        if self._poll_loop_task and not self._cancelled:
            self._cancelled = True
            if self._poll_loop_task: # Check if task exists
                try:
                    await asyncio.wait_for(self._poll_loop_task, timeout=5.0)
                except asyncio.TimeoutError:
                    logger.warning("KafkaProducer poll loop did not stop in time.")
                except Exception as e:
                    logger.error(f"Error stopping KafkaProducer poll loop: {e}", exc_info=True)
            self._poll_loop_task = None # Clear task reference


    def flush(self, timeout: float = 10.0) -> int: # Return remaining messages
        """Wait for all messages in the Producer queue to be delivered. """
        remaining = self.producer.flush(timeout)
        if remaining > 0:
            logger.warning(f"{remaining} messages still in Kafka producer queue after flush timeout.")
        else:
            logger.info("All Kafka messages flushed successfully.")
        return remaining

_kafka_producer_instance: Optional[KafkaProducerService] = None

def get_kafka_producer() -> KafkaProducerService:
    global _kafka_producer_instance
    if _kafka_producer_instance is None:
        if not settings.KAFKA_BOOTSTRAP_SERVERS:
            # This case should ideally be handled at app startup by trying to init early
            # or by Config ensuring KAFKA_BOOTSTRAP_SERVERS is set.
            logger.error("KAFKA_BOOTSTRAP_SERVERS not configured in settings. KafkaProducer cannot be initialized.")
            raise ValueError("KAFKA_BOOTSTRAP_SERVERS not configured.")
        _kafka_producer_instance = KafkaProducerService(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS
        )
    return _kafka_producer_instance

async def startup_kafka_producer():
    # Call get_kafka_producer to initialize if needed
    producer = get_kafka_producer()
    # Start its background polling task. This should be called during app startup.
    await producer.start_polling()

async def shutdown_kafka_producer():
    # Check if instance was created to avoid error if never used/initialized
    if _kafka_producer_instance:
        logger.info("Flushing Kafka producer before shutdown...")
        _kafka_producer_instance.flush() # Flush remaining messages
        await _kafka_producer_instance.stop_polling() # Stop the poll loop
        logger.info("Kafka producer shutdown complete.")
    else:
        logger.info("Kafka producer was not initialized, skipping shutdown steps.")
