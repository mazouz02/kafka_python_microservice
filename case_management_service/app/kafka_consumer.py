import json
import logging
import asyncio
import os # Added os import
from confluent_kafka import Consumer, KafkaError, KafkaException

from .kafka_models import KafkaMessage, PersonData as KafkaPersonData
from ..database import add_raw_event, connect_to_mongo, close_mongo_connection
from . import commands # Import commands module
from .command_handlers import handle_create_case_command # Import specific handler

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def store_event_async(data, event_type): # This helper might be reused or adapted
    return await add_raw_event(data, event_type)

async def process_kafka_message_to_command(validated_message: KafkaMessage):
    # Transform KafkaMessage to CreateCaseCommand
    # Assuming kafka_models.PersonData is compatible with commands.CreateCaseCommand.persons items

    create_case_cmd = commands.CreateCaseCommand(
        client_id=validated_message.client_id,
        case_type=validated_message.type, # Assuming 'type' from Kafka maps to 'case_type'
        case_version=validated_message.version, # Assuming 'version' from Kafka maps to 'case_version'
        persons=[person for person in validated_message.persons] # Direct pass-through
    )

    # Call the command handler
    case_id = await handle_create_case_command(create_case_cmd)
    logger.info(f"CreateCaseCommand processed successfully by handler for new case_id: {case_id}")


def consume_events():
    conf = {
        'bootstrap.servers': os.environ.get('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092'),
        'group.id': 'case_management_group_cqrs', # Changed group id
        'auto.offset.reset': 'earliest',
        'enable.auto.commit': 'false' # Important for at-least-once processing with explicit commits
    }
    consumer = Consumer(conf)

    try:
        connect_to_mongo() # Connect to MongoDB at startup

        consumer.subscribe([os.environ.get('KAFKA_TOPIC_NAME', 'kyc_events')])
        logger.info("Kafka consumer started (CQRS version). Waiting for messages...")

        while True:
            msg = consumer.poll(timeout=1.0)
            if msg is None:
                continue

            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    # logger.info(f"Reached end of partition {msg.topic()} [{msg.partition()}] at offset {msg.offset()}")
                    continue # Continue polling, EOF is not an error
                elif msg.error().code() == KafkaError.UNKNOWN_TOPIC_OR_PART:
                    logger.error(f"Kafka error: {msg.error()}. Topic not found or partition issue. Retrying subscription...")
                    # Potentially add a delay before retrying subscription
                    consumer.subscribe([os.environ.get('KAFKA_TOPIC_NAME', 'kyc_events')])
                    asyncio.sleep(5) # wait a bit before next poll
                    continue
                else:
                    logger.error(f"Kafka error: {msg.error()}. Skipping message.")
                    # For other errors, we might log and skip, or if it's critical, break/raise.
                    # Committing offset for the bad message so we don't process it again if it's poison pill
                    consumer.commit(message=msg, asynchronous=False)
                    continue
            else:
                try:
                    message_data = json.loads(msg.value().decode('utf-8'))
                    logger.info(f"Received raw message: {msg.topic()}/{msg.partition()}/{msg.offset()}")

                    # 1. Store raw event (for auditing/debugging)
                    raw_event_persisted = asyncio.run(store_event_async(message_data, event_type="KAFKA_MESSAGE_RECEIVED_FOR_COMMAND"))
                    logger.debug(f"Raw event {raw_event_persisted.id} stored.")

                    # 2. Validate Kafka message
                    validated_message = KafkaMessage(**message_data)
                    logger.debug(f"Validated Kafka message: {validated_message.client_id}")

                    # 3. Process message by converting to command and handling it
                    # Wrapped the call to process_kafka_message_to_command in asyncio.run()
                    await asyncio.run(process_kafka_message_to_command(validated_message))

                    # 4. Manually commit offset after successful processing
                    consumer.commit(message=msg, asynchronous=False) # Sync commit for stronger guarantee
                    logger.debug(f"Offset {msg.offset()} committed for topic {msg.topic()}[{msg.partition()}]")

                except json.JSONDecodeError as e:
                    logger.error(f"JSON Decode Error: {e} for message: {msg.value().decode('utf-8')}. Skipping and committing.")
                    consumer.commit(message=msg, asynchronous=False)
                except Exception as e: # Includes Pydantic validation errors and errors from command handler
                    logger.error(f"Error processing message or command: {e} for raw message: {msg.value().decode('utf-8')}. Skipping and committing.")
                    consumer.commit(message=msg, asynchronous=False)

    except KeyboardInterrupt:
        logger.info("Consumer interrupted by user.")
    except KafkaException as ke:
        logger.error(f"Critical KafkaException in consumer: {ke}")
    except Exception as e:
        logger.error(f"Unexpected critical error in consumer: {e}", exc_info=True)
    finally:
        consumer.close()
        logger.info("Kafka consumer closed.")
        close_mongo_connection()
        logger.info("MongoDB connection closed after consumer shutdown.")

if __name__ == '__main__':
    # Set default environment variables if not provided (useful for local testing)
    os.environ.setdefault('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092')
    os.environ.setdefault('KAFKA_TOPIC_NAME', 'kyc_events')
    os.environ.setdefault('MONGO_DETAILS', 'mongodb://localhost:27017')

    logger.info("Starting Kafka consumer (CQRS version) directly for testing...")
    consume_events()
