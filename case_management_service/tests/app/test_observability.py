import pytest
from unittest.mock import patch, MagicMock, ANY
import logging
import importlib # For reloading the module

from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider # To assert against specific type
from opentelemetry.sdk.metrics import MeterProvider as SDKMeterProvider # To assert against specific type
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

# Module to test
from case_management_service.app import observability
from case_management_service.app.config import settings # To manipulate for testing

# Preserve original settings
@pytest.fixture(autouse=True)
def preserve_original_settings():
    original_log_level = settings.LOG_LEVEL
    original_otel_traces_endpoint = settings.OTEL_EXPORTER_OTLP_TRACES_ENDPOINT
    original_otel_metrics_endpoint = settings.OTEL_EXPORTER_OTLP_METRICS_ENDPOINT
    yield
    settings.LOG_LEVEL = original_log_level
    settings.OTEL_EXPORTER_OTLP_TRACES_ENDPOINT = original_otel_traces_endpoint
    settings.OTEL_EXPORTER_OTLP_METRICS_ENDPOINT = original_otel_metrics_endpoint

@pytest.fixture
def mock_logger_dependencies(mocker):
    mock_logging = mocker.patch('case_management_service.app.observability.logging')
    mock_jsonlogger = mocker.patch('case_management_service.app.observability.jsonlogger')
    # Mock the root logger and the service-specific logger retrieval
    mock_root_logger = MagicMock(spec=logging.Logger)
    mock_service_logger = MagicMock(spec=logging.Logger)

    # Configure getLogger to return the appropriate mock
    def getLogger_side_effect(name=None):
        if name == "case_management_service": # As used in observability.logger
            return mock_service_logger
        return mock_root_logger # For logging.getLogger()

    mock_logging.getLogger.side_effect = getLogger_side_effect

    # Ensure handlers list is distinct for each call if needed, or manage its state
    mock_root_logger.handlers = []

    return mock_logging, mock_jsonlogger, mock_root_logger, mock_service_logger

def test_setup_json_logging_configures_correctly(mock_logger_dependencies):
    mock_logging, mock_jsonlogger, mock_root_logger, mock_service_logger = mock_logger_dependencies
    settings.LOG_LEVEL = "INFO"

    observability.setup_json_logging()

    mock_jsonlogger.JsonFormatter.assert_called_once_with(
        fmt="%(asctime)s %(levelname)s %(name)s %(module)s %(funcName)s %(lineno)d %(otelTraceID)s %(otelSpanID)s %(message)s",
        rename_fields={"levelname": "level", "name": "logger_name", "asctime": "timestamp"},
    )
    mock_logging.StreamHandler.assert_called_once()
    log_handler_instance = mock_logging.StreamHandler.return_value
    log_handler_instance.setFormatter.assert_called_once_with(mock_jsonlogger.JsonFormatter.return_value)

    mock_root_logger.addHandler.assert_called_once_with(log_handler_instance)
    mock_root_logger.setLevel.assert_called_once_with("INFO")
    mock_service_logger.setLevel.assert_called_once_with("INFO")

    # Test idempotency: Call again, ensure no duplicate handlers
    mock_root_logger.handlers = [log_handler_instance] # Simulate handler already added
    mock_jsonlogger.JsonFormatter.reset_mock() # Reset mocks for the second call check
    mock_logging.StreamHandler.reset_mock()
    mock_root_logger.addHandler.reset_mock()

    observability.setup_json_logging()

    mock_root_logger.addHandler.assert_not_called() # Should not add handler again


@pytest.fixture
def mock_otel_sdk(mocker):
    # Common SDK components
    mock_resource_cls = mocker.patch('case_management_service.app.observability.Resource')
    mock_resource_instance = MagicMock()
    mock_resource_cls.return_value = mock_resource_instance

    # Trace components
    mock_tracer_provider_cls = mocker.patch('case_management_service.app.observability.TracerProvider')
    mock_tracer_provider_instance = MagicMock(spec=SDKTracerProvider) # Use actual class for spec
    mock_tracer_provider_cls.return_value = mock_tracer_provider_instance
    mock_batch_span_processor_cls = mocker.patch('case_management_service.app.observability.BatchSpanProcessor')
    mock_console_span_exporter_cls = mocker.patch('case_management_service.app.observability.ConsoleSpanExporter')
    mock_otlp_span_exporter_cls = mocker.patch('case_management_service.app.observability.OTLPSpanExporter')

    # Metrics components
    mock_meter_provider_cls = mocker.patch('case_management_service.app.observability.MeterProvider')
    mock_meter_provider_instance = MagicMock(spec=SDKMeterProvider) # Use actual class for spec
    mock_meter_provider_cls.return_value = mock_meter_provider_instance
    mock_periodic_reader_cls = mocker.patch('case_management_service.app.observability.PeriodicExportingMetricReader')
    mock_console_metric_exporter_cls = mocker.patch('case_management_service.app.observability.ConsoleMetricExporter')
    mock_otlp_metric_exporter_cls = mocker.patch('case_management_service.app.observability.OTLPMetricExporter')

    # Global setters
    mock_set_tracer_provider = mocker.patch('case_management_service.app.observability.trace.set_tracer_provider')
    mock_set_meter_provider = mocker.patch('case_management_service.app.observability.metrics.set_meter_provider')

    mocker.patch.object(observability.logger, 'info') # Mock logger to avoid actual logging

    return {
        "Resource": mock_resource_cls, "resource_instance": mock_resource_instance,
        "TracerProvider": mock_tracer_provider_cls, "tracer_provider_instance": mock_tracer_provider_instance,
        "BatchSpanProcessor": mock_batch_span_processor_cls,
        "ConsoleSpanExporter": mock_console_span_exporter_cls,
        "OTLPSpanExporter": mock_otlp_span_exporter_cls,
        "MeterProvider": mock_meter_provider_cls, "meter_provider_instance": mock_meter_provider_instance,
        "PeriodicExportingMetricReader": mock_periodic_reader_cls,
        "ConsoleMetricExporter": mock_console_metric_exporter_cls,
        "OTLPMetricExporter": mock_otlp_metric_exporter_cls,
        "set_tracer_provider": mock_set_tracer_provider,
        "set_meter_provider": mock_set_meter_provider,
    }

def test_setup_opentelemetry_no_otlp_endpoints(mock_otel_sdk):
    settings.OTEL_EXPORTER_OTLP_TRACES_ENDPOINT = None
    settings.OTEL_EXPORTER_OTLP_METRICS_ENDPOINT = None
    service_name = "test-service-no-otlp"

    observability.setup_opentelemetry(service_name)

    mock_otel_sdk["Resource"].assert_called_once_with(attributes={observability.ResourceAttributesServiceName: service_name})

    # Tracer assertions
    mock_otel_sdk["TracerProvider"].assert_called_once_with(resource=mock_otel_sdk["resource_instance"])
    mock_otel_sdk["ConsoleSpanExporter"].assert_called_once()
    mock_otel_sdk["BatchSpanProcessor"].assert_any_call(mock_otel_sdk["ConsoleSpanExporter"].return_value)
    mock_otel_sdk["OTLPSpanExporter"].assert_not_called()
    mock_otel_sdk["set_tracer_provider"].assert_called_once_with(mock_otel_sdk["tracer_provider_instance"])

    # Meter assertions
    mock_otel_sdk["MeterProvider"].assert_called_once_with(
        resource=mock_otel_sdk["resource_instance"],
        metric_readers=[mock_otel_sdk["PeriodicExportingMetricReader"].return_value] # Only console reader
    )
    mock_otel_sdk["ConsoleMetricExporter"].assert_called_once()
    mock_otel_sdk["PeriodicExportingMetricReader"].assert_any_call(
        mock_otel_sdk["ConsoleMetricExporter"].return_value, export_interval_millis=ANY
    )
    mock_otel_sdk["OTLPMetricExporter"].assert_not_called()
    assert mock_otel_sdk["PeriodicExportingMetricReader"].call_count == 1 # Only one reader (console)
    mock_otel_sdk["set_meter_provider"].assert_called_once_with(mock_otel_sdk["meter_provider_instance"])

def test_setup_opentelemetry_with_otlp_endpoints(mock_otel_sdk):
    traces_endpoint = "http://trace-collector:4317"
    metrics_endpoint = "http://metrics-collector:4317"
    settings.OTEL_EXPORTER_OTLP_TRACES_ENDPOINT = traces_endpoint
    settings.OTEL_EXPORTER_OTLP_METRICS_ENDPOINT = metrics_endpoint
    service_name = "test-service-with-otlp"

    observability.setup_opentelemetry(service_name)

    # Tracer assertions
    mock_otel_sdk["OTLPSpanExporter"].assert_called_once_with(endpoint=traces_endpoint, insecure=True)
    # BatchSpanProcessor called for console AND otlp
    assert mock_otel_sdk["BatchSpanProcessor"].call_count == 2
    mock_otel_sdk["BatchSpanProcessor"].assert_any_call(mock_otel_sdk["OTLPSpanExporter"].return_value)

    # Meter assertions
    mock_otel_sdk["OTLPMetricExporter"].assert_called_once_with(endpoint=metrics_endpoint, insecure=True)
    # PeriodicExportingMetricReader called for console AND otlp
    assert mock_otel_sdk["PeriodicExportingMetricReader"].call_count == 2
    mock_otel_sdk["PeriodicExportingMetricReader"].assert_any_call(mock_otel_sdk["OTLPMetricExporter"].return_value, export_interval_millis=ANY)


@patch('case_management_service.app.observability.metrics') # Patch the whole metrics module object
def test_custom_metrics_definitions(mock_otel_metrics_module, mock_otel_sdk, mocker):
    # This test is a bit complex due to metrics being defined at module import time.
    # We need to ensure that the 'meter' object used for definitions
    # is a mock that we can inspect, and it's obtained from a mocked MeterProvider.

    mock_meter_instance = MagicMock()
    # When observability.meter is initialized (metrics.get_meter_provider().get_meter(...)),
    # make it use our mock_meter_instance.
    # The global 'meter' in observability.py is set by:
    # meter = metrics.get_meter_provider().get_meter("case_management_service.meter")
    # So, we mock get_meter_provider() to return a provider that returns our mock_meter_instance.

    mock_provider_instance = MagicMock()
    mock_provider_instance.get_meter.return_value = mock_meter_instance
    mock_otel_metrics_module.get_meter_provider.return_value = mock_provider_instance

    # Call setup_opentelemetry to set the (mocked) global meter provider
    # The actual MeterProvider class is already mocked by mock_otel_sdk
    observability.setup_opentelemetry("test-service-metrics")

    # Reload the observability module to trigger re-definition of global metrics
    # This will use the mocked `metrics.get_meter_provider().get_meter()` path
    importlib.reload(observability)

    # Assertions for counters
    mock_meter_instance.create_counter.assert_any_call(
        name="case_management.kafka.messages.consumed.total",
        description="Counts the total number of Kafka messages consumed.",
        unit="1"
    )
    mock_meter_instance.create_counter.assert_any_call(
        name="case_management.domain.events.processed.total",
        description="Counts the total number of domain events processed by projectors.",
        unit="1"
    )
    mock_meter_instance.create_counter.assert_any_call(
        name="case_management.domain.events.type.total",
        description="Counts domain events processed, partitioned by event type.",
        unit="1"
    )
    # Assertion for histogram
    mock_meter_instance.create_histogram.assert_called_once_with(
        name="case_management.case.creation.latency.seconds",
        description="Measures the latency of case creation from command reception to event persistence.",
        unit="s"
    )


@patch('case_management_service.app.observability.TraceContextTextMapPropagator')
def test_extract_trace_context_from_kafka_headers(MockPropagator):
    mock_propagator_instance = MagicMock(spec=TraceContextTextMapPropagator)
    MockPropagator.return_value = mock_propagator_instance
    mock_context = MagicMock()
    mock_propagator_instance.extract.return_value = mock_context

    # Test with valid traceparent and tracestate
    headers_valid = [
        ("traceparent", b"00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"),
        ("tracestate", b"rojo=00f067aa0ba902b7")
    ]
    result_valid = observability.extract_trace_context_from_kafka_headers(headers_valid)
    expected_carrier_valid = {
        "traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",
        "tracestate": "rojo=00f067aa0ba902b7"
    }
    mock_propagator_instance.extract.assert_called_with(carrier=expected_carrier_valid)
    assert result_valid == mock_context

    # Test with only traceparent
    mock_propagator_instance.extract.reset_mock()
    headers_traceparent_only = [("traceparent", b"00-abc-def-01")]
    result_traceparent_only = observability.extract_trace_context_from_kafka_headers(headers_traceparent_only)
    expected_carrier_traceparent_only = {"traceparent": "00-abc-def-01"}
    mock_propagator_instance.extract.assert_called_with(carrier=expected_carrier_traceparent_only)
    assert result_traceparent_only == mock_context

    # Test with other headers but no trace context
    mock_propagator_instance.extract.reset_mock()
    headers_no_trace = [("other_header", b"value")]
    result_no_trace = observability.extract_trace_context_from_kafka_headers(headers_no_trace)
    expected_carrier_no_trace = {"other_header": "value"}
    mock_propagator_instance.extract.assert_called_with(carrier=expected_carrier_no_trace) # extract will be called
    assert result_no_trace == mock_context # extract will return a new context if no parent is found

    # Test with empty headers list
    mock_propagator_instance.extract.reset_mock()
    result_empty = observability.extract_trace_context_from_kafka_headers([])
    assert result_empty is None # Function returns None if headers are empty
    mock_propagator_instance.extract.assert_not_called() # Should not call extract if headers are empty

    # Test with None headers
    mock_propagator_instance.extract.reset_mock()
    result_none = observability.extract_trace_context_from_kafka_headers(None)
    assert result_none is None # Function returns None if headers are None
    mock_propagator_instance.extract.assert_not_called()

    # Test with headers where value is None (should be filtered out)
    mock_propagator_instance.extract.reset_mock()
    headers_with_none_value = [("traceparent", None), ("real_header", b"real_value")]
    result_none_value = observability.extract_trace_context_from_kafka_headers(headers_with_none_value)
    expected_carrier_none_value = {"real_header": "real_value"}
    mock_propagator_instance.extract.assert_called_with(carrier=expected_carrier_none_value)
    assert result_none_value == mock_context
