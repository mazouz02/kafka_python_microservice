# Operations for the RequiredDocuments Read Model Collection
import logging
from typing import List, Optional, Dict, Any
import datetime

from .connection import get_database
from .schemas import RequiredDocumentDB # The DB schema for required documents

logger = logging.getLogger(__name__)
DOCUMENT_REQUIREMENTS_COLLECTION = "document_requirements"

async def add_required_document(doc_requirement: RequiredDocumentDB) -> RequiredDocumentDB:
    """Adds a new document requirement record to the collection."""
    db = await get_database()
    # Pydantic default_factory for id, created_at, updated_at handles their initialization.
    # status also has a default in the schema.

    doc_dict = doc_requirement.model_dump()

    await db[DOCUMENT_REQUIREMENTS_COLLECTION].insert_one(doc_dict)
    logger.info(f"Added document requirement ID: {doc_requirement.id} for entity {doc_requirement.entity_id} (type: {doc_requirement.document_type})")
    return doc_requirement

async def update_required_document_status_and_meta(
    doc_requirement_id: str,
    new_status: str,
    metadata_update: Optional[Dict[str, Any]] = None,
    notes_to_add: Optional[List[str]] = None
) -> Optional[RequiredDocumentDB]:
    """Updates the status and optionally metadata/notes of a document requirement."""
    db = await get_database()

    set_operations: Dict[str, Any] = {
        "status": new_status,
        "updated_at": datetime.datetime.now(datetime.UTC)
    }
    push_operations: Optional[Dict[str, Any]] = None

    if metadata_update is not None:
        # This will overwrite the entire metadata field if provided.
        # For merging or updating specific sub-fields, a more complex update query
        # or read-modify-write pattern would be needed.
        set_operations["metadata"] = metadata_update

    if notes_to_add and len(notes_to_add) > 0 : # Ensure there are notes to add
        push_operations = {"notes": {"$each": notes_to_add}}

    # Construct the update query
    update_query: Dict[str, Any] = {}
    if set_operations:
        update_query["$set"] = set_operations
    if push_operations:
        update_query["$push"] = push_operations

    if not update_query: # Nothing to update
        logger.info(f"No update operations specified for document requirement ID: {doc_requirement_id}")
        return await get_required_document_by_id(doc_requirement_id)


    result = await db[DOCUMENT_REQUIREMENTS_COLLECTION].update_one(
        {"id": doc_requirement_id},
        update_query
    )

    if result.matched_count == 0:
        logger.warning(f"Document requirement ID: {doc_requirement_id} not found for status update.")
        return None

    if result.modified_count == 0 and not push_operations : # Check if anything actually changed beyond what might have been $pushed
        logger.info(f"Document requirement ID: {doc_requirement_id} status was already {new_status} and no other fields changed.")
    else:
        logger.info(f"Updated status for document requirement ID: {doc_requirement_id} to {new_status}.")

    updated_doc = await db[DOCUMENT_REQUIREMENTS_COLLECTION].find_one({"id": doc_requirement_id})
    return RequiredDocumentDB(**updated_doc) if updated_doc else None

async def get_required_document_by_id(doc_requirement_id: str) -> Optional[RequiredDocumentDB]:
    """Retrieves a specific document requirement by its ID."""
    db = await get_database()
    doc = await db[DOCUMENT_REQUIREMENTS_COLLECTION].find_one({"id": doc_requirement_id})
    if doc:
        return RequiredDocumentDB(**doc)
    return None

async def list_required_documents(
    case_id: Optional[str] = None,
    entity_id: Optional[str] = None,
    entity_type: Optional[str] = None,
    status: Optional[str] = None,
    is_required: Optional[bool] = None # Added filter for is_required
) -> List[RequiredDocumentDB]:
    """Lists document requirements based on provided filters."""
    db = await get_database()
    query_filter: Dict[str, Any] = {}
    if case_id:
        query_filter["case_id"] = case_id
    if entity_id:
        query_filter["entity_id"] = entity_id
    if entity_type:
        query_filter["entity_type"] = entity_type
    if status:
        query_filter["status"] = status
    if is_required is not None: # Check for None explicitly as False is a valid value
        query_filter["is_required"] = is_required

    docs_cursor = db[DOCUMENT_REQUIREMENTS_COLLECTION].find(query_filter).sort("created_at", 1)
    documents = await docs_cursor.to_list(length=None) # Get all matching documents
    return [RequiredDocumentDB(**doc) for doc in documents]
