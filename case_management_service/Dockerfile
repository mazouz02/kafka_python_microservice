# Dockerfile for Case Management Service

# Use an official Python runtime as a parent image
FROM python:3.9-slim-buster

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set work directory
WORKDIR /usr/src/app

# Install system dependencies (if any - e.g., for librdkafka if not handled by wheels)
# RUN apt-get update && apt-get install -y --no-install-recommends build-essential librdkafka-dev

# Install pipenv if you were using it, or install requirements directly
# For requirements.txt:
COPY ./case_management_service/requirements.txt /usr/src/app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire project (or just the service code) into the container
# If .dockerignore is used, it can exclude venv, .git, etc.
# The COPY command below assumes the Docker build context is the parent of case_management_service
# So, ./case_management_service refers to the service directory within that context.
COPY ./case_management_service /usr/src/app/case_management_service

# Define how the Uvicorn server for FastAPI should be run
# Also, define how the Kafka consumer can be run.
# We might use a startup script to run both, or define them as separate commands.

# Create a startup script
# This script will allow running either the API or the Consumer, or both (e.g. with a process manager like supervisord)
# For simplicity now, we'll have it take an argument.
# The startup.sh will be created inside the image, so its content is part of the RUN command.
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
    echo '# Ensure PYTHONPATH is set correctly if modules are structured under case_management_service' >> /usr/src/app/startup.sh && \
    echo 'export PYTHONPATH=/usr/src/app:$PYTHONPATH' >> /usr/src/app/startup.sh && \
    echo '' >> /usr/src/app/startup.sh && \
    echo 'if [ "$COMMAND" = "api" ]; then' >> /usr/src/app/startup.sh && \
    echo '    echo "Starting Uvicorn server for FastAPI app..."' >> /usr/src/app/startup.sh && \
    echo '    exec uvicorn case_management_service.app.main:app --host 0.0.0.0 --port ${PORT:-8000} --reload ${UVICORN_RELOAD_FLAG:---no-reload}' >> /usr/src/app/startup.sh && \
    echo 'elif [ "$COMMAND" = "consumer" ]; then' >> /usr/src/app/startup.sh && \
    echo '    echo "Starting Kafka consumer..."' >> /usr/src/app/startup.sh && \
    echo '    exec python -u case_management_service.infrastructure.kafka.consumer.py' >> /usr/src/app/startup.sh && \
    echo 'else' >> /usr/src/app/startup.sh && \
    echo '    echo "Unknown command: $COMMAND"' >> /usr/src/app/startup.sh && \
    echo '    echo "Available commands: api, consumer"' >> /usr/src/app/startup.sh && \
    echo '    exit 1' >> /usr/src/app/startup.sh && \
    echo 'fi' >> /usr/src/app/startup.sh && \
    chmod +x /usr/src/app/startup.sh

# Expose port (though Uvicorn --port will determine it)
EXPOSE 8000

# Default command to run the API via startup script
CMD ["/usr/src/app/startup.sh", "api"]
