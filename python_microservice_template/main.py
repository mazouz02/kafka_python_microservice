# Main FastAPI Application File for the Microservice Template
import logging
from fastapi import FastAPI

# Import settings and OTel setup function
# These are relative to the location of main.py (which is in python_microservice_template/)
from .infra.config import settings
from .infra.telemetry.otel import setup_opentelemetry, instrument_fastapi_app
# Import lifecycle events for DB if used (placeholder for now)
# from .infra.db.mongo import close_mongo_client #, get_mongo_client (if sync connect at startup)

# Import API routers
from .app.api.v1.endpoints import health_routes # Relative from main.py

# Setup basic logging before OTel for early messages, using level from settings
# This basicConfig should ideally be called only once.
# If observability.py in a real service also calls it, it could lead to issues.
# For the template, this ensures logging is active if this main.py is run directly.
logging.basicConfig(level=settings.LOG_LEVEL.upper())
logger = logging.getLogger(settings.SERVICE_NAME) # Use service name for the main app logger

# Initialize OpenTelemetry (should be called early)
# The actual service_name used by OTel will be settings.SERVICE_NAME passed here.
setup_opentelemetry(app_name=settings.SERVICE_NAME)


# Create FastAPI app instance
app = FastAPI(
    title=settings.SERVICE_NAME,
    description="A template for Python microservices.",
    version="0.1.0", # Consider making this configurable via settings too
    # Add other FastAPI configurations like root_path if behind a proxy, etc.
)

# --- Lifespan Management (for startup/shutdown events) ---
# Example: Placeholder for DB connection pool or other resources
# @app.on_event("startup")
# async def startup_event():
#     logger.info("Application startup: Initializing resources...")
#     try:
#         # Example: Initialize MongoDB client if not managed by DI for each request
#         # get_mongo_client() # Initialize mongo client pool if not done by dependency
#         # logger.info("MongoDB client initialized (if MONGO_URI is set).")
#         pass
#     except Exception as e:
#         logger.error(f"Failed to initialize resources on startup: {e}", exc_info=True)
#     # Add other startup logic here (e.g., Kafka producer start from the main service)

# @app.on_event("shutdown")
# async def shutdown_event():
#     logger.info("Application shutdown: Cleaning up resources...")
#     # close_mongo_client() # Close mongo client pool
#     # Add other shutdown logic here (e.g., Kafka producer flush/close)

# Instrument FastAPI app with OpenTelemetry *after* app instance is created
instrument_fastapi_app(app)

# Include API routers
app.include_router(health_routes.router, prefix="/api/v1", tags=["Monitoring & Health"])
logger.info(f"Included health_routes under /api/v1 prefix.")

# Add a root endpoint for basic check (optional)
@app.get("/", tags=["General"])
async def root():
    return {"message": f"Welcome to {settings.SERVICE_NAME}"}

logger.info(f"'{settings.SERVICE_NAME}' application setup complete. API docs at /docs.")

# To run (from python_microservice_template directory, if this file is main.py):
# uvicorn main:app --reload --port 8000
# Or, if main.py is inside a 'src' or package dir, adjust path:
# uvicorn python_microservice_template.main:app --reload --port 8000 (if project root is in PYTHONPATH)
