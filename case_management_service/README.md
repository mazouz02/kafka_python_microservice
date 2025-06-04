# Case Management Microservice

This project implements a Case Management microservice using Python, FastAPI, Kafka, MongoDB, and OpenTelemetry. Key features include initial case and KYB data ingestion (companies, beneficial owners), management of document requirements, and a configurable system to trigger notifications (e.g., on case creation) by publishing events to Kafka for consumption by other microservices.
It follows a CQRS and Event Sourcing architectural pattern to handle events, process commands, and maintain read models.

## Key Technologies

*   **Python 3.9+**
*   **FastAPI**: For building the RESTful API.
*   **Confluent Kafka**: For asynchronous event streaming.
*   **MongoDB**: As the data store for the event store and read models.
*   **Pydantic**: For data validation and settings management.
*   **OpenTelemetry**: For distributed tracing, metrics, and structured logging.
*   **Docker & Docker Compose**: For containerization and local development orchestration.
*   **Unittest**: For unit testing.

## Project Structure Overview

The project is organized into a modular structure to clearly separate concerns and reflect the CQRS pattern:

*   `case_management_service/`: Root directory for the microservice.
    *   `app/`: Contains the FastAPI application setup, API routers, configuration, and observability initialization.
        *   `api/routers/`: Houses individual FastAPI routers for different API resources (e.g., cases, persons, health, documents).
        *   `config.py`: Manages application settings using Pydantic's `BaseSettings`.
        *   `main.py`: The main FastAPI application entry point, including router aggregation.
        *   `observability.py`: Configures logging and OpenTelemetry.
    *   `core/`: Contains the core business logic and CQRS components.
        *   `commands/`: Defines command models and their handlers.
        *   `events/`: Defines domain event models and event projectors (which update read models).
    *   `infrastructure/`: Manages interactions with external systems like databases and message brokers.
        *   `database/`: Handles MongoDB connections, event store operations, read model queries/updates, document requirement storage, and database schemas.
        *   `kafka/`: Contains Kafka consumer setup, message polling, Kafka message schemas, and a Kafka producer utility.
    *   `tests/`: Contains unit tests, mirroring the source code structure.
    *   `Dockerfile`: Defines the Docker image for the service.
*   `docker-compose.yml`: (In project root) Orchestrates local deployment of the service and its dependencies (Kafka, MongoDB).
*   `.env.example`: (In project root) Example environment file.
*   `README.md`: This file.
*   `requirements.txt`: Python dependencies.

## Key Domain Entities

The service primarily deals with the following domain concepts, especially after the introduction of KYB features:

*   **Case**: Represents a KYC or KYB onboarding instance, identified by a unique `case_id`. It includes a `traitement_type` (KYC/KYB).
*   **Person**: Represents an individual involved in a case, such as a primary KYC subject or a person linked to a company (e.g., director, contact). Stored with a unique `person_id`.
*   **Company Profile**: For KYB cases, this stores detailed information about a legal entity, identified by a unique `company_id`. The Case can be linked to this Company Profile.
*   **Beneficial Owner (BO)**: Represents a beneficial owner of a company, identified by a unique `beneficial_owner_id` and linked to a `company_id`. Includes details of the person and their ownership/control.
*   **Required Document**: Represents a document that needs to be collected for a specific entity (Person or Company) within a Case. Tracks type, status (e.g., AWAITING_UPLOAD, VERIFIED), and other metadata.

## Prerequisites

*   Python 3.9 or higher.
*   Pip (Python package installer).
*   Docker Engine.
*   Docker Compose.
*   Git (for cloning the repository).

## Setup and Installation

1.  **Clone the Repository:**
    ```bash
    git clone <repository_url>
    cd <project_directory_containing_docker-compose.yml>
    ```

2.  **Create a Python Virtual Environment (Recommended):**
    Navigate to the `case_management_service` directory:
    ```bash
    cd case_management_service
    python -m venv .venv
    source .venv/bin/activate  # On Windows: .venv\Scripts\activate
    ```

3.  **Install Dependencies:**
    Ensure your virtual environment is active.
    ```bash
    pip install -r requirements.txt
    ```

## Configuration

The application uses environment variables for configuration, managed by `case_management_service/app/config.py` via Pydantic's `BaseSettings`.

You can set these variables directly in your environment, or create a `.env` file in the project root directory (same level as `docker-compose.yml`).

**Create a `.env` file (e.g., by copying from `.env.example` if provided, or create it manually):**
```env
# MongoDB
MONGO_DETAILS="mongodb://localhost:27017" # For local run outside Docker
# MONGO_DETAILS="mongodb://mongo:27017" # For Docker Compose internal communication
DB_NAME="case_management_db_local"

# Kafka
KAFKA_BOOTSTRAP_SERVERS="localhost:29092" # For local run outside Docker (external port)
# KAFKA_BOOTSTRAP_SERVERS="kafka:9092" # For Docker Compose internal communication
KAFKA_TOPIC_NAME="kyc_events_local" # Main topic for case events
KAFKA_CONSUMER_GROUP_ID="case_management_group_local"

# Observability
LOG_LEVEL="INFO" # e.g., DEBUG, INFO, WARNING, ERROR
OTEL_EXPORTER_OTLP_TRACES_ENDPOINT= # e.g., http://localhost:4317
OTEL_EXPORTER_OTLP_METRICS_ENDPOINT= # e.g., http://localhost:4317
SERVICE_NAME_API="case-api-local"
SERVICE_NAME_CONSUMER="case-consumer-local"

# Configuration Service for Notifications (Optional)
CONFIG_SERVICE_URL= # e.g., http://localhost:8081/api/v1/notification-rules

# Kafka Topic for Outbound Notification Events
NOTIFICATION_KAFKA_TOPIC="notification_events_local"
```

**Note on Docker Compose:** The `docker-compose.yml` file sets these environment variables for the services running within Docker, often pointing to Docker network hostnames (e.g., `mongo`, `kafka`). The `.env` file is primarily for running the Python application directly on your host machine (outside Docker) for development or testing, or it can be used by Docker Compose if configured.

## Running the Application Locally (with Docker Compose)

1.  **Build and Start Services:**
    From the project root directory (where `docker-compose.yml` is located):
    ```bash
    docker-compose up --build -d
    ```
    This command will:
    *   Build the Docker image for the `case-management-api` and `case-management-consumer` services using `case_management_service/Dockerfile`.
    *   Start containers for:
        *   MongoDB (`mongo`)
        *   ZooKeeper (`zookeeper`)
        *   Kafka (`kafka`)
        *   Case Management API (`case-management-api`)
        *   Case Management Kafka Consumer (`case-management-consumer`)
    *   The `-d` flag runs containers in detached mode.

2.  **Accessing the API:**
    Once services are up, the FastAPI application will be available at:
    *   API Base: `http://localhost:8000`
    *   Swagger UI / OpenAPI Docs: `http://localhost:8000/docs`
    *   ReDoc: `http://localhost:8000/redoc`

#### Notable Endpoint Groups (under `/api/v1/` prefix via Docker Compose):
*   `/health`: System health check (no prefix).
*   `/events/raw`: For listing raw ingested events.
*   `/cases`: For querying case read models.
*   `/persons`: For querying person read models linked to cases.
*   `/documents`: For managing and querying document requirements:
    *   `POST /documents/determine-requirements`: To trigger the determination of required documents for an entity within a case.
    *   `PUT /documents/{document_requirement_id}/status`: To update the status of a specific document requirement.
    *   `GET /documents/{document_requirement_id}`: To retrieve details of a specific document requirement.
    *   `GET /documents/case/{case_id}`: To list document requirements for a specific case (path updated from `/entity/{entity_id}` for clarity).


3.  **Viewing Logs:**
    To view logs from the services:
    ```bash
    docker-compose logs -f case-management-api
    docker-compose logs -f case-management-consumer
    docker-compose logs -f kafka
    docker-compose logs -f mongo
    ```
    Use `Ctrl+C` to stop tailing logs.

4.  **Kafka Topic (`kyc_events_docker`):**
    The Kafka topic specified in `docker-compose.yml` (`KAFKA_TOPIC_NAME=kyc_events_docker`) should be auto-created by the Confluent Kafka image when the consumer or a producer first attempts to access it. If not, you might need to create it manually using Kafka tools (e.g., by exec-ing into the Kafka container). The `notification_events_docker` topic for notifications will also follow this behavior.

5.  **Stopping Services:**
    ```bash
    docker-compose down
    ```
    To remove volumes (like MongoDB data): `docker-compose down -v`

## Running Unit Tests

1.  **Ensure Dependencies are Installed** (in your local Python virtual environment if testing locally).
2.  **Set PYTHONPATH:**
    Make sure your `PYTHONPATH` includes the project root directory (the parent of `case_management_service`) if you are running tests from the project root.
    ```bash
    export PYTHONPATH=$(pwd):$PYTHONPATH  # For Linux/macOS
    # For Windows (PowerShell): $env:PYTHONPATH = "$(Get-Location);$env:PYTHONPATH"
    # For Windows (CMD): set PYTHONPATH=%CD%;%PYTHONPATH%
    ```
3.  **Run Tests:**
    From the project root directory:
    ```bash
    python -m unittest discover -s case_management_service/tests -p "test_*.py"
    ```
    Alternatively, if you have `pytest` installed:
    ```bash
    pytest case_management_service/tests/
    ```

## Testing Implemented Features

Beyond running the automated unit tests, each major feature can be tested more specifically, often involving end-to-end flows.

### 1. Core Case/Person Ingestion (KYC)

*   **Unit Tests:**
    *   Kafka message validation: `tests/infrastructure/kafka/test_kafka_schemas.py` (focus on KYC structure).
    *   Command handling for KYC: `tests/core/commands/test_command_handlers.py` (e.g., `test_handle_create_case_command_kyc_only_person`).
    *   Event projection for KYC: `tests/core/events/test_event_projectors.py` (e.g., `test_project_case_created`, `test_project_person_added_to_case_kyc`).
    *   API for KYC cases: `tests/app/test_api.py` (querying cases and persons).
*   **End-to-End Testing (Conceptual):**
    1.  Ensure Docker Compose services are running (`docker-compose up`).
    2.  Produce a Kafka message to the configured topic (e.g., `kyc_events_docker`) with `traitement_type: "KYC"` and relevant `persons` data.
        *Example Minimal KYC Kafka Message Payload (JSON):*
        ```json
        {
          "client_id": "kyc-client-001",
          "version": "1.0",
          "type": "INDIVIDUAL_STANDARD",
          "traitement_type": "KYC",
          "persons": [
            { "firstname": "John", "lastname": "Doe", "birthdate": "1990-01-15" }
          ]
        }
        ```
    3.  **Verify:**
        *   Logs from `case-management-consumer` for successful message processing.
        *   **API:** Use Swagger UI (`/docs`) or curl to query:
            *   `GET /api/v1/cases/{generated_case_id}`
            *   `GET /api/v1/persons/case/{generated_case_id}`
        *   **Database:** Check MongoDB collections:
            *   `domain_events`: Look for `CaseCreatedEvent`, `PersonAddedToCaseEvent`.
            *   `cases`: Verify the case read model.
            *   `persons`: Verify the person read model.

### 2. Company & Beneficial Owner Modeling (KYB)

*   **Unit Tests:**
    *   Kafka message validation for KYB: `tests/infrastructure/kafka/test_kafka_schemas.py`.
    *   Command handling for KYB: `tests/core/commands/test_command_handlers.py` (e.g., `test_handle_create_case_command_kyb_with_company_and_bos_and_persons`).
    *   Event projection for KYB: `tests/core/events/test_event_projectors.py` (e.g., `project_company_profile_created`, `project_beneficial_owner_added`, `project_person_linked_to_company`).
*   **End-to-End Testing (Conceptual):**
    1.  Ensure Docker Compose services are running.
    2.  Produce a Kafka message to the configured topic with `traitement_type: "KYB"`, `company_profile` data, `persons` (with roles), and `beneficial_owners` data.
        *Example Minimal KYB Kafka Message Payload (JSON):*
        ```json
        {
          "client_id": "kyb-client-002",
          "version": "1.0",
          "type": "COMPANY_STANDARD",
          "traitement_type": "KYB",
          "company_profile": {
            "registered_name": "Test Corp Ltd",
            "registration_number": "C09876",
            "country_of_incorporation": "GB",
            "registered_address": { "street": "1 Business Park", "city": "London", "country": "GB", "postal_code": "E14 5HQ" }
          },
          "persons": [
            { "firstname": "Jane", "lastname": "Director", "birthdate": "1985-03-20", "role_in_company": "Director" }
          ],
          "beneficial_owners": [
            {
              "person_details": { "firstname": "Ultimate", "lastname": "Owner", "birthdate": "1975-11-10" },
              "ownership_percentage": 75,
              "types_of_control": ["SHAREHOLDING_OVER_25"],
              "is_ubo": true
            }
          ]
        }
        ```
    3.  **Verify:**
        *   Logs from `case-management-consumer`.
        *   **API:** Query relevant case data. (Future: specific company/BO endpoints).
        *   **Database:** Check MongoDB collections:
            *   `domain_events`: Look for `CompanyProfileCreatedEvent`, `BeneficialOwnerAddedEvent`, `PersonLinkedToCompanyEvent`.
            *   `cases`: Verify the case links to the company.
            *   `companies`: Verify the company profile read model.
            *   `persons`: Verify linked persons (director) with roles.
            *   `beneficial_owners`: Verify BO read models.

### 3. Awaiting Documents System

*   **Unit Tests:**
    *   Database operations for documents: `tests/infrastructure/database/test_database.py` (e.g., `test_add_required_document`).
    *   Command handling for documents: `tests/core/commands/test_command_handlers.py` (e.g., `test_handle_determine_initial_document_requirements_person_kyc`, `test_handle_update_document_status_success`).
    *   Event projection for documents: `tests/core/events/test_event_projectors.py` (e.g., `test_project_document_requirement_determined`).
    *   API for documents: `tests/app/test_api.py` (e.g., `test_determine_document_requirements_api`).
*   **End-to-End Testing (Conceptual):**
    1.  Create a case (KYC or KYB) via Kafka as described above.
    2.  **Determine Requirements:** Call `POST /api/v1/documents/determine-requirements` with the `case_id`, `entity_id` (person or company ID from the created case), `entity_type`, `traitement_type`, and `case_type`.
        *Example Request Body for `determine-requirements` (JSON):*
        ```json
        {
          "case_id": "<your_case_id>",
          "entity_id": "<your_person_or_company_id>",
          "entity_type": "PERSON",
          "traitement_type": "KYC",
          "case_type": "INDIVIDUAL_STANDARD"
        }
        ```
    3.  **Verify Determination:**
        *   API: Call `GET /api/v1/documents/case/{case_id}` (using the path updated in router for listing by case) to see the list of required documents and their initial "AWAITING_UPLOAD" status.
        *   Database: Check the `document_requirements` collection.
    4.  **Update Status:** Call `PUT /api/v1/documents/{document_requirement_id}/status` for one of the generated document requirements.
        *Example Request Body for updating status (JSON):*
        ```json
        {
          "new_status": "UPLOADED",
          "updated_by_actor_id": "test_user",
          "metadata_changes": { "file_reference": "doc_xyz.pdf" }
        }
        ```
    5.  **Verify Update:**
        *   API: Call `GET /api/v1/documents/{document_requirement_id}` to check the updated status and metadata.
        *   Database: Check the updated record in `document_requirements`.

### 4. Configurable Notifications on Case Creation

*   **Unit Tests:**
    *   Configuration service client: `tests/infrastructure/test_config_service_client.py`.
    *   Kafka producer: `tests/infrastructure/kafka/test_kafka_producer.py`.
    *   Command handler logic for notifications: In `tests/core/commands/test_command_handlers.py` (e.g., `test_handle_create_case_command_kyb_sends_notification_if_configured`).
*   **End-to-End Testing (Conceptual - requires external setup):**
    1.  **Set up a mock Configuration Service:** This service should respond to POST requests at the URL specified in `CONFIG_SERVICE_URL` (e.g., `http://localhost:8081/api/v1/notification-rules/rules/match`). It should return a JSON `NotificationRule` when a matching trigger/context is sent.
        *Example Mock Config Service Response (JSON for a specific trigger):*
        ```json
        [{ "rule_id": "welcome_email_rule", "is_active": true, "notification_type": "EMAIL_WELCOME_KYC", "template_id": "KYC_WELCOME_EMAIL_V1" }]
        ```
    2.  **Set up a Kafka Consumer:** Use a generic Kafka consumer tool (e.g., `kcat`, or a simple Python script) to listen to the topic defined by `NOTIFICATION_KAFKA_TOPIC` (e.g., `notification_events_docker`).
    3.  Ensure Docker Compose services are running, and the `CONFIG_SERVICE_URL` environment variable for `case-management-api` and `case-management-consumer` points to your mock config service.
    4.  Produce a Kafka message (KYC or KYB) to create a new case.
    5.  **Verify:**
        *   Logs from `case-management-consumer` should indicate it called the config service.
        *   If a rule matched, logs should show a `NotificationRequiredEvent` being prepared and published.
        *   Your external Kafka consumer listening to the notification topic should receive the `NotificationRequiredEvent` message.
        *   Database: Check `domain_events` for the stored `NotificationRequiredEvent`.

This detailed testing guidance should help users verify each feature thoroughly.

## Observability

*   **Structured Logging**: Logs are in JSON format and include OpenTelemetry trace and span IDs (`otelTraceID`, `otelSpanID`) when a trace is active, allowing for easier log aggregation and correlation.
*   **Distributed Tracing & Metrics**: OpenTelemetry is integrated.
    *   By default, traces and metrics are exported to the **console**.
    *   To export to an OpenTelemetry Collector (e.g., Jaeger for traces, Prometheus for metrics), set the following environment variables (e.g., in your `.env` file or Docker Compose environment section):
        *   `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://<collector_host>:<collector_traces_port>` (e.g., `http://localhost:4317`)
        *   `OTEL_EXPORTER_OTLP_METRICS_ENDPOINT=http://<collector_host>:<collector_metrics_port>` (e.g., `http://localhost:4317`)
*   **Auto-instrumentation**: FastAPI requests and PyMongo database calls are automatically traced.
*   **Custom Tracing/Metrics**: Key operations like Kafka message consumption, command handling, and event projection are custom-traced and emit specific metrics.

---

This README provides a starting point. Further details on specific API endpoints, advanced configuration, or deployment to other environments would be added as the project evolves.
