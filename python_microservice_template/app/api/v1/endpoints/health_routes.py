# API Router for Health Checks
from fastapi import APIRouter, Depends, HTTPException
import logging

# Import settings dependency from the DI module
# Path is from python_microservice_template/app/api/v1/endpoints to python_microservice_template/infra/di.py
from .....infra.di import SettingsDep
# from .....infra.db.mongo import db_session_dependency # Example if health check used DB

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get(
    "/health",
    tags=["Monitoring"],
    summary="Perform a Health Check",
    response_description="Returns the health status of the service."
    # response_model=Dict[str, str] # More specific response model if desired
)
async def health_check(settings: SettingsDep): # Inject settings
    """
    Checks the operational status of the service.
    For this basic template, it always returns OK.
    Can be expanded to check database connections, external services, etc.
    """
    logger.info(f"Health check requested for service: {settings.SERVICE_NAME}")
    # Basic health check - always OK for the template
    status = {"status": "ok", "service_name": settings.SERVICE_NAME}

    # Example: Add DB connection check if needed
    # This example assumes db_session_dependency is set up and potentially uses Motor for async.
    # The current mongo.py is sync and doesn't install pymongo/motor by default.
    # try:
    #     db = await db_session_dependency()
    #     # For PyMongo, commands are sync. For Motor, they are async.
    #     # Example with PyMongo (would need to be run in threadpool for async endpoint or use Motor)
    #     # client = get_mongo_client() # Assuming get_mongo_client is sync
    #     # client.admin.command('ping')
    #     status["database_status"] = "connected_placeholder" # Placeholder
    # except Exception as e:
    #     logger.error(f"Health check: Database connection failed: {e}", exc_info=True)
    #     status["database_status"] = "disconnected_placeholder"
    #     # Optionally, make overall health fail if DB is critical
    #     # raise HTTPException(status_code=503, detail="Database not available")

    return status
