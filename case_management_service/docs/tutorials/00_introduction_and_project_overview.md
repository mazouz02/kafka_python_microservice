# Tutorial 0: Introduction and Project Overview

Welcome to the first tutorial in our series on building the Case Management Microservice! This series is designed to walk you through the concepts, design, and implementation details of a modern, event-driven microservice. By the end, you should have a solid understanding of how its various components work together and be ableto apply these patterns to your own projects.

## 1. Purpose of the Microservice

The **Case Management Microservice** serves as a foundational component in a larger system designed for **Know Your Customer (KYC)** and **Know Your Business (KYB)** processes. Its primary responsibilities are:

*   **Ingesting client data:** Receiving information about new individual clients (KYC) or business clients (KYB) from upstream systems (e.g., bank onboarding systems, insurance company systems) via Kafka events.
*   **Core Data Onboarding:** Creating and managing core profiles for these clients, including:
    *   Basic case information (`traitement_type` like KYC/KYB, case type).
    *   Company profiles for KYB cases (registration details, addresses, etc.).
    *   Beneficial owner information for companies.
    *   Associated persons and their roles (e.g., directors, contacts).
*   **Document Requirement Management:** Determining and tracking documents that are required for a given case or entity based on configurable rules. This includes managing the status of these document requirements (e.g., Awaiting Upload, Uploaded).
*   **Triggering Notifications:** Emitting events to signal that a notification (e.g., welcome email, SMS alert) should be sent by a separate communication microservice. This is configurable based on rules fetched from an external configuration service.
*   **Providing a Queryable State:** Maintaining up-to-date read models of cases, companies, persons, etc., that can be queried via a RESTful API.

This microservice acts as the system of record for the initial onboarding and core profile data of clients.

## 2. Key Features Implemented

This tutorial series will cover a microservice with the following key features:

*   **Event-Driven Ingestion:** Consumes client data from Kafka topics.
*   **CQRS/Event Sourcing:** Implements Command Query Responsibility Segregation and uses Event Sourcing as the pattern for state management. All changes are captured as domain events.
*   **KYC/KYB Data Modeling:** Handles distinct data structures and processing logic for both individual (KYC) and business (KYB) clients, including company profiles and beneficial owners.
*   **Configurable Document Tracking:** Determines necessary documents based on client/case type and tracks their status.
*   **Configurable External Notifications:** Publishes events to trigger notifications via other services, based on rules from a configuration service.
*   **RESTful API:** Exposes endpoints (built with FastAPI) for querying read models and potentially triggering certain actions.
*   **Observability:** Integrated with OpenTelemetry for structured logging, distributed tracing, and custom metrics.
*   **Containerized:** Dockerfile and Docker Compose for local development and deployment.
*   **Testable:** Comprehensive unit tests for various components.
*   **Modern Dependency Management:** Uses Poetry.

## 3. High-Level Architecture

The microservice employs a layered, event-driven architecture based on CQRS and Event Sourcing principles.

```mermaid
graph LR
    subgraph External Systems
        Kafka_Upstream[Kafka (Client Data Topic)]
        ConfigService[Configuration Service (External HTTP)]
        CommunicationService[Communication Service (Consumes Notification Events)]
    end

    subgraph Case Management Microservice
        direction LR
        subgraph Infrastructure In
            KafkaConsumer[Kafka Consumer]
        end

        subgraph Core Logic (CQRS/ES)
            direction TB
            CmdHandler[Command Handlers]
            DomainEvents[Domain Events]
            EventStore[Event Store (MongoDB)]
            Projectors[Event Projectors]
            ReadModels[Read Models (MongoDB)]
        end

        subgraph Infrastructure Out
            direction TB
            KafkaProducer[Kafka Producer (for Notification Events)]
            ConfigClient[Config Service Client (HTTP)]
            DBInfra[MongoDB Client]
        end

        subgraph API Layer
            FastAPI[FastAPI App / Routers]
        end

        KafkaConsumer -->|Creates Command| CmdHandler
        CmdHandler -->|Generates & Saves| DomainEvents
        DomainEvents -->|Persisted To| EventStore
        EventStore -->|Read by| Projectors
        Projectors -->|Updates| ReadModels
        CmdHandler -->|Calls Config Service via| ConfigClient
        CmdHandler -->|Publishes NotificationEvent via| KafkaProducer
        FastAPI -->|Queries| ReadModels
        FastAPI -->|Dispatches Commands via (e.g. for Doc Status)| CmdHandler
        DBInfra -- Used by --> EventStore
        DBInfra -- Used by --> ReadModels
    end

    Kafka_Upstream --> KafkaConsumer
    KafkaProducer --> CommunicationService
    ConfigClient --> ConfigService

    style EventStore fill:#f9f,stroke:#333,stroke-width:2px
    style ReadModels fill:#f9f,stroke:#333,stroke-width:2px
    style CoreLogic fill:#ccf,stroke:#333,stroke-width:2px
    style InfrastructureIn fill:#cfc,stroke:#333,stroke-width:2px
    style InfrastructureOut fill:#cfc,stroke:#333,stroke-width:2px
    style APILayer fill:#ffc,stroke:#333,stroke-width:2px
```

*   **Write Path:** Kafka Consumer ingests data, transforms it into Commands. Command Handlers process these commands, validate data, and generate Domain Events. These events are the source of truth and are persisted in the Event Store (MongoDB). The Command Handler might also interact with external services (like the Configuration Service) or publish events to Kafka (like NotificationRequiredEvent).
*   **Read Path:** Event Projectors listen to Domain Events from the Event Store and update denormalized Read Models (MongoDB collections optimized for querying). The API Layer (FastAPI) serves data from these Read Models.

## 4. Tools and Technologies Used

*   **Python 3.9+:** The primary programming language.
*   **Poetry:** For dependency management and packaging.
*   **FastAPI:** A modern, fast (high-performance) web framework for building APIs with Python based on standard Python type hints.
*   **Uvicorn:** An ASGI server for running FastAPI applications.
*   **Pydantic (V2) & Pydantic-Settings:** For data validation, serialization, and settings management.
*   **Confluent Kafka Python Client (`confluent-kafka`):** For interacting with Apache Kafka.
*   **MongoDB (with PyMongo driver):** A NoSQL document database used for the event store and read models.
*   **OpenTelemetry:** For vendor-agnostic observability (tracing, metrics, logging).
    *   **Python JSON Logger:** For structured JSON logging.
    *   **OTLP Exporter:** To send telemetry data to OpenTelemetry collectors.
*   **HTTPX:** An async-capable HTTP client for interacting with external services (like the configuration service).
*   **Docker & Docker Compose:** For containerizing the application and its dependencies for local development and consistent deployments.
*   **Unittest & `unittest.mock`:** Python's built-in framework for writing unit tests.
*   **Pytest (with `pytest-asyncio`):** A popular testing framework, used here primarily for its rich assertion introspection and plugin ecosystem (though tests are written to be compatible with `unittest` runner as well).
*   **Flake8, Black, Isort:** For code linting and formatting, ensuring code quality and consistency.

## 5. Prerequisites for Following Tutorials

To get the most out of this tutorial series, you should have:

*   Basic to intermediate understanding of Python programming.
*   Familiarity with web concepts (HTTP, REST APIs).
*   Some understanding of microservice concepts.
*   Docker and Docker Compose installed and a basic understanding of how they work.
*   An IDE or text editor of your choice (e.g., VS Code).
*   Git installed for version control.
*   Access to a terminal or command line interface.

Prior experience with Kafka, MongoDB, FastAPI, or CQRS/ES is beneficial but not strictly required, as these tutorials will explain their usage in the context of this project.

We are excited to guide you through this microservice. Let's get started!

Proceed to: [**Tutorial 1: Project Structure and Setup**](./01_project_structure_and_setup.md)
