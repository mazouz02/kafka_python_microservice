# Dockerfile for Case Management Service (using Poetry)

# Use an official Python runtime as a parent image
FROM python:3.9-slim-buster

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV POETRY_VERSION=2.1.3
ENV POETRY_HOME="/opt/poetry"
ENV PATH="$POETRY_HOME/bin:$PATH"
ENV UVICORN_RELOAD_FLAG=""
# Install Poetry
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && curl -sSL https://install.python-poetry.org | python - \
    && apt-get remove -y --auto-remove curl \
    && rm -rf /var/lib/apt/lists/*

# Set work directory
WORKDIR /usr/src/app

# Copy only files necessary for installing dependencies first, to leverage Docker cache
# These paths are relative to the build context (project root)
COPY ./case_management_service/pyproject.toml ./case_management_service/poetry.lock /usr/src/app/
# The pyproject.toml and poetry.lock are now in /usr/src/app/

# Configure Poetry to not create virtual environments within the project directory in Docker
# and install dependencies into the system's site-packages.
# Ensure this runs in the directory where pyproject.toml is, which is now /usr/src/app
RUN poetry config virtualenvs.create false \
    && poetry install --without dev --no-interaction --no-ansi --no-root
    # --no-dev: Do not install development dependencies
    # --no-interaction: Do not ask any interactive questions
    # --no-ansi: Disable ANSI output
    # --no-root: Do not install the project itself (as we'll COPY the source code next)

# Copy the entire project source code into the container
# This should come *after* installing dependencies to optimize Docker layer caching.
# This copies the 'case_management_service' directory from host into '/usr/src/app/case_management_service' in image
COPY ./case_management_service /usr/src/app/case_management_service

# Startup script (remains the same as it executes Python commands)
# The startup.sh was created in a previous step by the Dockerfile itself.
# Re-create it here to ensure it's part of this Dockerfile version.
RUN echo '#!/bin/sh' > /usr/src/app/startup.sh && \
    echo 'set -e' >> /usr/src/app/startup.sh && \
    echo '' >> /usr/src/app/startup.sh && \
    echo 'echo "Container Args: $@" ' >> /usr/src/app/startup.sh && \
    echo '' >> /usr/src/app/startup.sh && \
    echo '# Default to running API if no args given' >> /usr/src/app/startup.sh && \
    echo 'if [ -z "$1" ]; then' >> /usr/src/app/startup.sh && \
    echo '    COMMAND="api"' >> /usr/src/app/startup.sh && \
    echo 'else' >> /usr/src/app/startup.sh && \
    echo '    COMMAND=$1' >> /usr/src/app/startup.sh && \
    echo 'fi' >> /usr/src/app/startup.sh && \
    echo '' >> /usr/src/app/startup.sh && \
    # PYTHONPATH needs to allow imports like 'from case_management_service.app.main'
    # Since our code is now in /usr/src/app/case_management_service,
    # and pyproject.toml (which defines the "case-management-service" package for Poetry)
    # was temporarily at /usr/src/app for `poetry install`,
    # for Python to find `case_management_service.app...`, the directory /usr/src/app
    # needs to be in PYTHONPATH, because inside /usr/src/app is the case_management_service folder.
    echo 'export PYTHONPATH=/usr/src/app:$PYTHONPATH' >> /usr/src/app/startup.sh && \
    echo '' >> /usr/src/app/startup.sh && \
    echo 'if [ "$COMMAND" = "api" ]; then' >> /usr/src/app/startup.sh && \
    echo '    echo "Starting Uvicorn server for FastAPI app..."' >> /usr/src/app/startup.sh && \
    echo '    exec uvicorn case_management_service.app.main:app \' >> /usr/src/app/startup.sh && \
    echo '         --host 0.0.0.0 --port ${PORT:-8000} ${UVICORN_RELOAD_FLAG}' >> /usr/src/app/startup.sh && \
    echo 'elif [ "$COMMAND" = "consumer" ]; then' >> /usr/src/app/startup.sh && \
    echo '    echo "Starting Kafka consumer..."' >> /usr/src/app/startup.sh && \
    echo '    exec python -u -m case_management_service.infrastructure.kafka.consumer' >> /usr/src/app/startup.sh && \
    echo 'else' >> /usr/src/app/startup.sh && \
    echo '    echo "Unknown command: $COMMAND"' >> /usr/src/app/startup.sh && \
    echo '    echo "Available commands: api, consumer"' >> /usr/src/app/startup.sh && \
    echo '    exit 1' >> /usr/src/app/startup.sh && \
    echo 'fi' >> /usr/src/app/startup.sh && \
    chmod +x /usr/src/app/startup.sh

# Expose port (remains the same)
EXPOSE 8000

# Default command (remains the same, uses startup.sh)
CMD ["/usr/src/app/startup.sh", "api"]
