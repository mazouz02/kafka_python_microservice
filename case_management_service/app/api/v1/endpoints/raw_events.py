# API Router for Raw Events
from fastapi import APIRouter, Depends, HTTPException
from typing import List
import logging
from motor.motor_asyncio import AsyncIOMotorDatabase # Added for type hinting

from case_management_service.infrastructure.database.connection import get_db # Changed to get_db
from case_management_service.infrastructure.database import schemas as db_schemas

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/events/raw", response_model=List[db_schemas.RawEventDB], tags=["Events"]) # Path will be prefixed by main app
async def list_raw_events(limit: int = 10, skip: int = 0, db: AsyncIOMotorDatabase = Depends(get_db)): # Changed to get_db and added type hint
    try:
        events_cursor = db.raw_events.find().limit(limit).skip(skip).sort("received_at", -1)
        events = await events_cursor.to_list(length=limit)
        return [db_schemas.RawEventDB(**event) for event in events]
    except Exception as e:
        logger.error(f"Error retrieving raw events: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve raw events")
