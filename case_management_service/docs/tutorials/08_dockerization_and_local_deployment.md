# Tutorial 8: Dockerization and Local Deployment

This tutorial explains how the Case Management Microservice is containerized using Docker and orchestrated for local development using Docker Compose. This setup provides a consistent and isolated environment for running the service and its dependencies.

## 1. Dockerizing the Application (`Dockerfile`)

The `case_management_service/Dockerfile` is responsible for building the Docker image for our Python application (both the API and the Kafka consumer components, as they share the same codebase).

Key stages in the `Dockerfile`:

*   **Base Image:** Starts from an official Python slim image (`python:3.9-slim-buster`) to keep the image size relatively small.
    ```dockerfile
    FROM python:3.9-slim-buster
    ```
*   **Environment Variables:** Sets common Python environment variables like `PYTHONDONTWRITEBYTECODE=1` and `PYTHONUNBUFFERED=1`. It also sets up environment variables for Poetry installation (`POETRY_VERSION`, `POETRY_HOME`, and adds Poetry to `PATH`).
*   **Install Poetry:** Poetry is installed using its official `curl` installer. System dependencies like `curl` are installed for this step and then cleaned up.
    ```dockerfile
    ENV POETRY_VERSION=1.5.1 # Example version
    ENV POETRY_HOME="/opt/poetry"
    ENV PATH="$POETRY_HOME/bin:$PATH"
    RUN apt-get update && apt-get install -y --no-install-recommends curl \
        && curl -sSL https://install.python-poetry.org | python - \
        && apt-get remove -y --auto-remove curl \
        && rm -rf /var/lib/apt/lists/*
    ```
*   **Set Working Directory:** `WORKDIR /usr/src/app` sets the context for subsequent commands.
*   **Install Dependencies with Poetry:**
    1.  Copies only `pyproject.toml` and `poetry.lock` first (from the `case_management_service` directory in the build context). This leverages Docker's layer caching; if these files haven't changed, Docker can reuse the dependency layer.
    2.  Configures Poetry not to create a virtual environment within the image (`poetry config virtualenvs.create false`).
    3.  Installs dependencies using `poetry install --no-dev --no-interaction --no-ansi --no-root`.
        *   `--no-dev`: Excludes development dependencies (like `pytest`, linters) from the production image.
        *   `--no-root`: Prevents Poetry from installing the project package itself at this stage, as the source code will be copied next.
    ```dockerfile
    # Paths are relative to build context (project root)
    COPY ./case_management_service/pyproject.toml ./case_management_service/poetry.lock /usr/src/app/
    RUN poetry config virtualenvs.create false \
        && poetry install --no-dev --no-interaction --no-ansi --no-root
    ```
*   **Copy Application Code:** The entire `case_management_service` directory (containing `app`, `core`, `infrastructure`) is copied from the build context into the image at `/usr/src/app/case_management_service/`.
    ```dockerfile
    COPY ./case_management_service /usr/src/app/case_management_service
    ```
*   **Startup Script (`startup.sh`):**
    *   The Dockerfile creates a `startup.sh` script inside the image (`/usr/src/app/startup.sh`).
    *   This script takes an argument (`api` or `consumer`) to determine which process to run.
    *   It sets the `PYTHONPATH=/usr/src/app:$PYTHONPATH`. Since the application code is in `/usr/src/app/case_management_service`, Python can find the `case_management_service` package (e.g., for imports like `from case_management_service.app.main import app`).
    *   If `api`, it executes `uvicorn case_management_service.app.main:app ...`.
    *   If `consumer`, it executes `python -u case_management_service.infrastructure.kafka.consumer.py`.
    ```dockerfile
    # (Inside RUN echo ... > /usr/src/app/startup.sh)
    # export PYTHONPATH=/usr/src/app:$PYTHONPATH
    # ...
    # exec uvicorn case_management_service.app.main:app ...
    # exec python -u case_management_service.infrastructure.kafka.consumer.py
    ```
*   **Expose Port:** `EXPOSE 8000` documents that the API service within the container listens on port 8000.
*   **Default Command (`CMD`):** Specifies the default command to run when a container starts from this image: `["/usr/src/app/startup.sh", "api"]` (i.e., start the API service by default).

A `.dockerignore` file at the project root ensures that unnecessary files (like `.git`, `.venv`, `__pycache__`) are not copied into the Docker build context, keeping the image smaller and build times faster.

## 2. Local Orchestration with Docker Compose (`docker-compose.yml`)

The `docker-compose.yml` file (located at the project root) defines and orchestrates the multi-container application environment for local development.

It defines the following services:

### a. `mongo` Service
*   **Image:** Uses the official `mongo:5.0` image.
*   **Ports:** Maps host port 27017 to container port 27017.
*   **Volumes:** Uses a named volume `mongo_data` to persist MongoDB data across container restarts (`/data/db` inside the container).
*   **Network:** Connected to the custom bridge network `case_management_network`.

### b. `zookeeper` Service
*   **Image:** Uses `confluentinc/cp-zookeeper:7.3.2`. Required by the Confluent Kafka image.
*   **Ports:** Maps host port 2181 to container port 2181.
*   **Environment:** Sets `ZOOKEEPER_CLIENT_PORT` and `ZOOKEEPER_TICK_TIME`.
*   **Network:** Connected to `case_management_network`.

### c. `kafka` Service
*   **Image:** Uses `confluentinc/cp-kafka:7.3.2`.
*   **Depends On:** `zookeeper`.
*   **Ports:**
    *   `9092:9092`: For communication within the Docker network (e.g., from our application services).
    *   `29092:29092`: For communication from outside the Docker network (e.g., from your host machine if you use a Kafka tool locally).
*   **Environment:** Configures essential Kafka settings:
    *   `KAFKA_BROKER_ID`
    *   `KAFKA_ZOOKEEPER_CONNECT` (points to the `zookeeper` service).
    *   `KAFKA_LISTENER_SECURITY_PROTOCOL_MAP` and `KAFKA_ADVERTISED_LISTENERS`: Crucial for allowing Kafka to be accessible both internally within Docker (`kafka:9092`) and externally from the host (`localhost:29092`).
    *   Other settings for topic replication and Confluent platform specifics.
*   **Network:** Connected to `case_management_network`.

### d. `case-management-api` Service (Our Application - API)
*   **Build Context:** Builds the Docker image using the `Dockerfile` in the `case_management_service` directory (context is `.\`, the project root).
*   **Command:** Overrides the Dockerfile's default CMD to explicitly run the API: `["/usr/src/app/startup.sh", "api"]`.
*   **Ports:** Maps host port 8000 to container port 8000.
*   **Depends On:** `mongo` and `kafka`, so Docker Compose starts them first.
*   **Environment:** Sets environment variables that will be picked up by `app/config.py:AppSettings`.
    *   `MONGO_DETAILS=mongodb://mongo:27017` (uses service name `mongo`)
    *   `KAFKA_BOOTSTRAP_SERVERS=kafka:9092` (uses service name `kafka`)
    *   Other variables like topic names, group IDs, log levels, service names, OTel exporter endpoints, and notification-related configurations (`CONFIG_SERVICE_URL`, `NOTIFICATION_KAFKA_TOPIC`).
*   **Volumes:** Mounts the local `./case_management_service` directory to `/usr/src/app/case_management_service` in the container. This allows for live reloading of code changes during development if Uvicorn's `--reload` flag is used (which it is in our `[tool.poetry.scripts]` for `start-api`, and the Dockerfile's `startup.sh` can also support it via `UVICORN_RELOAD_FLAG`).
*   **Network:** Connected to `case_management_network`.

### e. `case-management-consumer` Service (Our Application - Consumer)
*   **Build Context:** Uses the same Docker image as the API service.
*   **Command:** Overrides the CMD to run the consumer: `["/usr/src/app/startup.sh", "consumer"]`.
*   **Depends On:** `mongo` and `kafka`.
*   **Environment:** Similar set of environment variables as the API service, ensuring it connects to the same Kafka and MongoDB instances within the Docker network. The `SERVICE_NAME_CONSUMER` is different for observability.
*   **Volumes:** Also mounts the local source code for development consistency.
*   **Network:** Connected to `case_management_network`.

### f. Volumes and Networks
*   **`mongo_data`:** A named volume for MongoDB data persistence.
*   **`case_management_network`:** A custom bridge network allowing services to communicate using their service names as hostnames.

## 3. Running the Local Environment

From the project root directory (where `docker-compose.yml` is located):

*   **Build and Start Services (Detached Mode):**
    ```bash
    docker-compose up --build -d
    ```
    The `--build` flag ensures images are rebuilt if the `Dockerfile` or source code changes. `-d` runs containers in the background.

*   **View Logs:**
    ```bash
    docker-compose logs -f <service_name>
    # e.g., docker-compose logs -f case-management-api
    # or docker-compose logs -f (to see all)
    ```

*   **Stop Services:**
    ```bash
    docker-compose down
    ```
    To also remove named volumes (like `mongo_data`):
    ```bash
    docker-compose down -v
    ```

*   **Accessing the API:**
    *   Swagger UI: `http://localhost:8000/docs`
    *   The API prefix `/api/v1/` is applied by `app/main.py` when including most routers, so actual resource paths are e.g., `http://localhost:8000/api/v1/cases`. Health check is at `http://localhost:8000/health`.

This Docker Compose setup provides a fully functional local environment for developing, testing, and running the Case Management Microservice and its dependencies.

Proceed to: [**Tutorial 9: Feature Walkthrough - Company & Beneficial Owner Modeling**](./09_feature_walkthrough_company_bo_modeling.md)
