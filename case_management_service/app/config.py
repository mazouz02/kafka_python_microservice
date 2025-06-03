# Application Configuration using Pydantic BaseSettings
from pydantic_settings import BaseSettings
from typing import Optional

class AppSettings(BaseSettings):
    # MongoDB
    MONGO_DETAILS: str = "mongodb://localhost:27017"
    DB_NAME: str = "case_management_db"

    # Kafka
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    KAFKA_TOPIC_NAME: str = "kyc_events"
    KAFKA_CONSUMER_GROUP_ID: str = "case_management_group_cqrs_refactored" # Matches consumer

    # Observability
    LOG_LEVEL: str = "INFO"
    OTEL_EXPORTER_OTLP_TRACES_ENDPOINT: Optional[str] = None
    OTEL_EXPORTER_OTLP_METRICS_ENDPOINT: Optional[str] = None
    SERVICE_NAME_API: str = "case-management-api"
    SERVICE_NAME_CONSUMER: str = "case-management-consumer"


    class Config:
        # Optional: if you have a .env file for local development
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore" # Ignore extra fields from .env

# Instantiate settings to be imported by other modules
settings = AppSettings()

# Log settings on import for visibility (optional)
import logging
logger = logging.getLogger(__name__)
# logger.info(f"Application settings loaded: {settings.model_dump_json(indent=2)}")
# Avoid logging sensitive details if any are present in future settings.
logger.info("Application settings module initialized.")
