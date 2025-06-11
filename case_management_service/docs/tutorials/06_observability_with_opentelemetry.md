# Tutorial 6: Observability with OpenTelemetry

Observability is crucial for understanding the behavior, performance, and health of microservices. In this project, we leverage OpenTelemetry (OTel) for a comprehensive observability solution encompassing structured logging, distributed tracing, and custom metrics.

## 1. Why Observability?

In a distributed system like a microservices architecture, understanding what's happening can be challenging. Observability provides insights through three main pillars:

*   **Logging:** Recording discrete events that happen over time. Structured logs (like JSON) make these easier to parse, search, and analyze.
*   **Tracing (Distributed Tracing):** Tracking a single request or operation as it flows through multiple services or components. This helps identify bottlenecks and understand dependencies.
*   **Metrics:** Aggregated numerical data representing the health and performance of the system over time (e.g., request counts, error rates, latencies).

OpenTelemetry provides a vendor-agnostic set of APIs, SDKs, and tools to instrument, generate, collect, and export telemetry data.

## 2. OpenTelemetry Setup (`app/observability.py`)

The core OpenTelemetry setup is centralized in `case_management_service/app/observability.py`.

### a. `setup_opentelemetry(service_name: str)`

This function initializes the OTel SDK for tracing and metrics:

*   **Resource:** A `Resource` object is created to associate all telemetry with the service (e.g., `service.name = "case-management-api"` or `"case-management-consumer"`).
    ```python
    # Snippet from app/observability.py
    from opentelemetry.sdk.resources import Resource, SERVICE_NAME as ResourceAttributesServiceName
    # ...
    resource = Resource(attributes={
        ResourceAttributesServiceName: service_name,
    })
    ```
*   **TracerProvider:**
    *   An OTel `TracerProvider` is configured with the resource.
    *   **Console Exporter:** A `ConsoleSpanExporter` is always added via a `BatchSpanProcessor` for local debugging (prints trace data to the console).
    *   **OTLP Exporter (gRPC):** If `settings.OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` is configured in `app/config.py`, an `OTLPSpanExporter` is added to send trace data to an OpenTelemetry collector or compatible backend via gRPC.
    *   The configured `TracerProvider` is set globally using `trace.set_tracer_provider(tracer_provider)`.
*   **MeterProvider:**
    *   An OTel `MeterProvider` is configured with the resource.
    *   **Console Exporter:** A `ConsoleMetricExporter` is always added via a `PeriodicExportingMetricReader` for local debugging (prints metrics to the console periodically).
    *   **OTLP Exporter (gRPC):** If `settings.OTEL_EXPORTER_OTLP_METRICS_ENDPOINT` is configured, an `OTLPMetricExporter` is added to send metric data.
    *   The configured `MeterProvider` is set globally using `metrics.set_meter_provider(meter_provider)`.

This setup function is called at the entry point of both the FastAPI application (`app/main.py`) and the Kafka consumer script (`infrastructure/kafka/consumer.py` when run standalone).

### b. Tracer and Meter Instances

Global tracer and meter instances are obtained in `app/observability.py` after the providers are (expected to be) set:
```python
# Snippet from app/observability.py
from opentelemetry import trace, metrics
# ...
tracer = trace.get_tracer("case_management_service.tracer")
meter = metrics.get_meter("case_management_service.meter")
```
These instances are then imported and used by other modules to create spans or record metrics.

## 3. Structured Logging (`app/observability.py`)

We use `python-json-logger` for structured JSON logging.

*   **`setup_json_logging()`:** This function (called when `app/observability.py` is imported) configures the root logger:
    *   It uses `jsonlogger.JsonFormatter`.
    *   The log format string includes `%(otelTraceID)s` and `%(otelSpanID)s`. When OpenTelemetry tracing is active and a log statement occurs within an active span, these fields are automatically populated in the `LogRecord`. This allows correlating logs with traces.
    *   Log level is configured via `settings.LOG_LEVEL`.
    ```python
    # Snippet from app/observability.py (formatter part)
    from pythonjsonlogger import jsonlogger
    # ...
    formatter = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(module)s %(funcName)s %(lineno)d %(otelTraceID)s %(otelSpanID)s %(message)s",
        rename_fields={"levelname": "level", "name": "logger_name", "asctime": "timestamp"},
    )
    ```
*   All loggers obtained via `logging.getLogger(__name__)` in other modules will inherit this JSON formatting.

## 4. Distributed Tracing

### a. Auto-instrumentation

OpenTelemetry provides libraries to automatically instrument popular frameworks and libraries.
*   **FastAPI:** `FastAPIInstrumentor.instrument_app(app)` is called in `app/main.py`. This automatically creates spans for incoming HTTP requests, capturing details like URL, method, and status code.
*   **PyMongo:** `PymongoInstrumentor().instrument()` is called in `app/main.py`'s startup event. This automatically creates spans for MongoDB operations, showing database calls, query details (sanitized), and duration.

### b. Manual/Custom Tracing

For more granular insights into specific parts of our application, we create custom spans:

*   **Kafka Consumer (`infrastructure/kafka/consumer.py`):**
    *   A parent span `kafka_message_received` (`SpanKind.CONSUMER`) is created for each message processed.
    *   **Context Propagation:** `extract_trace_context_from_kafka_headers(msg.headers())` (from `app/observability.py`) is used to attempt to extract an incoming trace context from Kafka message headers. If found, the new span becomes a child of this incoming trace, linking distributed operations.
    *   A child span `dispatch_command_from_kafka` (`SpanKind.INTERNAL`) is created for the command transformation and dispatch logic.
    *   Spans include relevant attributes (e.g., Kafka topic, partition, offset, client ID) and events (e.g., "MessageDecodedSuccessfully", "OffsetCommitted").
    *   Errors are recorded on spans using `span.record_exception(e)` and status set with `span.set_status(Status(StatusCode.ERROR, ...))`.

*   **Command Handlers (`core/commands/handlers.py`):**
    *   Handlers typically operate within the span created by the Kafka consumer (or an API endpoint if commands are triggered via HTTP).
    *   They enrich the current span by adding attributes (`span.set_attribute("command.name", ...)\`) or events (\`span.add_event("CreateCaseCommandHandlerStarted")\`).

*   **Event Projectors (`core/events/projectors.py\`):**
    *   The `project_event_with_tracing_and_metrics` wrapper function creates a new span (`SpanKind.INTERNAL`) for each projector execution (e.g., `projector.CaseCreated.project_case_created`).
    *   This span captures projector-specific attributes and records success or failure.

## 5. Custom Metrics

Custom metrics provide quantitative data about application performance and behavior. They are defined in `app/observability.py` using the global `meter` instance.

*   **`kafka_messages_consumed_counter = meter.create_counter(...)`**:
    *   Incremented in `infrastructure/kafka/consumer.py` each time a message is successfully consumed.
    *   Attributes: `topic`, `kafka_partition`.
*   **`case_creation_latency_histogram = meter.create_histogram(...)`**:
    *   Records the duration (in seconds) of the critical path from when a command is created from a Kafka message to when the primary domain events for that case/company are persisted. This is recorded in `infrastructure/kafka/consumer.py` within the `dispatch_command` function.
    *   Attributes: `command.type`, `success`.
*   **`domain_events_processed_counter = meter.create_counter(...)`**:
    *   Incremented in `core/events/projectors.py` (via the wrapper) each time an event is successfully processed by a projector.
    *   Attributes: `projector.name`.
*   **`domain_events_by_type_counter = meter.create_counter(...)`**:
    *   Also incremented by projectors, but includes an `event.type` attribute for more granular counting.

## 6. Configuration for OTLP Exporters

As mentioned, traces and metrics can be exported via OTLP. This is configured using environment variables (managed by `app/config.py:AppSettings`):

*   `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`: e.g., `http://localhost:4317` (for gRPC)
*   `OTEL_EXPORTER_OTLP_METRICS_ENDPOINT`: e.g., `http://localhost:4317` (for gRPC)

If these are set, the OTel SDK will attempt to send telemetry data to the specified collector endpoint.

## 7. Viewing Telemetry Data

*   **Console:** By default (if no OTLP endpoints are set, or in addition to them), traces and metrics are printed to the console. This is useful for local development.
*   **OpenTelemetry Collector & Backends:** For more persistent storage, analysis, and visualization, you would typically deploy an OpenTelemetry Collector that receives data via OTLP and then forwards it to one or more backends:
    *   **Tracing Backends:** Jaeger, Zipkin, Grafana Tempo, etc.
    *   **Metrics Backends:** Prometheus (often scraped by it or pushed via a gateway), Grafana Mimir, etc.
    *   **Logging Backends:** Elasticsearch/OpenSearch (with Kibana/OpenSearch Dashboards), Grafana Loki, etc. (Logs can be correlated with traces using trace/span IDs).

Setting up these backends is outside the scope of this microservice's codebase but is the typical way to consume OTLP data in a production-like environment.

This comprehensive observability setup is vital for operating and maintaining the Case Management Microservice effectively.

Proceed to: [**Tutorial 7: Unit Testing Strategy**](./07_unit_testing_strategy.md)
