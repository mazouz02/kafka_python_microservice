# FastAPI Application Entry Point (Refactored with API Routers)
import logging
from fastapi import FastAPI, Request # Added Request for app.state access in get_http_client
import httpx # Added httpx

# Configuration and Observability
from case_management_service.app.config import settings
from case_management_service.app.observability import setup_opentelemetry, logger

# Initialize OpenTelemetry
setup_opentelemetry(service_name=settings.SERVICE_NAME_API)

# Import instrumentors after OTel SDK is initialized
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.pymongo import PymongoInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor # Added httpx instrumentor

# Database connection
from case_management_service.infrastructure.database.connection import connect_to_mongo, close_mongo_connection, get_db
# Kafka Producer lifecycle
from case_management_service.infrastructure.kafka.producer import startup_kafka_producer, shutdown_kafka_producer


# API Routers
from case_management_service.app.api.v1.endpoints import health as health_router
from case_management_service.app.api.v1.endpoints import cases as cases_router
from case_management_service.app.api.v1.endpoints import persons as persons_router
from case_management_service.app.api.v1.endpoints import raw_events as raw_events_router
from case_management_service.app.api.v1.endpoints import documents as documents_router

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
        # Setup HTTP client
        app.state.http_client = httpx.AsyncClient(timeout=settings.DEFAULT_HTTP_TIMEOUT)
        HTTPXClientInstrumentor().instrument() # Instrument httpx client
        logger.info(f"HTTPX AsyncClient initialized with timeout {settings.DEFAULT_HTTP_TIMEOUT} and instrumented.")

        connect_to_mongo()
        # get_db() is an async generator, so we need to iterate it or use `async with`
        # For startup, just ensuring the connection is made by connect_to_mongo and db is set is enough.
        # If we needed the db object itself here, we'd do: `async for _db in get_db(): pass` (or similar)
        # However, connect_to_mongo() already sets the global db variable.
        # A direct call to `await get_db()` like `await get_database()` previously,
        # if get_db() was a simple async func, would be fine.
        # Since get_db() is now an async generator for FastAPI's Depends,
        # we can call it and iterate once to ensure it runs its course if needed,
        # but connect_to_mongo() should suffice for initializing the global `db` instance.
        # Let's confirm connect_to_mongo populates the global 'db' that get_db() yields.
        # The `get_db` function itself will call `connect_to_mongo` if db is None.
        # So, simply calling connect_to_mongo here is sufficient.
        # The previous `await get_database()` call was to ensure the connection was truly up.
        # We can achieve a similar check by trying to get the db instance via the generator.
        async for _ in get_db(): # Iterate once to ensure get_db logic (including connect_to_mongo if needed) runs
            break
        logger.info("MongoDB connection established via get_db call.")

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

    if hasattr(app.state, 'http_client') and app.state.http_client:
        await app.state.http_client.aclose()
        logger.info("HTTPX AsyncClient closed.")

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
