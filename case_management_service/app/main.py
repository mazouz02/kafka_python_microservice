# IMPORTANT: observability setup should be one of the first things.
from .observability import setup_opentelemetry, logger # Use the logger configured by observability

# Call OTel setup. This also ensures JSON logging is active.
# Name this service instance (e.g., if you have multiple services using the same core code)
setup_opentelemetry(service_name="case-management-api")

# Now other imports
from fastapi import FastAPI, HTTPException, Depends
from typing import List, Optional
import os # Already present in original file, ensure it's kept if used, or remove if not.

from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.pymongo import PymongoInstrumentor

# Assuming database.py and kafka_models.py are in the same directory or accessible
from .database import (
    connect_to_mongo,
    close_mongo_connection,
    get_database, # Make sure this can be used as a dependency
    RawEventDB, # For response model
    CaseManagementDB, PersonDB # For potential future endpoints
)
from .kafka_models import KafkaMessage # For potential future endpoints

# Configure logging - logger is already imported from observability
# logger = logging.getLogger(__name__) # This would get a child of the root logger configured by observability

# --- FastAPI Application Instance ---
app = FastAPI(
    title="Case Management Service",
    description="Manages cases and associated persons from Kafka events.",
    version="0.1.0"
)

# Instrument FastAPI
FastAPIInstrumentor.instrument_app(app)
logger.info("FastAPI instrumentation complete.")

# Instrument PyMongo - Call once per process
PymongoInstrumentor().instrument()
logger.info("PyMongo instrumentation complete.")


# --- Event Handlers for DB Connection ---
@app.on_event("startup")
async def startup_event():
    logger.info("FastAPI application startup...") # This logger will be JSON formatted
    try:
        connect_to_mongo()
        _ = await get_database()
        logger.info("MongoDB connection established for FastAPI app.")
    except Exception as e:
        logger.error(f"Failed to connect to MongoDB on startup: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("FastAPI application shutdown...")
    close_mongo_connection()
    logger.info("MongoDB connection closed for FastAPI app.")

# --- API Endpoints ---
@app.get("/health", tags=["Monitoring"])
async def health_check():
    mongodb_status = "connected"
    try:
        db_instance = await get_database()
        if db_instance is None:
             raise ConnectionError("MongoDB client not initialized")
        # The ping command itself will be traced by PymongoInstrumentor
        db_instance.admin.command('ping')
    except Exception as e:
        logger.error(f"MongoDB health check failed: {e}")
        mongodb_status = "disconnected"
    return {"status": "ok", "components": {"mongodb": mongodb_status}}

@app.get("/events/raw", response_model=List[RawEventDB], tags=["Events"])
async def list_raw_events(limit: int = 10, skip: int = 0, db = Depends(get_database)):
    if db is None:
        raise HTTPException(status_code=503, detail="Database service not available.")

    events_cursor = db.raw_events.find().limit(limit).skip(skip).sort("received_at", -1)
    events = await events_cursor.to_list(length=limit)
    return [RawEventDB(**event) for event in events]


@app.get("/cases/{case_id}", response_model=Optional[CaseManagementDB], tags=["Cases"])
async def get_case_by_id(case_id: str, db = Depends(get_database)):
    if db is None:
        raise HTTPException(status_code=503, detail="Database service not available.")
    case_doc = await db.cases.find_one({"id": case_id})
    if case_doc:
        return CaseManagementDB(**case_doc)
    return None

@app.get("/cases", response_model=List[CaseManagementDB], tags=["Cases"])
async def list_cases(limit: int = 10, skip: int = 0, db = Depends(get_database)):
    if db is None:
        raise HTTPException(status_code=503, detail="Database service not available.")

    cases_cursor = db.cases.find().limit(limit).skip(skip).sort("created_at", -1)
    cases = await cases_cursor.to_list(length=limit)
    return [CaseManagementDB(**case) for case in cases]

@app.get("/persons/case/{case_id}", response_model=List[PersonDB], tags=["Persons"])
async def list_persons_for_case(case_id: str, limit: int = 10, skip: int = 0, db = Depends(get_database)):
    if db is None:
        raise HTTPException(status_code=503, detail="Database service not available.")

    persons_cursor = db.persons.find({"case_id": case_id}).limit(limit).skip(skip).sort("created_at", 1)
    persons = await persons_cursor.to_list(length=limit)
    return [PersonDB(**person) for person in persons]

# --- Entry point for Uvicorn (if running directly) ---
# if __name__ == "__main__":
#     # Ensure environment variables for Kafka/Mongo are set if running directly
#     # Example: os.environ.setdefault('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092')
#     #          os.environ.setdefault('MONGO_DETAILS', 'mongodb://localhost:27017')
#     #          os.environ.setdefault('OTEL_EXPORTER_OTLP_TRACES_ENDPOINT', 'http://localhost:4317')
#     #          os.environ.setdefault('OTEL_EXPORTER_OTLP_METRICS_ENDPOINT', 'http://localhost:4317')
#     #          os.environ.setdefault('LOG_LEVEL', 'DEBUG') # For verbose OTel console logs
#     import uvicorn
#     port = int(os.environ.get("PORT", 8000))
#     # Uvicorn should be run from the command line as per FastAPI docs for --reload, etc.
#     # uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True) # 'main:app' if file is main.py
#     # If running this file directly: uvicorn.run(app, host="0.0.0.0", port=port)
#     logger.info(f"Starting Uvicorn directly on port {port}. Consider using CLI for production/reload.")
#     uvicorn.run(app, host="0.0.0.0", port=port)
