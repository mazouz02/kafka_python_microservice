# Kafka Consumer Implementation
import asyncio
import json
import logging
import os
import time # Keep time import for latency

from confluent_kafka import Consumer, KafkaError, KafkaException, Message

from opentelemetry.trace import SpanKind, get_current_span
from opentelemetry.trace.status import StatusCode, Status

# Corrected imports based on new structure
from case_management_service.app.config import settings
from .schemas import KafkaMessage
from case_management_service.app.service.commands.models import CreateCaseCommand # Updated import path
from case_management_service.app.service.commands.handlers import handle_create_case_command
from motor.motor_asyncio import AsyncIOMotorDatabase # For db type hint
from case_management_service.infrastructure.kafka.producer import KafkaProducerService # For producer type hint
from case_management_service.app.service.interfaces.notification_config_client import AbstractNotificationConfigClient # For config client type hint

# Import the new histogram along with other observability components
from case_management_service.app.observability import (
    tracer,
    kafka_messages_consumed_counter,
    case_creation_latency_histogram, # Added histogram
    extract_trace_context_from_kafka_headers,
    setup_opentelemetry
)
from case_management_service.infrastructure.database.raw_event_store import add_raw_event_to_store
from case_management_service.infrastructure.database.connection import connect_to_mongo, close_mongo_connection


logger = logging.getLogger(__name__)

async def dispatch_command(
    validated_message: KafkaMessage,
    db: AsyncIOMotorDatabase,
    kafka_producer: KafkaProducerService,
    config_client: AbstractNotificationConfigClient
):
    start_time = time.monotonic() # For latency calculation
    with tracer.start_as_current_span("dispatch_command_from_kafka", kind=SpanKind.INTERNAL) as cmd_span:
        cmd_span.set_attribute("messaging.system", "kafka")
        cmd_span.set_attribute("case.client_id", validated_message.client_id)

        create_case_cmd = CreateCaseCommand(
            client_id=validated_message.client_id,
            case_type=validated_message.type,
            case_version=validated_message.version,
            persons=[person for person in validated_message.persons]
        )
        cmd_span.add_event("CommandCreatedFromKafkaMessage", {"command.id": create_case_cmd.command_id, "command.type": "CreateCaseCommand"})

        # Pass resolved dependencies to the command handler
        case_id = await handle_create_case_command(
            db=db,
            command=create_case_cmd,
            kafka_producer=kafka_producer,
            config_client=config_client
        )

        latency = time.monotonic() - start_time
        if hasattr(case_creation_latency_histogram, "record"):
            case_creation_latency_histogram.record(latency, attributes={"command.type": "CreateCaseCommand", "success": "true"})

        cmd_span.set_attribute("case.id", case_id)
        cmd_span.add_event("CommandHandlerInvoked", {"case.id": case_id, "latency_seconds": latency})
        logger.info(f"Command {create_case_cmd.command_id} (for client {validated_message.client_id}) dispatched, resulted in case_id: {case_id}. Latency: {latency:.4f}s")


async def consume_kafka_events(
    kafka_producer_instance: KafkaProducerService, # Added DI instance
    config_client_instance: AbstractNotificationConfigClient # Added DI instance
):
    logger.info("Initializing Kafka consumer...")
    conf = {
        'bootstrap.servers': settings.KAFKA_BOOTSTRAP_SERVERS,
        'group.id': settings.KAFKA_CONSUMER_GROUP_ID,
        'auto.offset.reset': 'earliest',
        'enable.auto.commit': False
    }
    consumer = Consumer(conf)

    db: Optional[AsyncIOMotorDatabase] = None  # Initialize db variable
    try:
        connect_to_mongo()
        # Fetch the db instance once after connection is established
        from case_management_service.infrastructure.database.connection import get_db
        async for session in get_db(): # Iterate once to get the db session
            db = session
            break
        if db is None:
            logger.error("Failed to obtain database session for consumer. Exiting.")
            return

        consumer.subscribe([settings.KAFKA_TOPIC_NAME])
        logger.info(f"Kafka consumer subscribed to {settings.KAFKA_TOPIC_NAME} with group {settings.KAFKA_CONSUMER_GROUP_ID}. Waiting for messages...")

        while True:
            msg = consumer.poll(timeout=1.0)
            if msg is None:
                continue

            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                else:
                    logger.error(f"Kafka error: {msg.error()}. Committing offset for msg at {msg.topic()}/{msg.partition()}/{msg.offset()} and skipping.")
                    consumer.commit(message=msg, asynchronous=False)
                    continue

            parent_context = extract_trace_context_from_kafka_headers(msg.headers())
            with tracer.start_as_current_span("kafka_message_received", kind=SpanKind.CONSUMER, context=parent_context) as consume_span:
                msg_topic = msg.topic()
                msg_partition = msg.partition()
                msg_offset = msg.offset()

                consume_span.set_attribute("messaging.system", "kafka")
                consume_span.set_attribute("messaging.destination.name", msg_topic)
                consume_span.set_attribute("messaging.kafka.partition", msg_partition)
                consume_span.set_attribute("messaging.kafka.message.offset", msg_offset)
                if msg.key():
                    consume_span.set_attribute("messaging.kafka.message.key", msg.key().decode(errors='ignore'))

                try:
                    message_data_str = msg.value().decode('utf-8')
                    consume_span.set_attribute("messaging.message.payload_size_bytes", len(message_data_str))

                    if hasattr(kafka_messages_consumed_counter, 'add'):
                        kafka_messages_consumed_counter.add(1, {"topic": msg_topic, "kafka_partition": str(msg_partition)})

                    logger.info(f"Consumed message from {msg_topic}/{msg_partition}/{msg_offset}")
                    consume_span.add_event("MessageDecodingAttempt")

                    message_data = json.loads(message_data_str)
                    consume_span.add_event("MessageDecodedSuccessfully")

                    raw_event_persisted = await add_raw_event_to_store(message_data, event_type="KAFKA_MESSAGE_RAW_STORED")
                    consume_span.add_event("RawMessageStored", {"raw_event.id": raw_event_persisted.id})

                    validated_message = KafkaMessage(**message_data)
                    consume_span.set_attribute("case.client_id", validated_message.client_id)
                    consume_span.add_event("MessageValidated", {"client_id": validated_message.client_id})

                    await dispatch_command(
                        validated_message,
                        db=db, # Pass db instance from consume_kafka_events
                        kafka_producer=kafka_producer_instance, # Pass producer from consume_kafka_events
                        config_client=config_client_instance # Pass config client from consume_kafka_events
                    )

                    consumer.commit(message=msg, asynchronous=False)
                    consume_span.add_event("OffsetCommitted")
                    consume_span.set_status(Status(StatusCode.OK))

                except json.JSONDecodeError as e:
                    logger.error(f"JSON Decode Error for message at {msg_topic}/{msg_partition}/{msg_offset}: {e}", exc_info=True)
                    consume_span.record_exception(e)
                    consume_span.set_status(Status(StatusCode.ERROR, description=f"JSON Decode Error: {type(e).__name__}")) # Use type for brevity
                    consumer.commit(message=msg, asynchronous=False)
                except Exception as e:
                    logger.error(f"Error processing message at {msg_topic}/{msg_partition}/{msg_offset}: {e}", exc_info=True)
                    consume_span.record_exception(e)
                    consume_span.set_status(Status(StatusCode.ERROR, description=f"Processing Error: {type(e).__name__}"))
                    consumer.commit(message=msg, asynchronous=False)
    except KeyboardInterrupt:
        logger.info("Kafka consumer process interrupted by user.")
    except KafkaException as ke:
        logger.critical(f"Critical KafkaException in consumer: {ke}", exc_info=True)
    finally:
        logger.info("Closing Kafka consumer...")
        consumer.close()
        close_mongo_connection()
        logger.info("Kafka consumer closed. MongoDB connection closed.")

if __name__ == '__main__':
    # Setup basic logging for the script
    logging.basicConfig(level=settings.LOG_LEVEL.upper(),
                        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # Setup OpenTelemetry for the consumer service
    setup_opentelemetry(service_name=settings.SERVICE_NAME_CONSUMER)

    # --- Dependency Setup for Consumer ---
    # This is where we manually resolve dependencies that FastAPI would normally handle.

    # 1. Database Connection
    # connect_to_mongo() is called within consume_kafka_events,
    # and get_db() relies on this global connection.
    # We'll fetch the db instance within consume_kafka_events.

    # 2. Kafka Producer
    # Re-use the get_kafka_producer logic from the app's DI system.
    # This assumes KAFKA_BOOTSTRAP_SERVERS is configured.
    from case_management_service.infrastructure.kafka.producer import get_kafka_producer as get_app_kafka_producer
    try:
        app_kafka_producer = get_app_kafka_producer()
        # We need to manually start its polling if it's not already started (e.g. if consumer runs independently)
        # However, if this consumer is part of the same process that might run the API,
        # startup_kafka_producer might have already been called.
        # For a standalone consumer, we'd manage its lifecycle here.
        # For simplicity, we assume it's configured and ready.
        logger.info("Kafka producer obtained for command handler DI.")
    except Exception as e:
        logger.error(f"Failed to initialize Kafka producer for DI: {e}", exc_info=True)
        # Decide if consumer should exit or run without ability to produce follow-up events
        raise

    # 3. HTTP Client & Config Service Client
    # We need an httpx.AsyncClient for the NotificationConfigServiceClient.
    import httpx
    from case_management_service.infrastructure.config_service_client import NotificationConfigServiceClient

    http_client_for_consumer: Optional[httpx.AsyncClient] = None
    config_service_client_for_consumer: Optional[AbstractNotificationConfigClient] = None
    try:
        http_client_for_consumer = httpx.AsyncClient(timeout=settings.DEFAULT_HTTP_TIMEOUT)
        # Instrument it if desired (manual instrumentation for non-FastAPI context)
        # from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        # HTTPXClientInstrumentor().instrument_client(http_client_for_consumer)
        config_service_client_for_consumer = NotificationConfigServiceClient(http_client=http_client_for_consumer)
        logger.info("HTTP client and NotificationConfigServiceClient initialized for command handler DI.")
    except Exception as e:
        logger.error(f"Failed to initialize HTTP client or Config Service client for DI: {e}", exc_info=True)
        # Decide if consumer should exit
        if http_client_for_consumer: # try to clean up if partially initialized
            asyncio.run(http_client_for_consumer.aclose())
        raise

    logger.info("Starting Kafka consumer with manually resolved dependencies for command handlers...")

    # Pass the resolved dependencies to consume_kafka_events
    # We modify consume_kafka_events to accept these.
    try:
        asyncio.run(consume_kafka_events(
            kafka_producer_instance=app_kafka_producer,
            config_client_instance=config_service_client_for_consumer
        ))
    finally:
        if http_client_for_consumer:
            asyncio.run(http_client_for_consumer.aclose())
        # Kafka producer from get_app_kafka_producer is a singleton managed elsewhere,
        # so we don't close it here; its lifecycle is tied to the app or global state.
        logger.info("Consumer process finished. HTTP client closed if initialized.")
