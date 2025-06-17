# Dockerfile for Python Microservice Template
FROM python:3.9-slim-buster

# Environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV POETRY_VERSION=1.5.1 # Or a newer stable version
ENV POETRY_HOME="/opt/poetry"
ENV POETRY_NO_INTERACTION=1 # Ensure Poetry does not ask for interactive input
ENV PATH="$POETRY_HOME/bin:$PATH"

# Install Poetry and build dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && curl -sSL https://install.python-poetry.org | python - \
    && apt-get remove -y --auto-remove curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /usr/src/app

# Copy Poetry project files
COPY pyproject.toml poetry.lock /usr/src/app/
# Using poetry.lock without asterisk, assuming it's always present for builds.

# Install dependencies (excluding dev dependencies, install into system Python)
# Configure Poetry to not create a virtual env within the Docker image
RUN poetry config virtualenvs.create false \
    && poetry install --no-dev --no-root --no-ansi
    # --no-root: Do not install the project itself yet, code will be copied next.

# Copy application code
# This copies the content of python_microservice_template/ (the build context)
# into /usr/src/app/ in the image.
# This means main.py, app/, infra/ will be directly under /usr/src/app/
COPY . /usr/src/app/

# Expose the port the app runs on
EXPOSE 8000

# Command to run the application
# main.py is now at /usr/src/app/main.py
# uvicorn needs to find main:app
# WORKDIR is /usr/src/app, so main.py is directly accessible.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
