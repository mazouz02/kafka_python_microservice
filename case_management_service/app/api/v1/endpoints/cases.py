# API Router for Cases
from fastapi import APIRouter, Depends, HTTPException, Body
import logging
from typing import List, Optional
from motor.motor_asyncio import AsyncIOMotorDatabase # Added for type hinting

from case_management_service.infrastructure.database import schemas as db_schemas
from case_management_service.infrastructure.database import read_models as read_model_ops
from case_management_service.infrastructure.database.connection import get_db # Added get_db import
from case_management_service.app.service.commands.models import CreateCaseCommand # Updated import path
from case_management_service.app.service.commands.handlers import handle_create_case_command
from case_management_service.app.service.exceptions import KafkaProducerError, ConcurrencyConflictError # Import custom exceptions

# get_database might not be needed directly if read_model_ops handles it.

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/cases/{case_id}", response_model=Optional[db_schemas.CaseManagementDB], tags=["Cases"])
async def get_case_by_id(case_id: str, db: AsyncIOMotorDatabase = Depends(get_db)): # Injected db
    try:
        case_doc = await read_model_ops.get_case_by_id_from_read_model(db=db, case_id=case_id) # Passed db
        if not case_doc:
            # FastAPI handles Optional response model by returning null in JSON if None is returned.
            # If explicit 404 is desired for "not found":
            # raise HTTPException(status_code=404, detail="Case not found")
            return None
        return case_doc
    except Exception as e:
        logger.error(f"Error retrieving case {case_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to retrieve case {case_id}")


@router.get("/cases", response_model=List[db_schemas.CaseManagementDB], tags=["Cases"])
async def list_cases(limit: int = 10, skip: int = 0, db: AsyncIOMotorDatabase = Depends(get_db)): # Injected db
    try:
        cases = await read_model_ops.list_cases_from_read_model(db=db, limit=limit, skip=skip) # Passed db
        return cases
    except Exception as e:
        logger.error(f"Error listing cases: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list cases")

@router.post(
    "/cases",
    status_code=202,
    summary="Create a new case",
    tags=["Cases"],
)
async def create_case_api( # Will require db for handle_create_case_command later
    request_data: CreateCaseCommand = Body(...),
    db: AsyncIOMotorDatabase = Depends(get_db) # Added db for future use
):
    """
    Publish a CreateCaseCommand to start a new case flow.
    """
    try:
        # case_id = await handle_create_case_command(request_data) # This will need db
        # For now, we'll assume handle_create_case_command will be refactored separately
        # and will correctly receive 'db'.
        # Temporarily, let's pass db. This anticipates the next step of refactoring command handlers.
        # The handle_create_case_command now also requires kafka_producer and config_client,
        # which are injected by Depends in the handler itself, not passed from here.
        # This API endpoint is only passing `db` and `request_data` (which is the command).
        # This needs to be aligned: either the API passes all dependencies, or the handler fetches them.
        # For now, assuming the handler's DI setup via FastAPI for kafka_producer & config_client works.
        case_id = await handle_create_case_command(db=db, command=request_data)
        return {"case_id": case_id}
    except ConcurrencyConflictError as cce:
        logger.warning(f"Concurrency conflict during case creation for client {request_data.client_id}: {cce}")
        raise HTTPException(status_code=409, detail=str(cce))
    except KafkaProducerError as kpe:
        logger.error(f"Kafka producer error during case creation: {kpe}", exc_info=True)
        # Return a specific error code, e.g., 502 Bad Gateway, if Kafka is essential for this operation's success acknowledgement
        raise HTTPException(status_code=502, detail=f"Failed to publish essential notification event: {kpe}")
    except ValueError as ve:
        # for validation errors from the command model
        logger.warning(f"Validation error creating case: {ve}")
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"Unexpected error creating case: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An unexpected error occurred while creating the case.")
