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
