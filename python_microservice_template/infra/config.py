# Pydantic Settings for Application Configuration
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
import logging

class AppSettings(BaseSettings):
    # Service Configuration
    SERVICE_NAME: str = "PythonMicroserviceTemplate"
    LOG_LEVEL: str = "INFO"

    # OpenTelemetry Configuration
    OTEL_EXPORTER_OTLP_ENDPOINT_HTTP: Optional[str] = None
    # OTEL_EXPORTER_OTLP_TRACES_ENDPOINT_GRPC: Optional[str] = None # Example for gRPC
    # OTEL_EXPORTER_OTLP_METRICS_ENDPOINT_GRPC: Optional[str] = None # Example for gRPC

    # Database Configuration (examples, uncomment and type appropriately in derived services)
    # MONGO_URI: Optional[str] = None
    # DB_NAME: Optional[str] = None

    # Messaging Configuration (examples)
    # KAFKA_BOOTSTRAP_SERVERS: Optional[str] = None
    # KAFKA_DEFAULT_TOPIC: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = AppSettings()

# Initialize logger for this module after settings are loaded
logger = logging.getLogger(__name__)
# Basic logging setup for when settings are loaded (application might refine this)
# This basicConfig might conflict if app/main.py or observability.py also calls it.
# It's often better to configure logging once at the application entry point.
# For a library/template module like this, just `logger = logging.getLogger(__name__)` is often enough,
# and the application using the template configures the root logger.
# However, logging settings here shows intent.
try:
    logging.basicConfig(level=settings.LOG_LEVEL.upper())
    logger.info(
        f"AppSettings loaded. SERVICE_NAME: {settings.SERVICE_NAME}, "
        f"LOG_LEVEL: {settings.LOG_LEVEL}, "
        f"OTLP HTTP Endpoint: {settings.OTEL_EXPORTER_OTLP_ENDPOINT_HTTP}"
    )
except Exception as e: # Catch potential errors during basicConfig if already configured
    logger.debug(f"Could not apply basicConfig from infra.config, possibly already configured: {e}")
