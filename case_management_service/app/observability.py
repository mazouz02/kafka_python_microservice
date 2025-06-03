from case_management_service.app.config import settings # Added import
import logging
import os # os is still used by some parts, e.g. service_name default in setup_opentelemetry if not overridden
from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader, ConsoleMetricExporter
from opentelemetry.sdk.resources import Resource, SERVICE_NAME as ResourceAttributesServiceName
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from pythonjsonlogger import jsonlogger

# Get our service's specific logger
# It's good practice to get it early, so it's available for setup messages.
logger = logging.getLogger("case_management_service") # This name can be more dynamic if needed

def setup_json_logging():
    # Configure root logger primarily. Child loggers will inherit.
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
    # Use LOG_LEVEL from settings
    log_level = settings.LOG_LEVEL.upper()
    root_logger.setLevel(log_level)

    logger.setLevel(log_level)
    logger.info(f"JSON logging configured at level {log_level}.")


def setup_opentelemetry(service_name: str): # service_name is now mandatory
    # setup_json_logging() # Called at module load time now.

    resource = Resource(attributes={
        ResourceAttributesServiceName: service_name,
    })

    tracer_provider = TracerProvider(resource=resource)

    console_span_exporter = ConsoleSpanExporter()
    tracer_provider.add_span_processor(BatchSpanProcessor(console_span_exporter))

    # Use OTEL_EXPORTER_OTLP_TRACES_ENDPOINT from settings
    if settings.OTEL_EXPORTER_OTLP_TRACES_ENDPOINT:
        logger.info(f"Configuring OTLP Span Exporter. Endpoint: {settings.OTEL_EXPORTER_OTLP_TRACES_ENDPOINT}")
        otlp_span_exporter = OTLPSpanExporter(endpoint=settings.OTEL_EXPORTER_OTLP_TRACES_ENDPOINT, insecure=True)
        tracer_provider.add_span_processor(BatchSpanProcessor(otlp_span_exporter))
    else:
        logger.info("OTLP Span Exporter not configured (OTEL_EXPORTER_OTLP_TRACES_ENDPOINT not set in settings). Using Console for spans.")

    trace.set_tracer_provider(tracer_provider)
    logger.info(f"OpenTelemetry TracerProvider configured for service: {service_name}.")

    console_metric_exporter = ConsoleMetricExporter()
    metric_reader_console = PeriodicExportingMetricReader(console_metric_exporter, export_interval_millis=5000)

    metric_readers = [metric_reader_console]

    # Use OTEL_EXPORTER_OTLP_METRICS_ENDPOINT from settings
    if settings.OTEL_EXPORTER_OTLP_METRICS_ENDPOINT:
        logger.info(f"Configuring OTLP Metric Exporter. Endpoint: {settings.OTEL_EXPORTER_OTLP_METRICS_ENDPOINT}")
        otlp_metric_exporter = OTLPMetricExporter(endpoint=settings.OTEL_EXPORTER_OTLP_METRICS_ENDPOINT, insecure=True)
        otlp_metric_reader = PeriodicExportingMetricReader(otlp_metric_exporter, export_interval_millis=5000)
        metric_readers.append(otlp_metric_reader)
    else:
        logger.info("OTLP Metric Exporter not configured (OTEL_EXPORTER_OTLP_METRICS_ENDPOINT not set in settings). Using Console for metrics.")

    meter_provider = MeterProvider(resource=resource, metric_readers=metric_readers)
    metrics.set_meter_provider(meter_provider)
    logger.info(f"OpenTelemetry MeterProvider configured for service: {service_name}.")

# Initialize OpenTelemetry related counters/metrics if they are defined here
# For example, if kafka_messages_consumed_counter was defined here:
# meter = metrics.get_meter(__name__)
# kafka_messages_consumed_counter = meter.create_counter(...)
# domain_events_processed_counter = meter.create_counter(...)
# domain_events_by_type_counter = meter.create_counter(...)
# These are defined in step 9.6 in core/events/projectors.py and kafka consumer,
# they should get the global meter provider.
# For now, ensuring the setup functions are correct.

setup_json_logging()
