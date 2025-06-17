from case_management_service.app.config import settings
import logging
import os
from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader, ConsoleMetricExporter
from opentelemetry.sdk.resources import Resource, SERVICE_NAME as ResourceAttributesServiceName
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from pythonjsonlogger import jsonlogger
# For extract_trace_context_from_kafka_headers
from opentelemetry.context import Context
from opentelemetry.propagate import extract
from opentelemetry.trace import set_span_in_context
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator



logger = logging.getLogger("case_management_service")

def setup_json_logging():
    root_logger = logging.getLogger()
    if any(isinstance(h.formatter, jsonlogger.JsonFormatter) for h in root_logger.handlers):
        return
    logHandler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(module)s %(funcName)s %(lineno)d %(otelTraceID)s %(otelSpanID)s %(message)s",
        rename_fields={"levelname": "level", "name": "logger_name", "asctime": "timestamp"},
    )
    logHandler.setFormatter(formatter)
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    root_logger.addHandler(logHandler)
    log_level = settings.LOG_LEVEL.upper()
    root_logger.setLevel(log_level)
    logger.setLevel(log_level)
    logger.info(f"JSON logging configured at level {log_level}.")

def setup_opentelemetry(service_name: str):
    resource = Resource(attributes={
        ResourceAttributesServiceName: service_name,
    })
    tracer_provider = TracerProvider(resource=resource)
    console_span_exporter = ConsoleSpanExporter()
    tracer_provider.add_span_processor(BatchSpanProcessor(console_span_exporter))
    if settings.OTEL_EXPORTER_OTLP_TRACES_ENDPOINT:
        logger.info(f"Configuring OTLP Span Exporter. Endpoint: {settings.OTEL_EXPORTER_OTLP_TRACES_ENDPOINT}")
        otlp_span_exporter = OTLPSpanExporter(endpoint=settings.OTEL_EXPORTER_OTLP_TRACES_ENDPOINT, insecure=True)
        tracer_provider.add_span_processor(BatchSpanProcessor(otlp_span_exporter))
    else:
        logger.info("OTLP Span Exporter not configured. Using Console for spans.")
    trace.set_tracer_provider(tracer_provider)
    logger.info(f"OpenTelemetry TracerProvider configured for service: {service_name}.")

    console_metric_exporter = ConsoleMetricExporter()
    metric_reader_console = PeriodicExportingMetricReader(console_metric_exporter, export_interval_millis=5000)
    metric_readers = [metric_reader_console]
    if settings.OTEL_EXPORTER_OTLP_METRICS_ENDPOINT:
        logger.info(f"Configuring OTLP Metric Exporter. Endpoint: {settings.OTEL_EXPORTER_OTLP_METRICS_ENDPOINT}")
        otlp_metric_exporter = OTLPMetricExporter(endpoint=settings.OTEL_EXPORTER_OTLP_METRICS_ENDPOINT, insecure=True)
        otlp_metric_reader = PeriodicExportingMetricReader(otlp_metric_exporter, export_interval_millis=5000)
        metric_readers.append(otlp_metric_reader)
    else:
        logger.info("OTLP Metric Exporter not configured. Using Console for metrics.")
    meter_provider = MeterProvider(resource=resource, metric_readers=metric_readers)
    metrics.set_meter_provider(meter_provider)
    logger.info(f"OpenTelemetry MeterProvider configured for service: {service_name}.")

# Call at module load time
setup_json_logging()

# --- Tracer and Meter instances ---
# These are now globally available after setup_opentelemetry is called by an entry point.
# Modules should import these instances.
tracer = trace.get_tracer("case_management_service.tracer")
meter = metrics.get_meter("case_management_service.meter")

# --- Custom Metrics Definitions ---
kafka_messages_consumed_counter = meter.create_counter(
    name="case_management.kafka.messages.consumed.total",
    description="Counts the total number of Kafka messages consumed.",
    unit="1"
)

domain_events_processed_counter = meter.create_counter(
    name="case_management.domain.events.processed.total",
    description="Counts the total number of domain events processed by projectors.",
    unit="1"
)

domain_events_by_type_counter = meter.create_counter(
    name="case_management.domain.events.type.total",
    description="Counts domain events processed, partitioned by event type.",
    unit="1"
)

case_creation_latency_histogram = meter.create_histogram(
    name="case_management.case.creation.latency.seconds",
    description="Measures the latency of case creation from command reception to event persistence.",
    unit="s"
)
logger.info("Custom metrics (Counters, Histogram) defined in observability.py.")

# --- Kafka Trace Context Extraction ---
# (Moved from consumer, as it's generic observability helper)
def extract_trace_context_from_kafka_headers(headers: list) -> Context:
    """
    Extracts OpenTelemetry trace context from Kafka message headers.
    Args:
        headers: A list of tuples (key, value_bytes) from Kafka message.
    Returns:
        An OpenTelemetry Context object, potentially with parent span info.
    """
    if not headers:
        return None

    header_dict = {key: value.decode('utf-8') for key, value in headers if value is not None}
    return TraceContextTextMapPropagator().extract(carrier=header_dict)
