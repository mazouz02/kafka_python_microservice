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

# Get our service's specific logger
# It's good practice to get it early, so it's available for setup messages.
logger = logging.getLogger("case_management_service")

def setup_json_logging():
    # Configure root logger primarily. Child loggers will inherit.
    root_logger = logging.getLogger()

    # Avoid adding handlers multiple times if this function is called again
    if any(isinstance(h.formatter, jsonlogger.JsonFormatter) for h in root_logger.handlers):
        # Using service logger to indicate this, as root logger might not be fully set up yet.
        # Or use print() if even service logger isn't ready.
        # print("JSON logging appears to be already configured.")
        return

    logHandler = logging.StreamHandler()
    # For otelTraceID and otelSpanID to appear, OTel logging instrumentation must be active.
    # This typically happens when a tracer is active and has a logging span processor,
    # or specific loggers are instrumented. python-json-logger just formats what's in the LogRecord.
    formatter = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(module)s %(funcName)s %(lineno)d %(otelTraceID)s %(otelSpanID)s %(message)s",
        rename_fields={"levelname": "level", "name": "logger_name", "asctime": "timestamp"},
        # Add other fields you expect from OTel instrumentation if they are not standard LogRecord fields
    )
    logHandler.setFormatter(formatter)

    # Clear existing handlers from root logger
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    root_logger.addHandler(logHandler)
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    root_logger.setLevel(log_level)

    # Configure the service-specific logger as well, mainly for its level
    # It will use the root logger's handlers by default due to propagation.
    logger.setLevel(log_level)
    # logger.propagate = True # Default, ensure it propagates to root for handling

    logger.info(f"JSON logging configured at level {log_level}.")


def setup_opentelemetry(service_name: str = "case_management_service"):
    # Logging should be configured before OTel setup uses logging.
    # setup_json_logging() # Called at module load time now.

    resource = Resource(attributes={
        ResourceAttributesServiceName: service_name,
        # Add other resource attributes like deployment.environment if available
    })

    # --- Tracing Setup ---
    tracer_provider = TracerProvider(resource=resource)

    # Console exporter for local debugging
    console_span_exporter = ConsoleSpanExporter()
    tracer_provider.add_span_processor(BatchSpanProcessor(console_span_exporter))

    otlp_traces_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
    if otlp_traces_endpoint:
        logger.info(f"Configuring OTLP Span Exporter. Endpoint: {otlp_traces_endpoint}")
        otlp_span_exporter = OTLPSpanExporter(endpoint=otlp_traces_endpoint, insecure=True) # insecure=True for http
        tracer_provider.add_span_processor(BatchSpanProcessor(otlp_span_exporter))
    else:
        logger.info("OTLP Span Exporter not configured (OTEL_EXPORTER_OTLP_TRACES_ENDPOINT not set). Using Console for spans.")

    trace.set_tracer_provider(tracer_provider)
    logger.info("OpenTelemetry TracerProvider configured.")

    # --- Metrics Setup ---
    console_metric_exporter = ConsoleMetricExporter()
    metric_reader_console = PeriodicExportingMetricReader(console_metric_exporter, export_interval_millis=5000)

    metric_readers = [metric_reader_console]

    otlp_metrics_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT")
    if otlp_metrics_endpoint:
        logger.info(f"Configuring OTLP Metric Exporter. Endpoint: {otlp_metrics_endpoint}")
        otlp_metric_exporter = OTLPMetricExporter(endpoint=otlp_metrics_endpoint, insecure=True) # insecure=True for http
        otlp_metric_reader = PeriodicExportingMetricReader(otlp_metric_exporter, export_interval_millis=5000)
        metric_readers.append(otlp_metric_reader)
    else:
        logger.info("OTLP Metric Exporter not configured (OTEL_EXPORTER_OTLP_METRICS_ENDPOINT not set). Using Console for metrics.")

    meter_provider = MeterProvider(resource=resource, metric_readers=metric_readers)
    metrics.set_meter_provider(meter_provider)
    logger.info("OpenTelemetry MeterProvider configured.")

# Call JSON logging setup when this module is imported.
# OTel setup should be called by application entry points.
setup_json_logging()
