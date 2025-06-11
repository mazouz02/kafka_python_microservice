# Tutorial 11: Feature Walkthrough - Configurable Notifications

This tutorial explains the "Configurable Notifications" feature. It allows the Case Management Microservice to trigger external notifications (e.g., emails, SMS) via a separate communication microservice in a decoupled and configurable manner, typically when significant events like case creation occur.

## 1. Purpose of the Feature

When a new case is created or reaches a certain milestone, it's often necessary to notify the client or internal teams. Instead of embedding notification logic directly into the case management service, this feature promotes a decoupled approach:

*   **Triggering Mechanism:** The Case Management service determines *if* a notification is needed and *what basic information* it should contain.
*   **External Configuration:** The decision to send a notification (and which one) is driven by rules fetched from an external "Configuration Microservice". This allows notification logic to be changed without redeploying the Case Management service.
*   **Decoupled Communication:** This service publishes a generic `NotificationRequiredEvent` to a dedicated Kafka topic. A separate "Communication Microservice" (not part of this project) would consume these events and handle the actual sending of emails, SMS, etc., using the appropriate templates and providers.
*   **Auditability:** The intent to send a notification is recorded as a domain event in our service's event store.

## 2. Key Data Models Involved

### a. Domain Event Model (`core/events/models.py`)

*   **`NotificationRequiredEventPayload`**:
    *   `notification_type: str`: A string identifier for the type of notification (e.g., "EMAIL_WELCOME_KYC", "SMS_CASE_INITIATED"). This is typically determined by the configuration rule.
    *   `recipient_details: Dict[str, Any]`: Flexible dictionary to hold information about the recipient. This might include direct contact details (if readily available and appropriate for this service to handle) or, more commonly, identifiers (like `user_id`, `case_id`) that the Communication Service can use to look up actual contact information.
    *   `template_id: Optional[str]`: An identifier for the specific message template to be used by the Communication Service.
    *   `language_code: Optional[str]`: Preferred language for the notification.
    *   `context_data: Dict[str, Any]`: Key-value pairs providing data to personalize the notification template (e.g., client name, case ID).
*   **`NotificationRequiredEvent(BaseEvent)`**:
    *   `payload`: An instance of `NotificationRequiredEventPayload`.
    *   `aggregate_id`: Typically the `case_id` to which the notification pertains.
    *   `event_type`: Standardized to "NotificationRequired".

### b. Configuration Service Client Model (`infrastructure/config_service_client.py`)

*   **`NotificationRule` (Pydantic Model)**: Represents the expected structure of a rule fetched from the external Configuration Microservice.
    *   Fields: `rule_id`, `is_active`, `notification_type`, `template_id`, `language_code`.

### c. Application Configuration (`app/config.py`)

New settings were added to `AppSettings`:
*   **`CONFIG_SERVICE_URL: Optional[str]`**: The base URL for the external Configuration Microservice.
*   **`NOTIFICATION_KAFKA_TOPIC: str`**: The Kafka topic to which `NotificationRequiredEvent`s are published (e.g., "notification_events").

## 3. Logic Flow and Implementation Details

The primary logic for this feature resides within the `handle_create_case_command` in `core/commands/handlers.py`.

1.  **Core Event Persistence:** The command handler first processes the `CreateCaseCommand` as usual, generating and saving core domain events like `CaseCreatedEvent`, `CompanyProfileCreatedEvent`, etc., to the local Event Store.
2.  **Check Notification Configuration:**
    *   After successfully saving core events, the handler constructs an `event_trigger` string (e.g., "CASE_CREATED_KYC_STANDARD") and a `context` dictionary based on the command's data (`traitement_type`, `case_type`, etc.).
    *   It calls `await get_notification_config(event_trigger, context)` from `infrastructure.config_service_client`.
    ```python
    # Snippet from core/commands/handlers.py
    config_service_event_trigger = f"CASE_CREATED_{command.traitement_type}_{command.case_type}".upper().replace("-", "_")
    # ... build context_service_context ...
    notification_rule = await get_notification_config(config_service_event_trigger, config_service_context)
    ```
3.  **If an Active Rule is Found:**
    *   The handler proceeds to prepare and dispatch a notification.
    *   **Gather Data:** It constructs the `recipient_details` and `context_data` for the `NotificationRequiredEventPayload`. Recipient details might involve using IDs or basic information from the command.
    *   **Create Event:** A `NotificationRequiredEvent` is instantiated. Its `aggregate_id` is the `case_id`, and its version is determined by incrementing from the latest event version for that `case_id` within the current handler's transaction.
    *   **Save Event Locally:** The `NotificationRequiredEvent` is saved to the local Event Store using `save_event()`. This ensures an audit record of the intent to notify.
    *   **Publish Event to Kafka:** The `NotificationRequiredEvent` is then published to the Kafka topic specified in `settings.NOTIFICATION_KAFKA_TOPIC` using the `KafkaProducerService` from `infrastructure/kafka/producer.py`. The `case_id` is typically used as the Kafka message key for partitioning.
    ```python
    # Snippet from core/commands/handlers.py
    if notification_rule and notification_rule.is_active:
        # ... construct notification_payload ...
        # Determine next version for the case aggregate
        current_case_aggregate_version = 0
        for evt in events_to_dispatch: # events_to_dispatch holds core events for this case
            if evt.aggregate_id == case_id and evt.version > current_case_aggregate_version:
                current_case_aggregate_version = evt.version
        notification_event_version = current_case_aggregate_version + 1

        notification_event = domain_event_models.NotificationRequiredEvent(
            aggregate_id=case_id,
            payload=notification_payload,
            version=notification_event_version
        )
        await save_event(notification_event) # Save to local event store

        kafka_producer = get_kafka_producer()
        kafka_producer.produce_message( # Publish to Kafka
            topic=settings.NOTIFICATION_KAFKA_TOPIC,
            message=notification_event,
            key=case_id
        )
    ```
4.  **No Rule / Inactive Rule / Error:** If no active rule is found, or if the `CONFIG_SERVICE_URL` is not set, or if there's an error calling the config service, the notification step is skipped (with appropriate logging). Failure to publish to Kafka is also logged but currently does not fail the main command processing.
5.  **Dispatch Core Events:** Finally, the originally generated core domain events (like `CaseCreatedEvent`) are dispatched to local projectors as usual. The `NotificationRequiredEvent` is *not* typically dispatched to local projectors unless there's a specific local need to react to it (its main purpose is external).

## 4. Infrastructure Components

*   **`infrastructure/config_service_client.py`:**
    *   Uses `httpx.AsyncClient` to make a POST request to the configured external service.
    *   Parses the JSON response into a `NotificationRule` Pydantic model (or a list of them).
    *   Includes basic error handling for HTTP errors, request errors, and JSON parsing issues.
*   **`infrastructure/kafka/producer.py`:**
    *   Provides `KafkaProducerService` which wraps `confluent_kafka.Producer`.
    *   Handles message serialization (Pydantic model to JSON).
    *   Manages an asyncio-friendly polling loop for delivery reports.
    *   Its lifecycle (`startup_kafka_producer`, `shutdown_kafka_producer`) is managed by the FastAPI application in `app/main.py`.

## 5. How to Test This Feature

### a. Unit Tests

*   **Config Service Client (`tests/infrastructure/test_config_service_client.py\`):**
    *   Tests `get_notification_config` by mocking `httpx.AsyncClient`. Scenarios include:
        *   Successful retrieval of active/inactive rules.
        *   Config service URL not set.
        *   HTTP errors, request errors, JSON decoding errors from the mocked client.
*   **Kafka Producer (`tests/infrastructure/kafka/test_kafka_producer.py\`):**
    *   Tests `KafkaProducerService.produce_message` by mocking `confluent_kafka.Producer` and verifying calls.
    *   Tests delivery report handling and lifecycle methods.
*   **Command Handler (`tests/core/commands/test_command_handlers.py\`):**
    *   The tests for `handle_create_case_command` are augmented (e.g., `test_handle_create_case_command_kyb_sends_notification_if_configured`).
    *   Mock `get_notification_config` to return different `NotificationRule` scenarios (active, inactive, None).
    *   Mock `get_kafka_producer` and its `produce_message` method.
    *   Verify that `NotificationRequiredEvent` is correctly generated, saved via `save_event`, and published via `produce_message` only when an active rule dictates.
    *   Check event payload, topic, and key.

### b. End-to-End Testing (Conceptual)

1.  **Mock/Actual Configuration Service:**
    *   **Option A (Mock):** Set up a simple mock HTTP server (e.g., using FastAPI itself or another tool) that mimics the expected API of your Configuration Microservice. Configure `CONFIG_SERVICE_URL` in your `.env` or `docker-compose.yml` to point to this mock. The mock should return predefined `NotificationRule` JSON responses based on the `event_trigger` and `context` it receives.
        *Example Mock Config Service Response (JSON for a specific trigger, assuming it returns a list):*
        ```json
        [{ "rule_id": "welcome_email_rule", "is_active": true, "notification_type": "EMAIL_WELCOME_KYC", "template_id": "KYC_WELCOME_EMAIL_V1" }]
        ```
    *   **Option B (Actual, if available):** If a dev instance of the real Configuration Service is available and accessible from your local Docker network, configure the URL to point to it.
2.  **Kafka Consumer Tool:** Use a Kafka tool (e.g., `kcat`, Conduktor, Offset Explorer, or a simple Python Kafka consumer script) to subscribe to and monitor the `NOTIFICATION_KAFKA_TOPIC` (e.g., `notification_events_docker`).
3.  **Run Services:** Start the Case Management Microservice (API and consumer), Kafka, and MongoDB using Docker Compose.
4.  **Trigger Case Creation:** Produce a Kafka message to the main data ingestion topic (e.g., `kyc_events_docker`) that you expect to trigger a notification based on your (mocked or real) configuration rules.
5.  **Verify:**
    *   **Case Management Consumer Logs:** Check for logs indicating interaction with the Configuration Service and, if applicable, the preparation and publishing of a `NotificationRequiredEvent`.
    *   **Event Store (MongoDB - `domain_events` collection):** Verify that the `NotificationRequiredEvent` was saved with the correct `case_id` as its `aggregate_id` and appropriate payload.
    *   **Notification Kafka Topic:** Your external Kafka consumer tool should receive the `NotificationRequiredEvent` message. Inspect its content (payload, key).

This feature effectively decouples notification logic from the core case processing, making the system more flexible and scalable.

Proceed to: [**Tutorial 12: Conclusion and Next Steps**](./12_conclusion_and_next_steps.md)
