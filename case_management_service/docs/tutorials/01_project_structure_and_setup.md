# Tutorial 1: Project Structure and Setup

This tutorial dives into the project's directory structure and guides you through setting up your local development environment. A well-organized structure is key to maintaining a scalable and understandable microservice.

## 1. Project Directory Structure

Our Case Management Microservice is organized with a clear separation of concerns, drawing inspiration from Clean Architecture and Hexagonal Architecture (Ports and Adapters) principles. The main Python package is `case_management_service`, which houses the application logic.

Here's a breakdown of the key directories within `case_management_service/`:

```
case_management_service/
├── app/ # FastAPI application, API routing, configuration, observability
│   ├── api/ # Contains API routers for different resources
│   │   └── routers/
│   │       ├── __init__.py
│   │       ├── cases.py
│   │       ├── documents.py
│   │       ├── health.py
│   │       ├── persons.py
│   │       └── raw_events.py
│   ├── __init__.py
│   ├── config.py # Pydantic settings management (environment variables, .env file)
│   ├── main.py # FastAPI app instantiation, middleware, router inclusion, lifecycle events
│   └── observability.py # OpenTelemetry setup (logging, tracing, metrics)
│
├── core/ # Core business logic, independent of web frameworks or infrastructure details
│   ├── __init__.py
│   ├── commands/ # CQRS Command side: models and handlers
│   │   ├── __init__.py
│   │   ├── handlers.py # Command handler functions (e.g., handle_create_case_command)
│   │   └── models.py # Pydantic models for Commands (e.g., CreateCaseCommand)
│   └── events/ # Domain Events and their projectors
│       ├── __init__.py
│       ├── models.py # Pydantic models for Domain Events (e.g., CaseCreatedEvent)
│       └── projectors.py # Event projector functions and the EVENT_PROJECTORS map
│
├── infrastructure/ # Interaction with external systems (databases, message brokers, services)
│   ├── __init__.py
│   ├── config_service_client.py # Client for the external configuration service
│   ├── database/ # MongoDB interaction logic
│   │   ├── __init__.py
│   │   ├── connection.py # MongoDB connection setup and utilities
│   │   ├── document_requirements_store.py # CRUD for document requirements read model
│   │   ├── event_store.py # Saving and retrieving domain events
│   │   ├── read_models.py # Querying/updating general read models (cases, persons, etc.)
│   │   └── schemas.py # Pydantic models for MongoDB documents (read models, stored events)
│   └── kafka/ # Kafka interaction logic
│       ├── __init__.py
│       ├── consumer.py # Kafka consumer setup and message processing loop
│       ├── producer.py # Kafka producer utility for publishing events
│       └── schemas.py # Pydantic models for Kafka message structures
│
├── tests/ # Unit tests, mirroring the source code structure
│   ├── __init__.py
│   ├── app/
│   ├── core/
│   │   ├── commands/
│   │   └── events/
│   └── infrastructure/
│       ├── database/
│       └── kafka/
│
├── docs/ # Detailed documentation for the project
│   ├── tutorials/ # This tutorial series
│   │   ├── summary.md # Table of contents for tutorials
│   │   └── ... (individual tutorial files)
│   ├── 01_architecture.md
│   └── ... (other detailed documentation files)
│
├── .gitignore
├── Dockerfile # For building the service's Docker image
├── poetry.lock # Poetry lock file for deterministic dependency resolution
└── pyproject.toml # Project metadata and dependencies (Poetry)

# Files at the project root (parent of case_management_service/):
# .env.example
# docker-compose.yml
# .dockerignore
# README.md (Main project README, linking to case_management_service/README.md or docs)
```

### Key Principles of this Structure:

*   **`app` (Presentation Layer):** Responsible for handling external interactions, primarily HTTP requests via FastAPI. It knows about `core` and `infrastructure` to delegate tasks but doesn't contain business logic itself.
*   **`core` (Application & Domain Layer):** This is the heart of the microservice. It contains the pure business logic (command handlers, domain events, projectors determining read model updates). It has NO dependency on `app` or specific details of `infrastructure` (like knowing it's FastAPI or MongoDB). This makes the core logic portable and highly testable.
*   **`infrastructure` (Infrastructure Layer):** Provides concrete implementations for external concerns like database access, message queue interactions, and calls to other services. It implements interfaces or uses data structures defined by `core` or takes simple data types.

This separation ensures that changes in one layer (e.g., switching from FastAPI to another web framework, or from MongoDB to another database for read models) have minimal impact on the other layers, especially the `core` business logic.

## 2. Setting Up the Development Environment

We use [Poetry](https://python-poetry.org/) for dependency management and packaging.

### Prerequisites:
*   Python 3.9 or higher installed.
*   Git installed.
*   Poetry installed. If you don't have Poetry, follow the instructions [here](https://python-poetry.org/docs/#installation).

### Steps:

1.  **Clone the Repository:**
    If you haven't already, clone the project repository to your local machine.
    ```bash
    git clone <repository_url>
    cd <project_root_directory> # This is the directory containing 'case_management_service/' and 'docker-compose.yml'
    ```

2.  **Navigate to the Service Directory:**
    The Python package and Poetry project are defined within the `case_management_service` directory.
    ```bash
    cd case_management_service
    ```
    You should see the `pyproject.toml` file in this directory.

3.  **Install Dependencies with Poetry:**
    Poetry will read the `pyproject.toml` file, resolve the dependencies (and use `poetry.lock` if present for exact versions), create a virtual environment (by default), and install all necessary packages.
    ```bash
    poetry install
    ```
    This command installs both main dependencies and development dependencies (like `pytest`, `flake8`, `black`, `isort`).

4.  **Activate the Virtual Environment (Optional but Recommended):**
    Poetry creates and manages its own virtual environments. To work within this environment directly in your shell (e.g., to run Python scripts or linters without prefixing with `poetry run`):
    ```bash
    poetry shell
    ```
    You should see your shell prompt change, indicating you're now in the project's virtual environment. To exit, simply type `exit`.

    Alternatively, you can run any command within the Poetry environment using `poetry run <command>\`. For example:
    ```bash
    poetry run python -m unittest discover tests/
    poetry run flake8 .
    ```

## 3. Configuration Management

Application configuration is handled centrally using Pydantic's `BaseSettings` in `case_management_service/app/config.py`.

### `app/config.py`
This file defines an `AppSettings` class that loads configuration values from environment variables and, optionally, from a `.env` file.

Key configurations include:
*   MongoDB connection details (`MONGO_DETAILS`, `DB_NAME`)
*   Kafka broker addresses and topic names (`KAFKA_BOOTSTRAP_SERVERS`, `KAFKA_TOPIC_NAME`, etc.)
*   Observability settings (`LOG_LEVEL`, OTLP exporter endpoints, service names)
*   External service URLs (`CONFIG_SERVICE_URL`)

### `.env` File for Local Development
For local development (when not using Docker Compose, or to override Docker Compose environment variables locally if your Docker setup sources it), you can create a `.env` file in the **project root directory** (i.e., at the same level as your `docker-compose.yml\` file, one level above `case_management_service/`).

Poetry itself doesn't directly load `.env` files into the environment when you run `poetry install` or `poetry shell`. However, `pydantic-settings` (used in `app/config.py`) *can* be configured to load a `.env` file. Our `AppSettings` class is set up to do this:
```python
# In app/config.py
class AppSettings(BaseSettings):
    # ... other settings ...
    class Config:
        env_file = ".env" # Looks for .env in the current working directory
        env_file_encoding = "utf-8"
        extra = "ignore"
```
This means if a `.env` file exists where the application *runs*, Pydantic will load it.
*   When running with `docker-compose up`, environment variables are set directly in the `docker-compose.yml` file.
*   When running Python scripts directly for development (e.g., `poetry run python case_management_service/infrastructure/kafka/consumer.py` from the project root, or if your IDE runs from project root), a `.env` file in the project root will be loaded by `AppSettings`.

An example structure for your `.env` file can be found in `.env.example` in the project root. Copy it to `.env` and customize the values for your local setup (e.g., if you're running Kafka/MongoDB directly on your host machine outside of the project's Docker Compose).

**Example `.env` content (for local direct execution):**
```env
MONGO_DETAILS="mongodb://localhost:27017"
DB_NAME="case_management_db_local_direct"
KAFKA_BOOTSTRAP_SERVERS="localhost:29092" # External Kafka port
KAFKA_TOPIC_NAME="kyc_events_local_direct"
# ... other variables ...
```

With the project structure understood and your environment set up, you're ready to explore the specific components of the microservice in the subsequent tutorials.

Proceed to: [**Tutorial 2: CQRS and Event Sourcing Deep Dive**](./02_cqrs_and_event_sourcing_deep_dive.md)
