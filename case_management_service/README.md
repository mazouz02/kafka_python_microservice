# Case Management Microservice (Summary)

This project implements a Case Management microservice using Python, FastAPI, Kafka, MongoDB, and OpenTelemetry. It follows a CQRS and Event Sourcing architectural pattern. Key features include KYC/KYB data ingestion, company and beneficial owner modeling, configurable document requirement tracking, and event-driven notifications.

**For detailed information, please see the full documentation in the [`/docs`](./docs/index.md) directory.**
*(Consider serving the `/docs` folder with a static site generator like MkDocs for better readability and navigation if this project grows).*

## Quick Links to Documentation

*   [**Architecture Overview**](./docs/01_architecture.md)
*   [**API Guide**](./docs/02_api_guide.md)
*   [**Kafka Event Contracts**](./docs/03_kafka_events_and_contracts.md) (Details on messages consumed and produced)
*   [**Event Sourcing & CQRS Details**](./docs/04_event_sourcing_and_cqrs.md)
*   [**Deployment Guide**](./docs/05_deployment.md) (Docker Compose, Kubernetes)
*   [**Testing Strategy**](./docs/06_testing_strategy.md) (Unit tests, End-to-End testing concepts for features)
*   [**Observability Guide**](./docs/07_observability.md) (Logging, Tracing, Metrics)
*   **Feature Guides:**
    *   [Company & Beneficial Owner Modeling](./docs/feature_guides/01_company_bo_modeling.md)
    *   [Awaiting Documents System](./docs/feature_guides/02_awaiting_documents.md)
    *   [Configurable Notifications](./docs/feature_guides/03_notifications.md)

## Key Technologies

*   Python 3.9+ / Poetry
*   FastAPI, Uvicorn
*   Confluent Kafka
*   MongoDB
*   Pydantic (V2 with Pydantic-Settings)
*   OpenTelemetry
*   Docker & Docker Compose

## Prerequisites

*   Python 3.9 or higher
*   Poetry (Dependency Management)
*   Docker Engine & Docker Compose
*   Git

## Setup and Installation

1.  **Clone the Repository:**
    ```bash
    git clone <repository_url>
    cd <project_directory_root>
    ```
2.  **Install Poetry (if not already installed):**
    Follow the official Poetry installation guide: [https://python-poetry.org/docs/#installation](https://python-poetry.org/docs/#installation)
3.  **Install Project Dependencies (using Poetry):**
    Navigate to the `case_management_service` directory (where `pyproject.toml` is located):
    ```bash
    cd case_management_service
    poetry install
    ```
    To activate the virtual environment managed by Poetry, use `poetry shell`.

## Configuration

Refer to the [Deployment Guide](./docs/05_deployment.md) and `../.env.example` (in project root) for details on environment variables and configuration. Key settings are managed in `case_management_service/app/config.py`.

## Running the Application Locally

Refer to the [Deployment Guide](./docs/05_deployment.md) for instructions on using Docker Compose.
Quick start:
```bash
# From project root (where docker-compose.yml is)
docker-compose up --build -d
```
API will be available at `http://localhost:8000/docs`.

## Running Tests

Refer to the [Testing Strategy](./docs/06_testing_strategy.md) for detailed information.
Quick start (from `case_management_service` directory, after `poetry install`):
```bash
poetry run pytest tests/
# or
poetry run python -m unittest discover -s tests -p "test_*.py"
```

## Project Structure

A brief overview:
*   `case_management_service/`: The Python package root.
    *   `app/`: FastAPI application, API routers, config, observability.
    *   `core/`: Core business logic (commands, events, handlers, projectors).
    *   `infrastructure/`: Database, Kafka clients, external service integrations.
    *   `tests/`: Unit tests.
    *   `docs/`: Detailed documentation.
*   `pyproject.toml`, `poetry.lock`: Dependency management.
*   `Dockerfile`: Container image definition.
*   `docker-compose.yml`: Local orchestration (in project root).
*   `kubernetes/`: K8s deployment manifests (in `case_management_service/kubernetes/`).

For a detailed breakdown, see [Architecture Overview](./docs/01_architecture.md).
