# API Router for Persons
from fastapi import APIRouter, Depends, HTTPException
from typing import List
import logging
from motor.motor_asyncio import AsyncIOMotorDatabase # Added for type hinting

from case_management_service.infrastructure.database import schemas as db_schemas
from case_management_service.infrastructure.database import read_models as read_model_ops
from case_management_service.infrastructure.database.connection import get_db # Added get_db import

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/persons/case/{case_id}", response_model=List[db_schemas.PersonDB], tags=["Persons"])
async def list_persons_for_case_api(case_id: str, limit: int = 10, skip: int = 0, db: AsyncIOMotorDatabase = Depends(get_db)): # Renamed function & Injected db
    try:
        persons = await read_model_ops.list_persons_for_case_from_read_model(db=db, case_id=case_id, limit=limit, skip=skip) # Passed db
        return persons
    except Exception as e:
        logger.error(f"Error listing persons for case {case_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list persons for case {case_id}")
