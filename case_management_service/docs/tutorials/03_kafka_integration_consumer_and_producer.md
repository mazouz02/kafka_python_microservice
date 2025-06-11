# Tutorial 3: Kafka Integration - Consumer and Producer

This tutorial focuses on how the Case Management Microservice integrates with Apache Kafka for consuming client data events and producing notification events. We use the `confluent-kafka` Python library.

## 1. Kafka Consumer (`infrastructure/kafka/consumer.py`)

The Kafka consumer is responsible for ingesting raw data (typically about new or updated clients) from an upstream Kafka topic. This data then kicks off the internal processing within our microservice.

### a. Configuration and Initialization

*   **Dependencies:** The primary dependency is `confluent-kafka`.
*   **Configuration:** Key Kafka consumer settings are managed via `app/config.py:AppSettings` and sourced from environment variables. These include:
    *   `KAFKA_BOOTSTRAP_SERVERS`: List of Kafka broker addresses.
    *   `KAFKA_TOPIC_NAME`: The topic from which to consume messages (e.g., `kyc_events`).
    *   `KAFKA_CONSUMER_GROUP_ID`: The consumer group ID for this service.
    *   Other settings like `auto.offset.reset` (`earliest`) and `enable.auto.commit` (`False` for manual commits) are set directly in the consumer configuration dictionary.

    ```python
    # Snippet from infrastructure/kafka/consumer.py
    from case_management_service.app.config import settings
    from confluent_kafka import Consumer, KafkaError, KafkaException # Ensure KafkaException is imported if used

    logger = logging.getLogger(__name__)

    def consume_kafka_events():
        logger.info("Initializing Kafka consumer...")
        conf = {
            'bootstrap.servers': settings.KAFKA_BOOTSTRAP_SERVERS,
            'group.id': settings.KAFKA_CONSUMER_GROUP_ID,
            'auto.offset.reset': 'earliest',
            'enable.auto.commit': False
        }
        consumer = Consumer(conf)
        # ...
    ```
*   **Database Connection:** The consumer also initializes a connection to MongoDB via `connect_to_mongo()` at startup and closes it on shutdown, as it primarily stores raw events via `add_raw_event_to_store`.

### b. Message Polling Loop

The core of the consumer is an infinite loop that continuously polls Kafka for new messages:
```python
# Snippet from infrastructure/kafka/consumer.py
    consumer.subscribe([settings.KAFKA_TOPIC_NAME])
    logger.info(f"Kafka consumer subscribed to {settings.KAFKA_TOPIC_NAME} ...")

    while True:
        msg = consumer.poll(timeout=1.0) # Poll with a timeout
        if msg is None:
            continue # No message, continue polling

        if msg.error():
            # Handle Kafka errors (e.g., EOF, authentication, etc.)
            if msg.error().code() == KafkaError._PARTITION_EOF:
                continue
            else:
                logger.error(f"Kafka error: {msg.error()}...")
                consumer.commit(message=msg, asynchronous=False) # Commit to skip
                continue

        # If no error, process the message
        # ... (message processing logic) ...
```
The `consumer.poll(timeout=1.0)` attempts to fetch a message, waiting up to 1 second.

### c. Message Deserialization and Validation

Once a message is received:
1.  **Trace Context Extraction:** If OpenTelemetry is used and upstream producers include trace context in headers, it's extracted using `extract_trace_context_from_kafka_headers(msg.headers())` (from `app/observability.py`).
2.  **Span Creation:** A new OpenTelemetry span (`kafka_message_received`) is created for processing this message, linked to any parent trace context.
3.  **Deserialization:** The message value (assumed to be UTF-8 encoded JSON) is decoded: `message_data = json.loads(msg.value().decode('utf-8'))`.
4.  **Raw Event Storage:** The raw, successfully decoded JSON payload is saved to a `raw_events` MongoDB collection using `add_raw_event_to_store` (from `infrastructure/database/raw_event_store.py`). This provides an audit trail.
5.  **Pydantic Validation:** The `message_data` dictionary is then validated against the Pydantic model `KafkaMessage` (defined in `infrastructure/kafka/schemas.py`):
    ```python
    # Snippet from infrastructure/kafka/consumer.py (within the try block)
    validated_message = KafkaMessage(**message_data)
    # KafkaMessage includes validators for 'version', 'traitement_type',
    # and conditional requirements for 'company_profile' and 'beneficial_owners'.
    ```
    If validation fails, Pydantic raises a `ValidationError`, which is caught, logged, and the message offset is committed to prevent reprocessing.

### d. Transforming to Command and Dispatching

*   If message validation is successful, the `validated_message` (a `KafkaMessage` instance) is passed to an async helper function `dispatch_command`.
*   **`dispatch_command(validated_message: KafkaMessage)`:**
    *   This function runs within its own OpenTelemetry span (`dispatch_command_from_kafka`).
    *   It transforms the `KafkaMessage` into a specific command object (e.g., `CreateCaseCommand` from `core/commands/models.py`).
    *   It then calls the appropriate command handler (e.g., `handle_create_case_command` from `core/commands/handlers.py`) with the command.
    ```python
    # Snippet from infrastructure/kafka/consumer.py
    async def dispatch_command(validated_message: KafkaMessage):
        with tracer.start_as_current_span("dispatch_command_from_kafka", ...):
            # ... (set span attributes) ...
            create_case_cmd = CreateCaseCommand(
                client_id=validated_message.client_id,
                # ... map other fields ...
                traitement_type=validated_message.traitement_type,
                company_profile=validated_message.company_profile,
                # ...
            )
            # ... (add event to span, record latency metric) ...
            case_id = await handle_create_case_command(create_case_cmd)
            # ... (log, set more span attributes) ...
    ```
    *   The main synchronous `consume_kafka_events` loop calls this async function using `asyncio.run(dispatch_command(validated_message))`.

### e. Error Handling and Offset Management

*   **Kafka Errors:** Errors from `consumer.poll()` (like connectivity issues) are logged. If it's a message-specific error that's not just EOF, the offset is committed to skip the problematic message.
*   **Deserialization/Validation Errors:** `json.JSONDecodeError` or Pydantic's `ValidationError` are caught. The error is logged, the OpenTelemetry span is marked as errored, and the message offset is committed. This is a "skip-on-error" or "poison pill" handling strategy.
*   **Manual Offset Commits:** `enable.auto.commit` is set to `False`. Offsets are committed manually using `consumer.commit(message=msg, asynchronous=False)` *after* a message has been successfully processed OR after a processing error has been handled (to skip it). This provides at-least-once processing semantics.

### f. Graceful Shutdown

The consumer loop can be interrupted by `KeyboardInterrupt` (Ctrl+C). The `finally` block ensures that the Kafka consumer (`consumer.close()`) and MongoDB connection (`close_mongo_connection()`) are closed gracefully.

## 2. Kafka Producer (`infrastructure/kafka/producer.py`)

The Kafka producer is used to send domain events (specifically `NotificationRequiredEvent` in our current implementation) to other microservices via Kafka.

### a. Configuration and Initialization (`KafkaProducerService` class)

*   **Producer Configuration:** The `KafkaProducerService` class takes `bootstrap_servers` (from `app/config.py:settings`) in its constructor. Additional producer configurations (`linger.ms`, `acks`, compression, etc.) can be added to `self.producer_config`.
*   **Instance Management:** A lazily initialized global instance is managed by `get_kafka_producer()`.
*   **Lifecycle:** `startup_kafka_producer()` and `shutdown_kafka_producer()` are provided to start/stop an internal polling loop for delivery reports and to flush the producer on shutdown. These are hooked into the FastAPI app's lifecycle events in `app/main.py`.

    ```python
    # Snippet from infrastructure/kafka/producer.py
    class KafkaProducerService:
        def __init__(self, bootstrap_servers: str):
            self.producer_config = {'bootstrap.servers': bootstrap_servers}
            self.producer = Producer(self.producer_config)
            # ... other attributes for polling loop ...
    ```

### b. Producing Messages

*   **`produce_message(topic: str, message: BaseModel, key: Optional[str], ...)`:**
    *   Takes a Pydantic `BaseModel` object as the message.
    *   Serializes the message to a JSON string using `message.model_dump_json()`.
    *   Calls `self.producer.produce()` to send the message to the specified `topic`, with an optional `key` and a delivery report callback.
    ```python
    # Snippet from infrastructure/kafka/producer.py
    def produce_message(self, topic: str, message: BaseModel, ...):
        value_json = message.model_dump_json()
        self.producer.produce(
            topic,
            value=value_json.encode('utf-8'),
            key=key.encode('utf-8') if key else None,
            callback=self._delivery_report
        )
    ```

### c. Delivery Reports

*   **`_delivery_report(self, err, msg)`:** A callback function used by the Confluent Kafka client. It's invoked once for each produced message to indicate success or failure.
    *   Logs errors if `err` is not `None`.
    *   Logs success information (topic, key, partition, offset) if delivery was successful.
*   **Polling Loop (`_poll_loop`)**: The `KafkaProducerService` runs an internal asyncio loop (`self.producer.poll(0.1)`) to ensure delivery reports are processed. This is important because the Confluent producer is asynchronous.

### d. Flushing and Shutdown

*   **`flush(timeout: float)`:** Calls `self.producer.flush()` to ensure all buffered messages are sent before shutdown or a critical point.
*   **`shutdown_kafka_producer()` (global helper):** Calls `flush()` and stops the internal polling loop.

## 3. Usage Example (Notification Event)

In `core/commands/handlers.py`, after a `NotificationRequiredEvent` is created and saved locally:
```python
# Snippet from core/commands/handlers.py (handle_create_case_command)
from case_management_service.infrastructure.kafka.producer import get_kafka_producer
from case_management_service.app.config import settings

# ... (after notification_event is created) ...
try:
    kafka_producer = get_kafka_producer()
    kafka_producer.produce_message(
        topic=settings.NOTIFICATION_KAFKA_TOPIC,
        message=notification_event, # The Pydantic event model
        key=case_id # Partition by case_id
    )
    logger.info(f"NotificationRequiredEvent for case {case_id} published to Kafka ...")
except Exception as e:
    logger.error(f"Failed to publish NotificationRequiredEvent ...: {e}")
```

This setup provides robust consumption of input events and reliable production of outbound events, forming key integration points for the microservice.

Proceed to: [**Tutorial 4: MongoDB Interaction**](./04_mongodb_interaction.md)
