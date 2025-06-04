# API Router for Health Checks
from fastapi import APIRouter, Depends
import logging

# Assuming get_database and settings are still accessible via these paths after full import resolution
# For now, these are placeholders for where they *will* be correctly imported from.
from case_management_service.infrastructure.database.connection import get_database
from case_management_service.app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/health", tags=["Monitoring"])
async def health_check(db = Depends(get_database)): # get_database will provide the db session
    mongodb_status = "connected"
    try:
        await db.command('ping') # Ping DB
    except Exception as e:
        logger.error(f"MongoDB health check ping failed: {e}")
        mongodb_status = "disconnected"
    return {"status": "ok", "components": {"mongodb": mongodb_status}, "service_name": settings.SERVICE_NAME_API}
