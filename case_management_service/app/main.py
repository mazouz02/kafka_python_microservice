# FastAPI Application Entry Point
import logging # logging is configured by observability, but import still needed for direct use if any.
from fastapi import FastAPI, HTTPException, Depends
from typing import List, Optional

# Configuration and Observability (these should be among the very first imports)
from case_management_service.app.config import settings
from case_management_service.app.observability import setup_opentelemetry, logger # logger is already configured by observability

# Initialize OpenTelemetry (using service name from settings)
# This needs to be called BEFORE instrumentors or any traced code.
setup_opentelemetry(service_name=settings.SERVICE_NAME_API)

# Import instrumentors after OTel SDK is initialized
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.pymongo import PymongoInstrumentor

# Database connection and read model operations
from case_management_service.infrastructure.database.connection import connect_to_mongo, close_mongo_connection, get_database
from case_management_service.infrastructure.database import schemas as db_schemas # DB Pydantic Models
from case_management_service.infrastructure.database import read_models as read_model_ops # DB query functions
# Raw event store might be needed if there are API endpoints to add/query raw events directly (besides Kafka)
# from case_management_service.infrastructure.database.raw_event_store import add_raw_event_to_store

# --- FastAPI Application Instance ---
app = FastAPI(
    title="Case Management Service (Refactored)",
    description="Manages cases and associated persons from Kafka events. CQRS architecture.",
    version="0.2.0" # Updated version
)

# --- Event Handlers for DB Connection & OTel Instrumentation ---
@app.on_event("startup")
async def startup_event():
    logger.info("FastAPI application startup...")
    try:
        connect_to_mongo() # Uses settings from config.py via database.connection
        # Verify DB connection by trying to get the db instance
        await get_database()
        logger.info("MongoDB connection established for FastAPI app.")

        # Instrument PyMongo - Call once per process after DB is likely connectable
        # and OTel SDK is ready.
        PymongoInstrumentor().instrument()
        logger.info("PyMongo instrumentation complete.")

    except Exception as e:
        logger.error(f"Failed during startup: {e}", exc_info=True)
        # Depending on policy, you might want the app to fail starting.

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("FastAPI application shutdown...")
    close_mongo_connection()
    logger.info("MongoDB connection closed for FastAPI app.")

# Instrument FastAPI itself (after app object created, before routes usually)
FastAPIInstrumentor.instrument_app(app)
logger.info("FastAPI instrumentation complete.")


# --- API Endpoints (Querying Read Models) ---
@app.get("/health", tags=["Monitoring"])
async def health_check(db = Depends(get_database)): # get_database will provide the db session
    mongodb_status = "connected"
    try:
        # Ping DB via the an admin command
        await db.command('ping') # db is the result of get_database()
    except Exception as e:
        logger.error(f"MongoDB health check ping failed: {e}")
        mongodb_status = "disconnected"
    return {"status": "ok", "components": {"mongodb": mongodb_status}, "service_name": settings.SERVICE_NAME_API}

# Endpoint to retrieve stored raw events (kept for demonstration/debugging)
@app.get("/events/raw", response_model=List[db_schemas.RawEventDB], tags=["Events"])
async def list_raw_events(limit: int = 10, skip: int = 0, db = Depends(get_database)):
    events_cursor = db.raw_events.find().limit(limit).skip(skip).sort("received_at", -1)
    events = await events_cursor.to_list(length=limit)
    return [db_schemas.RawEventDB(**event) for event in events]


@app.get("/cases/{case_id}", response_model=Optional[db_schemas.CaseManagementDB], tags=["Cases"])
async def get_case_by_id(case_id: str): # db dependency implicitly handled by read_model_ops
    case_doc = await read_model_ops.get_case_by_id_from_read_model(case_id=case_id)
    if not case_doc:
        return None # FastAPI will return 200 with null body if Optional allows it
                    # raise HTTPException(status_code=404, detail="Case not found") # For explicit 404
    return case_doc

@app.get("/cases", response_model=List[db_schemas.CaseManagementDB], tags=["Cases"])
async def list_cases(limit: int = 10, skip: int = 0):
    cases = await read_model_ops.list_cases_from_read_model(limit=limit, skip=skip)
    return cases

@app.get("/persons/case/{case_id}", response_model=List[db_schemas.PersonDB], tags=["Persons"])
async def list_persons_for_case(case_id: str, limit: int = 10, skip: int = 0):
    persons = await read_model_ops.list_persons_for_case_from_read_model(case_id=case_id, limit=limit, skip=skip)
    return persons

# To run this app (example): uvicorn case_management_service.app.main:app --reload --port 8000
# Ensure PYTHONPATH includes the root of the project if running from elsewhere.
