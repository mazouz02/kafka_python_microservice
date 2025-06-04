# Architecture Overview

This document details the architecture of the Case Management Microservice.

## Guiding Principles

*   **Domain-Driven Design (DDD)**: Focusing on the core domain and business logic.
*   **CQRS (Command Query Responsibility Segregation)**: Separating read and write operations to optimize each path.
*   **Event Sourcing (ES)**: Persisting all state changes as a sequence of immutable domain events. Read models are derived from these events.
*   **Microservice Architecture**: Designed as a standalone service with clear API boundaries and event-based communication for decoupling.
*   **Layered Architecture / Clean Architecture**: Separating concerns into distinct layers:
    *   **App (Presentation/API)**: Handles HTTP requests, API routing, and initial request validation. (Located in `case_management_service/app/`)
    *   **Core (Application/Domain Logic)**: Contains the primary business logic, including command handlers, domain event definitions, and event projectors. This layer is independent of specific frameworks or infrastructure. (Located in `case_management_service/core/`)
    *   **Infrastructure**: Manages interactions with external systems like databases (MongoDB), message brokers (Kafka), and external services (e.g., Configuration Service). (Located in `case_management_service/infrastructure/`)

## Directory Structure

(This section can be expanded from the main README's structure overview, providing more detail on the role of each module and key files within `app`, `core`, and `infrastructure`.)

*   `case_management_service/`
    *   `app/`: FastAPI application, API routers (`api/`), configuration (`config.py`), observability setup.
    *   `core/`:
        *   `commands/`: Command Pydantic models and their handlers.
        *   `events/`: Domain Event Pydantic models and event projectors.
    *   `infrastructure/`:
        *   `database/`: MongoDB connection, schemas, event store implementation, read model query/update functions, document requirements store.
        *   `kafka/`: Kafka consumer, Kafka message schemas, Kafka producer.
        *   `config_service_client.py`: Client for the external configuration service.
    *   `tests/`: Unit tests, mirroring the source structure.
    *   `docs/`: This detailed documentation.
    *   `pyproject.toml`: Project metadata and dependencies (Poetry).
    *   `Dockerfile`: For building the service container.
*   `docker-compose.yml`: For local development orchestration.
*   `kubernetes/`: Kubernetes deployment manifests.

## Key Components and Flow (CQRS/ES)

(This section would detail the flow of data, similar to what's been discussed: Kafka Ingest -> Command -> Command Handler -> Domain Event(s) -> Event Store -> Event Projector(s) -> Read Model(s) -> API Queries. Include diagrams if possible in a richer MD environment.)

### Write Path (Commands & Events)
1.  **Kafka Ingestion**: The Kafka consumer in `infrastructure/kafka/consumer.py` receives messages.
2.  **Command Creation**: The consumer validates the message and transforms it into a Command object (defined in `core/commands/models.py`).
3.  **Command Handling**: The command is dispatched to a handler in `core/commands/handlers.py`.
4.  **Domain Logic & Event Generation**: The command handler executes business rules and generates one or more Domain Events (defined in `core/events/models.py`).
5.  **Event Persistence**: These domain events are saved to the Event Store (MongoDB via `infrastructure/database/event_store.py`). This is the source of truth.
6.  **Event Dispatch (Internal & External)**:
    *   **Internal**: Saved events are dispatched to local projectors.
    *   **External**: Specific events (e.g., `NotificationRequiredEvent`) may be published to external Kafka topics for other services.

### Read Path (Queries & Read Models)
1.  **Event Projection**: Event Projectors in `core/events/projectors.py` subscribe to domain events.
2.  **Read Model Update**: Upon receiving relevant events, projectors update denormalized Read Models (MongoDB collections, schemas in `infrastructure/database/schemas.py`, updated via functions in `infrastructure/database/read_models.py` or specific stores like `document_requirements_store.py`).
3.  **API Queries**: The API layer (`app/api/routers/`) queries these read models to serve client requests.

## Design Patterns Used
*   **CQRS**
*   **Event Sourcing**
*   **Repository Pattern** (Implicitly for data access in `infrastructure/database/` stores)
*   **Dependency Injection** (Leveraged by FastAPI for API handlers, and conceptually for service dependencies)
*   **(Future considerations based on user feedback)**: Strategy, Adapter, Proxy for more complex scenarios.

(Further sections would elaborate on each component, data flow, error handling, etc.)
