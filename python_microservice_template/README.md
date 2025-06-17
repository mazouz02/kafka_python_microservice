# Python Microservice Template

This is a template for creating Python microservices using FastAPI, Poetry, and incorporating best practices for observability, CQRS/ES (optional), and containerization.

## Project Structure

(Refer to `docs/01_architecture.md` in a fully fleshed-out service for a detailed explanation. For this template, it's:)

*   `/app`: Contains the FastAPI application, API routers, domain models (read/write), and application services (command/query/event handlers).
*   `/infra`: Infrastructure concerns like database connections, message broker clients, OpenTelemetry setup, configuration, and dependency injection providers.
*   `/main.py`: FastAPI application entry point.
*   `/tests`: Unit and integration tests.
*   `Dockerfile`: For building the service container image.
*   `docker-compose.yml`: For local development orchestration.
*   `pyproject.toml`: Poetry dependency and project management.
*   `.env.example`: Example environment variables.

## Prerequisites

*   Python 3.9+
*   Poetry (`pip install poetry` or see official docs for other methods)
*   Docker & Docker Compose

## Getting Started

1.  **Clone this template repository.**
    ```bash
    # git clone ... (or copy this template)
    cd python_microservice_template
    ```

2.  **Install Dependencies using Poetry:**
    ```bash
    poetry install
    ```
    This will create a virtual environment (if not already in one) and install all dependencies from `pyproject.toml` and `poetry.lock`.

3.  **Activate Virtual Environment (optional but recommended for direct script execution):**
    ```bash
    poetry shell
    ```

4.  **Configuration:**
    *   Copy `.env.example` to `.env`.
    *   Update variables in `.env` as needed for your local setup (e.g., `SERVICE_NAME`, `OTEL_EXPORTER_OTLP_ENDPOINT_HTTP`).
    *   Configuration is loaded by `infra/config.py` using Pydantic's `BaseSettings`.

## Running the Service Locally

### Using Docker Compose (Recommended for full environment)

This starts the application and any defined dependencies (like Jaeger for OTel traces).

```bash
docker-compose up --build -d
```
*   API will be available at: `http://localhost:8000` (e.g., health check at `http://localhost:8000/api/v1/health`)
*   Swagger UI: `http://localhost:8000/docs`
*   Jaeger UI (if started by Docker Compose): `http://localhost:16686`

To stop:
```bash
docker-compose down
```

### Using Uvicorn Directly (with Poetry)

Ensure your `.env` file is configured.
```bash
poetry run uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## Running Tests

From the `python_microservice_template` directory:
```bash
poetry run pytest tests/
# or for more verbose unittest output:
poetry run python -m unittest discover -s tests -p "test_*.py"
```

## Next Steps when using this Template

1.  **Rename the package** in `pyproject.toml` (`name = ...`) and update directory names if needed.
2.  **Update `SERVICE_NAME`** in `.env.example` and `infra/config.py` defaults.
3.  **Flesh out `app/models/` and `app/services/`** with your specific domain logic.
4.  **Implement your API endpoints** in `app/api/v1/endpoints/`.
5.  **Add database/messaging interactions** in `infra/db/` and `infra/messaging/`.
6.  **Expand unit and integration tests** in `tests/`.
7.  **Update this README** and create detailed documentation in a `/docs` folder.
