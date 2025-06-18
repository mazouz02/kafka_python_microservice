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
from case_management_service.app.models.commands.models import CreateCaseCommand
from case_management_service.app.service.commands.handlers import handle_create_case_command
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

async def dispatch_command(validated_message: KafkaMessage):
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

        case_id = await handle_create_case_command(create_case_cmd)

        latency = time.monotonic() - start_time
        if hasattr(case_creation_latency_histogram, "record"):
            case_creation_latency_histogram.record(latency, attributes={"command.type": "CreateCaseCommand", "success": "true"})

        cmd_span.set_attribute("case.id", case_id)
        cmd_span.add_event("CommandHandlerInvoked", {"case.id": case_id, "latency_seconds": latency})
        logger.info(f"Command {create_case_cmd.command_id} (for client {validated_message.client_id}) dispatched, resulted in case_id: {case_id}. Latency: {latency:.4f}s")


async def consume_kafka_events():
    logger.info("Initializing Kafka consumer...")
    conf = {
        'bootstrap.servers': settings.KAFKA_BOOTSTRAP_SERVERS,
        'group.id': settings.KAFKA_CONSUMER_GROUP_ID,
        'auto.offset.reset': 'earliest',
        'enable.auto.commit': False
    }
    consumer = Consumer(conf)

    try:
        connect_to_mongo()
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

                    await dispatch_command(validated_message)

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
    logging.basicConfig(level=settings.LOG_LEVEL.upper(),
                        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    setup_opentelemetry(service_name=settings.SERVICE_NAME_CONSUMER)

    logger.info("Starting Kafka consumer directly (refactored version using AppSettings)...")
    asyncio.run(consume_kafka_events())
