# Application Configuration using Pydantic BaseSettings
from pydantic_settings import BaseSettings
from typing import Optional

class AppSettings(BaseSettings):
    # MongoDB
    MONGO_DETAILS: str = "mongodb://mongo:27017"
    DB_NAME: str = "case_management_db"

    # Kafka
    KAFKA_BOOTSTRAP_SERVERS: str = "kafka:29092"
    KAFKA_TOPIC_NAME: str = "kyc_events_docker" # Main topic for case events
    KAFKA_CONSUMER_GROUP_ID: str = "case_management_group_cqrs_refactored"

    # Observability
    LOG_LEVEL: str = "INFO"
    OTEL_EXPORTER_OTLP_TRACES_ENDPOINT: Optional[str] = None
    OTEL_EXPORTER_OTLP_METRICS_ENDPOINT: Optional[str] = None
    SERVICE_NAME_API: str = "case-management-api"
    SERVICE_NAME_CONSUMER: str = "case-management-consumer"

    # Configuration Service Client
    CONFIG_SERVICE_URL: Optional[str] = None # e.g., http://localhost:8081/api/v1/notification-rules

    # Kafka Topic for Notifications
    NOTIFICATION_KAFKA_TOPIC: str = "notification_events"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

# Instantiate settings to be imported by other modules
settings = AppSettings()

# Log settings on import for visibility (optional)
import logging
logger = logging.getLogger(__name__)
# logger.info(f"Application settings loaded: {settings.model_dump_json(indent=2)}")
# Avoid logging sensitive details if any are present in future settings.
logger.info("Application settings module initialized.")
