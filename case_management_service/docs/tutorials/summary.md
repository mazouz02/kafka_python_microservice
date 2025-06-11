# Case Management Microservice Tutorials

Welcome to the tutorial series for the Case Management Microservice! These tutorials aim to provide a detailed, step-by-step guide to understanding its architecture, components, and features, enabling you to build similar microservices.

## Tutorial Index

1.  [**Introduction and Project Overview**](./00_introduction_and_project_overview.md)
    *   Purpose of the microservice.
    *   High-level features and architecture.
    *   Tools and technologies used.
    *   Prerequisites.
2.  [**Project Structure and Setup**](./01_project_structure_and_setup.md)
    *   Detailed walkthrough of the project layout (`app`, `core`, `infrastructure`).
    *   Setting up the development environment with Poetry.
    *   Configuration management.
3.  [**CQRS and Event Sourcing Deep Dive**](./02_cqrs_and_event_sourcing_deep_dive.md)
    *   Core principles with examples from this project.
    *   Commands, Domain Events, Event Store, Projectors, Read Models.
4.  [**Kafka Integration: Consumer and Producer**](./03_kafka_integration_consumer_and_producer.md)
    *   Kafka Consumer: Connection, message processing, error handling.
    *   Kafka Producer: Sending outbound events (e.g., for notifications).
5.  [**MongoDB Interaction**](./04_mongodb_interaction.md)
    *   Connecting to MongoDB.
    *   Storing and retrieving domain events (Event Store).
    *   Managing read models.
6.  [**FastAPI and API Design**](./05_fastapi_and_api_design.md)
    *   FastAPI application setup.
    *   API Routers and request handling.
    *   Pydantic for validation.
    *   Dependency Injection.
7.  [**Observability with OpenTelemetry**](./06_observability_with_opentelemetry.md)
    *   Structured Logging.
    *   Distributed Tracing (auto and custom).
    *   Custom Metrics.
    *   Exporting telemetry.
8.  [**Unit Testing Strategy**](./07_unit_testing_strategy.md)
    *   Approach to testing different components (handlers, projectors, API, etc.).
    *   Using `unittest` and `unittest.mock`.
    *   Running tests with Poetry.
9.  [**Dockerization and Local Deployment**](./08_dockerization_and_local_deployment.md)
    *   Understanding the `Dockerfile`.
    *   Using `docker-compose.yml` for local development.
10. [**Feature Walkthrough: Company & Beneficial Owner Modeling**](./09_feature_walkthrough_company_bo_modeling.md)
    *   Design and implementation details.
    *   Relevant models, commands, events, and tests.
11. [**Feature Walkthrough: Awaiting Documents System**](./10_feature_walkthrough_awaiting_documents.md)
    *   Design and implementation details.
    *   Relevant models, commands, events, APIs, and tests.
12. [**Feature Walkthrough: Configurable Notifications**](./11_feature_walkthrough_notifications.md)
    *   Design and implementation details.
    *   Relevant models, events, clients, producer, and tests.
13. [**Conclusion and Next Steps**](./12_conclusion_and_next_steps.md)
    *   Summary and potential future enhancements.

Please proceed through the tutorials in order for the best learning experience.
