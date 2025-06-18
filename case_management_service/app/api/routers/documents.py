# API Router for Document Requirements
import logging
from fastapi import APIRouter, Depends, HTTPException, Body
from typing import List, Optional, Dict, Any
from pydantic import BaseModel # Ensure BaseModel is imported

from case_management_service.app.config import settings
# Command models
from case_management_service.app.service.commands import models as command_models
# Command handlers (or a dispatch function)
from case_management_service.app.service.commands import handlers as command_handlers
# DB Schemas (for response models)
from case_management_service.infrastructure.database import schemas as db_schemas
# DB Store for querying document requirements (for GET endpoints)
from case_management_service.infrastructure.database import document_requirements_store

logger = logging.getLogger(__name__)
router = APIRouter()

# --- Pydantic models for API request/response if they differ from command/db schemas ---
class DetermineDocRequirementsRequest(BaseModel):
    case_id: str
    entity_id: str
    entity_type: str # "PERSON" or "COMPANY"
    traitement_type: str # "KYC" or "KYB"
    case_type: str # e.g., "STANDARD_DUE_DILIGENCE"
    context_data: Optional[Dict[str, Any]] = None

class UpdateDocStatusRequest(BaseModel):
    new_status: str
    updated_by_actor_type: Optional[str] = None
    updated_by_actor_id: Optional[str] = None
    metadata_changes: Optional[Dict[str, Any]] = None
    notes_to_add: Optional[List[str]] = None


# --- API Endpoints ---

@router.post(
    "/determine-requirements",
    status_code=202,
    summary="Determine and record initial document requirements for an entity in a case."
)
async def determine_document_requirements_api(
    request_data: DetermineDocRequirementsRequest = Body(...)
):
    try:
        cmd = command_models.DetermineInitialDocumentRequirementsCommand(
            case_id=request_data.case_id,
            entity_id=request_data.entity_id,
            entity_type=request_data.entity_type,
            traitement_type=request_data.traitement_type,
            case_type=request_data.case_type,
            context_data=request_data.context_data
        )
        await command_handlers.handle_determine_initial_document_requirements(cmd)
        return {"message": "Document requirement determination process initiated."}
    except ValueError as ve:
        logger.warning(f"Validation error determining document requirements: {ve}")
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"Error determining document requirements: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to initiate document requirement determination.")


@router.put(
    "/{document_requirement_id}/status",
    response_model=db_schemas.RequiredDocumentDB, # Return updated document
    summary="Update the status of a specific document requirement."
)
async def update_document_status_api(
    document_requirement_id: str,
    request_data: UpdateDocStatusRequest = Body(...)
):
    try:
        cmd = command_models.UpdateDocumentStatusCommand(
            document_requirement_id=document_requirement_id,
            new_status=request_data.new_status,
            updated_by_actor_type=request_data.updated_by_actor_type,
            updated_by_actor_id=request_data.updated_by_actor_id,
            metadata_changes=request_data.metadata_changes,
            notes_to_add=request_data.notes_to_add
        )
        updated_doc_req_id = await command_handlers.handle_update_document_status(cmd)
        if not updated_doc_req_id:
            raise HTTPException(status_code=404, detail=f"Document requirement ID {document_requirement_id} not found or update failed.")

        final_doc = await document_requirements_store.get_required_document_by_id(updated_doc_req_id)
        if not final_doc:
             raise HTTPException(status_code=404, detail=f"Updated document requirement ID {updated_doc_req_id} not found after update.")
        return final_doc

    except ValueError as ve:
        logger.warning(f"Validation error updating document status for {document_requirement_id}: {ve}")
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"Error updating document status for {document_requirement_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update document status.")


@router.get(
    "/{document_requirement_id}",
    response_model=db_schemas.RequiredDocumentDB, # Changed from Optional to direct, will raise 404 if not found
    summary="Get details of a specific document requirement."
)
async def get_document_requirement_details_api(document_requirement_id: str):
    try:
        doc = await document_requirements_store.get_required_document_by_id(document_requirement_id)
        if not doc:
            raise HTTPException(status_code=404, detail=f"Document requirement ID {document_requirement_id} not found.")
        return doc
    except Exception as e:
        logger.error(f"Error retrieving document requirement {document_requirement_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve document requirement details.")


@router.get(
    "/case/{case_id}", # Changed path for better grouping by case
    response_model=List[db_schemas.RequiredDocumentDB],
    summary="List all document requirements for a specific case."
)
async def list_document_requirements_for_case_api( # Renamed for clarity
    case_id: str,
    entity_id: Optional[str] = None,
    entity_type: Optional[str] = None,
    status: Optional[str] = None,
    is_required: Optional[bool] = None # Added is_required filter
):
    try:
        docs = await document_requirements_store.list_required_documents(
            case_id=case_id,
            entity_id=entity_id,
            entity_type=entity_type,
            status=status,
            is_required=is_required
        )
        return docs
    except Exception as e:
        logger.error(f"Error listing document requirements for case {case_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list document requirements.")
