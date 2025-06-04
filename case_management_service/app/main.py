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

# API Routers
from case_management_service.app.api.routers import health as health_router
from case_management_service.app.api.routers import cases as cases_router
from case_management_service.app.api.routers import persons as persons_router
from case_management_service.app.api.routers import raw_events as raw_events_router


# --- FastAPI Application Instance ---
app = FastAPI(
    title="Case Management Service (API Routers)",
    description="Manages cases and associated persons. Uses API routers.",
    version="0.3.0" # Updated version
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
    except Exception as e:
        logger.error(f"Failed during startup: {e}", exc_info=True)

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("FastAPI application shutdown...")
    close_mongo_connection()
    logger.info("MongoDB connection closed.")

# Instrument FastAPI app (after app created, before routes included is also fine)
FastAPIInstrumentor.instrument_app(app)
logger.info("FastAPI instrumentation complete.")

# Include API Routers
app.include_router(health_router.router) # No prefix, direct /health
app.include_router(raw_events_router.router, prefix="/api/v1") # Example prefix, tags are in router file
app.include_router(cases_router.router, prefix="/api/v1")
app.include_router(persons_router.router, prefix="/api/v1")

logger.info("API routers included. Application setup complete.")

# To run: uvicorn case_management_service.app.main:app --reload --port 8000
