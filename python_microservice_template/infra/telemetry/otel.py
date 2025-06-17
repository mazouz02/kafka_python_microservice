# OpenTelemetry Setup for the Microservice Template
import logging
from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader, ConsoleMetricExporter
from opentelemetry.sdk.resources import Resource, SERVICE_NAME as ResourceAttributesServiceName
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

# OTLP Exporters (using HTTP as per pyproject.toml default)
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter as OTLPHttpTraceExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter as OTLPHttpMetricExporter

# Import application settings
# Assuming infra is a package, and config is a module within it.
from ..config import settings # Relative import from infra.config

logger = logging.getLogger(__name__)

def setup_opentelemetry(app_name: str = settings.SERVICE_NAME):
    """Configures OpenTelemetry tracing and metrics for the application."""

    resource = Resource(attributes={
        ResourceAttributesServiceName: app_name
    })

    # --- Tracer Setup ---
    tracer_provider = TracerProvider(resource=resource)
    # Console exporter for local debugging (always on for template)
    tracer_provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    logger.info("ConsoleSpanExporter configured for OpenTelemetry traces.")

    # OTLP/HTTP Exporter for Traces (if endpoint is configured)
    if settings.OTEL_EXPORTER_OTLP_ENDPOINT_HTTP:
        try:
            # Ensure the endpoint doesn't already include /v1/traces
            endpoint_url = settings.OTEL_EXPORTER_OTLP_ENDPOINT_HTTP
            if not endpoint_url.endswith("/v1/traces"):
                endpoint_url = f"{endpoint_url.rstrip('/')}/v1/traces"

            otlp_http_trace_exporter = OTLPHttpTraceExporter(
                endpoint=endpoint_url
            )
            tracer_provider.add_span_processor(BatchSpanProcessor(otlp_http_trace_exporter))
            logger.info(f"OTLP/HTTP Trace Exporter configured for endpoint: {otlp_http_trace_exporter._endpoint}") # Use internal _endpoint for logging
        except Exception as e:
            logger.error(f"Failed to configure OTLP/HTTP Trace Exporter: {e}", exc_info=True)
    else:
        logger.info("OTLP/HTTP Trace Exporter not configured (OTEL_EXPORTER_OTLP_ENDPOINT_HTTP not set).")
    trace.set_tracer_provider(tracer_provider)
    logger.info(f"OpenTelemetry TracerProvider configured for service: {app_name}.")

    # --- Meter Setup ---
    metric_readers = [PeriodicExportingMetricReader(ConsoleMetricExporter())]
    logger.info("ConsoleMetricExporter configured for OpenTelemetry metrics.")

    if settings.OTEL_EXPORTER_OTLP_ENDPOINT_HTTP:
        try:
            # Ensure the endpoint doesn't already include /v1/metrics
            endpoint_url = settings.OTEL_EXPORTER_OTLP_ENDPOINT_HTTP
            if not endpoint_url.endswith("/v1/metrics"):
                endpoint_url = f"{endpoint_url.rstrip('/')}/v1/metrics"

            otlp_http_metric_exporter = OTLPHttpMetricExporter(
                endpoint=endpoint_url
            )
            metric_readers.append(PeriodicExportingMetricReader(otlp_http_metric_exporter))
            logger.info(f"OTLP/HTTP Metric Exporter configured for endpoint: {otlp_http_metric_exporter._endpoint}") # Use internal _endpoint for logging
        except Exception as e:
            logger.error(f"Failed to configure OTLP/HTTP Metric Exporter: {e}", exc_info=True)
    else:
        logger.info("OTLP/HTTP Metric Exporter not configured (OTEL_EXPORTER_OTLP_ENDPOINT_HTTP not set).")

    meter_provider = MeterProvider(resource=resource, metric_readers=metric_readers)
    metrics.set_meter_provider(meter_provider)
    logger.info(f"OpenTelemetry MeterProvider configured for service: {app_name}.")

def instrument_fastapi_app(app): # app is FastAPI instance
    """Instruments a FastAPI application for OpenTelemetry tracing."""
    # Check if a non-default TracerProvider is set (i.e., setup_opentelemetry was effective)
    if isinstance(trace.get_tracer_provider(), TracerProvider) and \
       trace.get_tracer_provider().resource != Resource.get_empty():
        FastAPIInstrumentor.instrument_app(app)
        logger.info("FastAPI application instrumented with OpenTelemetry (tracing).")
    else:
        logger.warning("OpenTelemetry TracerProvider is default/empty or not SDK TracerProvider. FastAPI instrumentation skipped.")

# Note: For structured logging (e.g., with python-json-logger) to include trace IDs,
# it would typically be configured after OTel SDK is set up, often in main.py or a logging bootstrap module.
# This template's otel.py focuses on OTel SDK trace/metric setup.
# Global tracer/meter instances for custom instrumentation could be defined here:
# tracer = trace.get_tracer(settings.SERVICE_NAME, "0.1.0") # Or a specific instrumenting module name
# meter = metrics.get_meter(settings.SERVICE_NAME, "0.1.0")
