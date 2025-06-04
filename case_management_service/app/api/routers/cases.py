# API Router for Cases
from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional

from case_management_service.infrastructure.database import schemas as db_schemas
from case_management_service.infrastructure.database import read_models as read_model_ops
# get_database might not be needed directly if read_model_ops handles it.

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/cases/{case_id}", response_model=Optional[db_schemas.CaseManagementDB], tags=["Cases"])
async def get_case_by_id(case_id: str):
    try:
        case_doc = await read_model_ops.get_case_by_id_from_read_model(case_id=case_id)
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
async def list_cases(limit: int = 10, skip: int = 0):
    try:
        cases = await read_model_ops.list_cases_from_read_model(limit=limit, skip=skip)
        return cases
    except Exception as e:
        logger.error(f"Error listing cases: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list cases")
