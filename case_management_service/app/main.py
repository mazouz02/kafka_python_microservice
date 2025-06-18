# FastAPI Application Entry Point (Refactored with API Routers)
import logging
from fastapi import FastAPI

# Configuration and Observability
from case_management_service.app.config import settings
from case_management_service.app.observability import setup_opentelemetry, logger

# Initialize OpenTelemetry
setup_opentelemetry(service_name=settings.SERVICE_NAME_API)

# Import instrumentors after OTel SDK is initialized
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.pymongo import PymongoInstrumentor

# Database connection
from case_management_service.infrastructure.database.connection import connect_to_mongo, close_mongo_connection, get_database
# Kafka Producer lifecycle
from case_management_service.infrastructure.kafka.producer import startup_kafka_producer, shutdown_kafka_producer


# API Routers
from case_management_service.app.api.routers import health as health_router
from case_management_service.app.api.routers import cases as cases_router
from case_management_service.app.api.routers import persons as persons_router
from case_management_service.app.api.routers import raw_events as raw_events_router
from case_management_service.app.api.routers import documents as documents_router

# --- FastAPI Application Instance ---
app = FastAPI(
    title="Case Management Service (API Routers)",
    description="Manages cases and associated persons. Uses API routers.",
    version="0.3.0"
)

# --- Event Handlers for DB Connection & OTel Instrumentation ---
@app.on_event("startup")
async def startup_event():
    logger.info("FastAPI application startup (with routers)...")
    try:
        connect_to_mongo()
        await get_database()
        logger.info("MongoDB connection established.")

        PymongoInstrumentor().instrument()
        logger.info("PyMongo instrumentation complete.")

        await startup_kafka_producer() # Start Kafka producer polling
        logger.info("Kafka Producer polling started.")

    except Exception as e:
        logger.error(f"Failed during startup: {e}", exc_info=True)
        # Depending on policy, might want to raise to prevent app start on critical init failure

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("FastAPI application shutdown...")

    await shutdown_kafka_producer() # Stop Kafka producer polling and flush
    logger.info("Kafka Producer shutdown initiated and flushed.")

    close_mongo_connection()
    logger.info("MongoDB connection closed.")

# Instrument FastAPI app (after app created, before routes included is also fine)
FastAPIInstrumentor.instrument_app(app) # Temporarily commented out for debugging
logger.info("FastAPI instrumentation complete.") # Temporarily commented out for debugging

# Include API Routers
app.include_router(health_router.router)
app.include_router(raw_events_router.router, prefix="/api/v1")
app.include_router(cases_router.router, prefix="/api/v1")
app.include_router(persons_router.router, prefix="/api/v1")
app.include_router(documents_router.router, prefix="/api/v1/documents", tags=["Document Requirements"])

logger.info("API routers included. Application setup complete.")

# To run: uvicorn case_management_service.app.main:app --reload --port 8000
