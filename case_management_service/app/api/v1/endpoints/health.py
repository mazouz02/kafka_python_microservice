# API Router for Health Checks
from fastapi import APIRouter, Depends
import logging

# Assuming get_database and settings are still accessible via these paths after full import resolution
# For now, these are placeholders for where they *will* be correctly imported from.
from case_management_service.infrastructure.database.connection import get_db # Changed to get_db
from case_management_service.app.config import settings
from motor.motor_asyncio import AsyncIOMotorDatabase # Added for type hinting

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/health", tags=["Monitoring"])
async def health_check(db: AsyncIOMotorDatabase = Depends(get_db)): # Changed to get_db and added type hint
    mongodb_status = "connected"
    try:
        await db.command('ping') # Ping DB
    except Exception as e:
        logger.error(f"MongoDB health check ping failed: {e}")
        mongodb_status = "disconnected"
    return {"status": "ok", "components": {"mongodb": mongodb_status}, "service_name": settings.SERVICE_NAME_API}
